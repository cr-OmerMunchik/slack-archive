"""SQLite storage + full-text search for slack-archive.

Design notes
------------
* One file, ``search.db``, holds everything: conversations, users, messages,
  files, and a contentless-external FTS5 index over the *plain* message text.
* ``messages`` has a synthetic integer ``id`` (rowid) so the FTS5 external
  content table can reference it cheaply. We rebuild the FTS index in one shot
  after a bulk load rather than maintaining triggers - ingest is a batch job.
* All search filters (conversation, type, author, date range) are plain columns
  on ``messages`` / ``conversations``; only the free-text part goes through FTS5.

Nothing here imports Flask, so the storage layer is independently testable.
"""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# Sentinel chars wrap FTS5 snippet highlights; we escape the snippet text for
# HTML and only then swap these for <mark> tags, so message text can't inject markup.
_HL_OPEN = "\x02"
_HL_CLOSE = "\x03"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id           TEXT PRIMARY KEY,   -- C.../G.../D... Slack id
    type         TEXT NOT NULL,      -- public_channel | private_channel | mpim | im
    name         TEXT,               -- channel name, group-DM handle list, or DM partner name
    real_name    TEXT,               -- for DMs: partner real name
    topic        TEXT,
    purpose      TEXT,
    num_members  INTEGER,
    is_archived  INTEGER DEFAULT 0,
    source_dir   TEXT,               -- directory name inside the export
    msg_count    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    name          TEXT,   -- handle
    real_name     TEXT,
    display_name  TEXT,
    is_bot        INTEGER DEFAULT 0,
    deleted       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,   -- rowid, referenced by FTS
    conv_id     TEXT NOT NULL,
    ts          TEXT NOT NULL,         -- Slack ts string (unique within a conversation)
    thread_ts   TEXT,                  -- parent thread ts, NULL if not threaded
    user_id     TEXT,
    type        TEXT,
    subtype     TEXT,
    epoch       REAL,                  -- seconds, for sorting + date filters
    text_raw    TEXT,                  -- original Slack mrkdwn
    text_plain  TEXT,                  -- mentions/links resolved to readable text (indexed)
    html        TEXT,                  -- pre-rendered display HTML
    has_files   INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    edited      INTEGER DEFAULT 0,
    UNIQUE (conv_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_msg_conv      ON messages (conv_id, epoch);
CREATE INDEX IF NOT EXISTS idx_msg_thread    ON messages (conv_id, thread_ts);
CREATE INDEX IF NOT EXISTS idx_msg_user      ON messages (user_id);
CREATE INDEX IF NOT EXISTS idx_msg_epoch     ON messages (epoch);

CREATE TABLE IF NOT EXISTS files (
    id         TEXT PRIMARY KEY,
    conv_id    TEXT,
    msg_ts     TEXT,
    name       TEXT,
    title      TEXT,
    mimetype   TEXT,
    filetype   TEXT,
    size       INTEGER,
    local_path TEXT,    -- path relative to the export root, or NULL if not downloaded
    permalink  TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_msg ON files (conv_id, msg_ts);

-- External-content FTS5 index over the readable message text.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text_plain,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
"""

CONV_TYPE_LABELS = {
    "public_channel": "Channel",
    "private_channel": "Private channel",
    "mpim": "Group DM",
    "im": "Direct message",
}


# --------------------------------------------------------------------------- #
# Connection / schema
# --------------------------------------------------------------------------- #
def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.__fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """Drop all data (used at the start of a full re-index)."""
    for tbl in ("messages_fts", "messages", "files", "users", "conversations", "meta"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.commit()
    init_schema(conn)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# --------------------------------------------------------------------------- #
# Free-text query handling
# --------------------------------------------------------------------------- #
def to_match_query(raw: str) -> str:
    """Turn a user's free-text query into a safe FTS5 MATCH expression.

    Each whitespace-separated token is wrapped in double quotes (so FTS special
    characters can't break the query), combined with implicit AND. A trailing
    ``*`` on a token is preserved as a prefix search. A token already wrapped in
    double quotes is treated as a phrase.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    # Respect explicit "quoted phrases" by keeping them intact.
    tokens: list[str] = []
    for part in _split_keep_quotes(raw):
        part = part.strip()
        if not part:
            continue
        prefix = ""
        if part.endswith("*") and not part.startswith('"'):
            prefix = "*"
            part = part[:-1]
        part = part.strip('"')
        if not part:
            continue
        esc = part.replace('"', '""')
        tokens.append(f'"{esc}"{prefix}')
    return " ".join(tokens)


def _split_keep_quotes(s: str) -> list[str]:
    out, buf, in_q = [], [], False
    for ch in s:
        if ch == '"':
            in_q = not in_q
            buf.append(ch)
        elif ch.isspace() and not in_q:
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


# --------------------------------------------------------------------------- #
# Read queries (used by the web server)
# --------------------------------------------------------------------------- #
def list_conversations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT c.*, COALESCE(c.msg_count, 0) AS n
        FROM conversations c
        ORDER BY
            CASE c.type
                WHEN 'public_channel' THEN 0
                WHEN 'private_channel' THEN 1
                WHEN 'mpim' THEN 2
                WHEN 'im' THEN 3 ELSE 4 END,
            n DESC, c.name COLLATE NOCASE
        """
    ).fetchall()


def get_conversation(conn: sqlite3.Connection, conv_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT COUNT(*) AS m FROM messages").fetchone()
    convs = conn.execute(
        "SELECT type, COUNT(*) AS c FROM conversations GROUP BY type"
    ).fetchall()
    files = conn.execute("SELECT COUNT(*) AS f FROM files").fetchone()
    return {
        "messages": row["m"],
        "files": files["f"],
        "by_type": {r["type"]: r["c"] for r in convs},
        "indexed_at": get_meta(conn, "indexed_at"),
        "export_root": get_meta(conn, "export_root"),
    }


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    conv_ids: Optional[Sequence[str]] = None,
    types: Optional[Sequence[str]] = None,
    user_id: Optional[str] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Full-text search. Returns (rows, total_count)."""
    match = to_match_query(query)
    if not match:
        return [], 0

    where = ["messages_fts MATCH :match"]
    params: dict[str, Any] = {"match": match}
    if conv_ids:
        ph = ",".join(f":c{i}" for i in range(len(conv_ids)))
        where.append(f"m.conv_id IN ({ph})")
        params.update({f"c{i}": v for i, v in enumerate(conv_ids)})
    if types:
        ph = ",".join(f":t{i}" for i in range(len(types)))
        where.append(f"c.type IN ({ph})")
        params.update({f"t{i}": v for i, v in enumerate(types)})
    if user_id:
        where.append("m.user_id = :uid")
        params["uid"] = user_id
    if date_from is not None:
        where.append("m.epoch >= :df")
        params["df"] = date_from
    if date_to is not None:
        where.append("m.epoch <= :dt")
        params["dt"] = date_to
    where_sql = " AND ".join(where)

    total = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        JOIN conversations c ON c.id = m.conv_id
        WHERE {where_sql}
        """,
        params,
    ).fetchone()["n"]

    params["limit"] = limit
    params["offset"] = offset
    rows = conn.execute(
        f"""
        SELECT
            m.id, m.conv_id, m.ts, m.thread_ts, m.user_id, m.epoch,
            m.has_files, m.reply_count,
            c.name AS conv_name, c.type AS conv_type, c.real_name AS conv_real,
            u.display_name, u.real_name, u.name AS user_name,
            snippet(messages_fts, 0, char(2), char(3), '…', 18) AS snippet
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        JOIN conversations c ON c.id = m.conv_id
        LEFT JOIN users u ON u.id = m.user_id
        WHERE {where_sql}
        ORDER BY bm25(messages_fts)
        LIMIT :limit OFFSET :offset
        """,
        params,
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        raw = d.get("snippet") or ""
        d["snippet"] = (
            html.escape(raw).replace(_HL_OPEN, "<mark>").replace(_HL_CLOSE, "</mark>")
        )
        out.append(d)
    return out, total


def distinct_authors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Users who authored at least one message (for the 'From person' filter)."""
    return conn.execute(
        """
        SELECT u.id, u.display_name, u.real_name, u.name
        FROM users u
        WHERE u.id IN (SELECT DISTINCT user_id FROM messages WHERE user_id IS NOT NULL)
        ORDER BY COALESCE(NULLIF(u.display_name,''), NULLIF(u.real_name,''), u.name, u.id) COLLATE NOCASE
        """
    ).fetchall()


def conversation_messages(
    conn: sqlite3.Connection,
    conv_id: str,
    *,
    limit: int = 200,
    before_epoch: Optional[float] = None,
    after_epoch: Optional[float] = None,
) -> list[dict]:
    """Top-level (non-reply) messages of a conversation, oldest->newest within a window."""
    where = ["m.conv_id = :cid", "(m.thread_ts IS NULL OR m.thread_ts = '' OR m.thread_ts = m.ts)"]
    params: dict[str, Any] = {"cid": conv_id, "limit": limit}
    if before_epoch is not None:
        where.append("m.epoch < :before")
        params["before"] = before_epoch
    if after_epoch is not None:
        where.append("m.epoch > :after")
        params["after"] = after_epoch
    rows = conn.execute(
        f"""
        SELECT m.*, u.display_name, u.real_name, u.name AS user_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.user_id
        WHERE {" AND ".join(where)}
        ORDER BY m.epoch
        LIMIT :limit
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def thread_messages(conn: sqlite3.Connection, conv_id: str, thread_ts: str) -> list[dict]:
    """All messages in a thread (the parent + replies), oldest->newest."""
    rows = conn.execute(
        """
        SELECT m.*, u.display_name, u.real_name, u.name AS user_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.user_id
        WHERE m.conv_id = :cid AND (m.ts = :tts OR m.thread_ts = :tts)
        ORDER BY m.epoch
        """,
        {"cid": conv_id, "tts": thread_ts},
    ).fetchall()
    return [dict(r) for r in rows]


def files_for_message(conn: sqlite3.Connection, conv_id: str, ts: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM files WHERE conv_id=? AND msg_ts=?", (conv_id, ts)
    ).fetchall()
    return [dict(r) for r in rows]


def users_in_conversation(conn: sqlite3.Connection, conv_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT DISTINCT u.id, u.display_name, u.real_name, u.name
        FROM messages m JOIN users u ON u.id = m.user_id
        WHERE m.conv_id = ?
        ORDER BY COALESCE(NULLIF(u.display_name,''), u.real_name, u.name)
        """,
        (conv_id,),
    ).fetchall()
