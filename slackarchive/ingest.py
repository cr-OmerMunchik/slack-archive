"""Parse slackdump *standard* export directories into the search database.

Export layout (slackdump v4, ``-type standard``)::

    export/
      channels.json   groups.json   mpims.json   dms.json   users.json
      attachments/                 # <fileID>-<name>  (downloaded files)
      <channel-name>/              # one dir per conversation
        2026-06-21.json            # an array of messages, one file per day
        ...

Multiple export dirs can be indexed into one database (e.g. your member-only
backup plus a separate export of hand-picked public channels). Downloaded files
are addressed relative to the *common parent* of all indexed exports, so a single
``export_root`` in the DB lets the web server serve every attachment.

Thread replies are ordinary messages in the daily files carrying ``thread_ts``;
we link them at query time, so ingest just stores every message.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import db as dbmod
from .slackfmt import render

_FILE_ID_RE = re.compile(r"^(F[A-Z0-9]+)-")   # standard layout: attachments/F<id>-name
_FILE_DIR_RE = re.compile(r"^(F[A-Z0-9]+)$")  # mattermost layout: __uploads/F<id>/name


def _load_json(path: Path) -> Any:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []


def _conv_type(obj: dict, default: str) -> str:
    if obj.get("is_im"):
        return "im"
    if obj.get("is_mpim"):
        return "mpim"
    if obj.get("is_private") or obj.get("is_group"):
        return "private_channel"
    if obj.get("is_channel") or obj.get("is_general"):
        return "public_channel"
    return default


def _detect_self(dms: list) -> str | None:
    """The current user is the member present in every 1:1 DM."""
    member_sets = [set(d.get("members") or []) for d in dms
                   if isinstance(d, dict) and d.get("members")]
    if not member_sets:
        return None
    common = set(member_sets[0])
    for s in member_sets[1:]:
        common &= s
    if len(common) == 1:
        return next(iter(common))
    # Fallback: the most frequently occurring member across DMs.
    counts: dict[str, int] = {}
    for s in member_sets:
        for m in s:
            counts[m] = counts.get(m, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _user_display(u: dict) -> dict:
    profile = u.get("profile") or {}
    return {
        "id": u.get("id"),
        "name": u.get("name") or "",
        "real_name": u.get("real_name") or profile.get("real_name") or "",
        "display_name": profile.get("display_name") or "",
        "is_bot": 1 if u.get("is_bot") else 0,
        "deleted": 1 if u.get("deleted") else 0,
    }


def _rich_text(block: dict) -> str:
    """Flatten a Block Kit rich_text block into Slack mrkdwn-ish text."""
    parts: list[str] = []

    def walk(el):
        if isinstance(el, list):
            for v in el:
                walk(v)
        elif isinstance(el, dict):
            t = el.get("type")
            if t == "text" and el.get("text"):
                parts.append(el["text"])
            elif t == "link":
                parts.append(el.get("text") or el.get("url") or "")
            elif t == "emoji" and el.get("name"):
                parts.append(f":{el['name']}:")
            elif t == "user" and el.get("user_id"):
                parts.append(f"<@{el['user_id']}>")
            elif t == "channel" and el.get("channel_id"):
                parts.append(f"<#{el['channel_id']}>")
            elif t == "broadcast" and el.get("range"):
                parts.append(f"<!{el['range']}>")
            for v in (el.get("elements") or []):
                walk(v)

    walk(block.get("elements") or [])
    return "".join(parts)


def _blocks_text(blocks) -> str:
    out: list[str] = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t in ("section", "header"):
            txt = b.get("text")
            if isinstance(txt, dict) and txt.get("text"):
                out.append(txt["text"])
            for f in (b.get("fields") or []):
                if isinstance(f, dict) and f.get("text"):
                    out.append(f["text"])
        elif t == "rich_text":
            rt = _rich_text(b)
            if rt:
                out.append(rt)
        elif t == "context":
            for e in (b.get("elements") or []):
                if isinstance(e, dict) and e.get("text"):
                    out.append(str(e["text"]))
    return "\n".join(out)


def _attachments_text(msg: dict) -> str:
    """App/bot messages (Jenkins, CI, GitHub…) carry their body in attachments, not text."""
    chunks: list[str] = []
    for a in (msg.get("attachments") or []):
        if not isinstance(a, dict):
            continue
        parts: list[str] = []
        for k in ("pretext", "author_name", "title", "text"):
            if a.get(k):
                parts.append(str(a[k]))
        for f in (a.get("fields") or []):
            if not isinstance(f, dict):
                continue
            title, value = f.get("title"), f.get("value")
            if title and value:
                parts.append(f"{title}: {value}")
            elif value or title:
                parts.append(str(value or title))
        nested = _blocks_text(a.get("blocks") or [])
        if nested:
            parts.append(nested)
        if not parts and a.get("fallback"):
            parts.append(str(a["fallback"]))
        if parts:
            chunks.append("\n".join(parts))
    return "\n\n".join(chunks)


def _message_content(msg: dict) -> str:
    """Full displayable text: the message text, else its Block Kit text, plus any
    attachment content (so app/bot messages aren't rendered blank)."""
    content = msg.get("text") or ""
    if not content:
        content = _blocks_text(msg.get("blocks") or [])
    extra = _attachments_text(msg)
    if extra:
        content = (content + "\n\n" + extra) if content else extra
    return content


def index_export(export_dir: str | Path, db_path: str | Path, *, verbose: bool = True) -> dict:
    """Index a single export directory (convenience wrapper)."""
    return index_paths([export_dir], db_path, verbose=verbose)


def _build_file_index(roots: list[Path], files_root: Path) -> dict[str, str]:
    """Map slackdump file ID -> path relative to files_root. Handles both export
    layouts: 'attachments/F<id>-name' (standard) and '__uploads/F<id>/name' (mattermost,
    used by the resumable archive)."""
    idx: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            m = _FILE_ID_RE.match(p.name)
            fid = m.group(1) if m else None
            if not fid:
                pm = _FILE_DIR_RE.match(p.parent.name)
                fid = pm.group(1) if pm else None
            if fid:
                idx.setdefault(fid, os.path.relpath(p.resolve(), files_root).replace("\\", "/"))
    return idx


def index_paths(export_dirs: Iterable[str | Path], db_path: str | Path, *,
                files_root: str | Path | None = None,
                attachment_roots: Iterable[str | Path] | None = None,
                verbose: bool = True) -> dict:
    """Index one or more export directories. Attachments are resolved from the export
    dirs plus any ``attachment_roots`` (e.g. the resumable archive's ``__uploads``), and
    served relative to ``files_root`` (defaults to the common parent of everything)."""
    roots = [Path(d).resolve() for d in export_dirs]
    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        raise FileNotFoundError("export directory not found: " + ", ".join(missing))
    if not roots:
        raise ValueError("no export directories given")
    att_roots = [Path(a).resolve() for a in (attachment_roots or [])]
    all_roots = roots + [a for a in att_roots if a.exists()]

    if files_root:
        files_root = Path(files_root).resolve()
    elif len(all_roots) == 1:
        files_root = all_roots[0]
    else:
        files_root = Path(os.path.commonpath([str(r) for r in all_roots]))

    file_index = _build_file_index(all_roots, files_root)

    conn = dbmod.connect(db_path)
    if not dbmod.fts5_available(conn):
        raise RuntimeError(
            "This Python's sqlite3 was built without FTS5. Install a Python with "
            "FTS5 support (the python.org Windows/macOS builds include it)."
        )
    dbmod.reset(conn)

    totals = {"messages": 0, "files": 0, "conversations": 0, "users": 0}
    for root in roots:
        if verbose:
            print(f"Indexing {root}", file=sys.stderr)
        counts = _ingest_one(conn, root, files_root, file_index, verbose=verbose)
        for k in totals:
            totals[k] += counts[k]

    # Drop conversations that ended up with no messages (Slack creates DM/group
    # channels that were never used); we don't want them cluttering the UI.
    conn.execute(
        "DELETE FROM conversations "
        "WHERE id NOT IN (SELECT DISTINCT conv_id FROM messages WHERE conv_id IS NOT NULL)"
    )
    totals["conversations"] = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

    dbmod.set_meta(conn, "export_root", str(files_root))
    dbmod.set_meta(conn, "indexed_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    conn.commit()
    dbmod.rebuild_fts(conn)
    conn.execute("PRAGMA optimize")
    conn.commit()
    conn.close()
    return totals


def _ingest_one(conn, export: Path, files_root: Path, file_index: dict[str, str], *, verbose: bool) -> dict:
    # ---- users ----
    users_raw = _load_json(export / "users.json")
    user_rows = [_user_display(u) for u in users_raw if isinstance(u, dict)]
    conn.executemany(
        "INSERT OR REPLACE INTO users(id,name,real_name,display_name,is_bot,deleted) "
        "VALUES(:id,:name,:real_name,:display_name,:is_bot,:deleted)",
        user_rows,
    )
    user_lookup: dict[str, str] = {
        r["id"]: (r["display_name"] or r["real_name"] or r["name"] or r["id"]) for r in user_rows
    }
    bot_ids = {r["id"] for r in user_rows if r["is_bot"]}
    bot_ids.add("USLACKBOT")

    def _is_bot(uid: str | None) -> bool:
        # bot_id authors start with "B"; Slackbot and flagged bot users are excluded too
        return bool(uid) and (uid.startswith("B") or uid in bot_ids)

    # ---- conversations (4 metadata files) ----
    self_id = _detect_self(_load_json(export / "dms.json"))
    convs: dict[str, dict] = {}
    dir_to_id: dict[str, str] = {}
    channel_lookup: dict[str, str] = {}

    def _names(member_ids: list[str]) -> str:
        return ", ".join(user_lookup.get(m, m) for m in member_ids)

    def add_conv(obj: dict, default_type: str) -> None:
        cid = obj.get("id")
        if not cid:
            return
        ctype = _conv_type(obj, default_type)
        members = obj.get("members") or []
        name = obj.get("name") or obj.get("name_normalized") or ""
        real = ""
        if ctype == "im":
            # dms.json entries are 1:1 DMs (their ids start with "D"). `members` can
            # include people merely @-tagged in the chat, so it's unreliable for naming -
            # this is a provisional label; we refine it from the real message authors
            # after ingesting messages (see the author-based override below).
            others = [m for m in members if m != self_id and not _is_bot(m)]
            name = _names(others[:1]) if others else "direct message"
            real = name
        elif ctype == "mpim":
            others = [m for m in members if m != self_id]
            if others:
                name = _names(others)   # readable: "Alice, Bob, Carol" instead of mpdm-handles
        topic = obj.get("topic", {}).get("value", "") if isinstance(obj.get("topic"), dict) else ""
        purpose = obj.get("purpose", {}).get("value", "") if isinstance(obj.get("purpose"), dict) else ""
        convs[cid] = {
            "id": cid, "type": ctype, "name": name, "real_name": real,
            "topic": topic, "purpose": purpose,
            "num_members": obj.get("num_members") or (len(obj.get("members") or []) or None),
            "is_archived": 1 if obj.get("is_archived") else 0,
            "source_dir": None, "msg_count": 0,
        }
        if name:
            channel_lookup[cid] = name
        for key in (cid, obj.get("name"), obj.get("name_normalized")):
            if key:
                dir_to_id[str(key)] = cid

    for fname, default in (
        ("channels.json", "public_channel"),
        ("groups.json", "private_channel"),
        ("mpims.json", "mpim"),
        ("dms.json", "im"),
    ):
        for obj in _load_json(export / fname):
            if isinstance(obj, dict):
                add_conv(obj, default)

    # ---- messages ----  (file_index is shared/prebuilt and covers all roots)
    counts = {"messages": 0, "files": 0, "conversations": 0, "users": len(user_rows)}
    bot_names: dict[str, str] = {}
    conv_dirs = [d for d in export.iterdir() if d.is_dir() and d.name != "attachments"]
    for cdir in sorted(conv_dirs):
        cid = dir_to_id.get(cdir.name)
        if cid is None:
            ctype = "im" if cdir.name.startswith("D") else "public_channel"
            cid = cdir.name
            convs.setdefault(cid, _placeholder_conv(cid, ctype, user_lookup))
        conv = convs[cid]
        conv["source_dir"] = cdir.name

        msg_rows: list[dict] = []
        file_rows: list[dict] = []
        for day_file in sorted(cdir.glob("*.json")):
            for msg in _load_json(day_file):
                if not isinstance(msg, dict) or not msg.get("ts"):
                    continue
                ts = str(msg["ts"])
                content = _message_content(msg)
                html_out, plain = render(content, user_lookup, channel_lookup)
                files = msg.get("files") or []
                bot_id = msg.get("bot_id")
                if bot_id and not msg.get("user"):
                    bname = msg.get("username") or (msg.get("bot_profile") or {}).get("name")
                    if bname and bot_id not in user_lookup:
                        bot_names[bot_id] = bname
                try:
                    epoch = float(ts)
                except ValueError:
                    epoch = 0.0
                thread_ts = msg.get("thread_ts")
                msg_rows.append({
                    "conv_id": cid, "ts": ts,
                    "thread_ts": str(thread_ts) if thread_ts else None,
                    "user_id": msg.get("user") or msg.get("bot_id"),
                    "type": msg.get("type") or "message",
                    "subtype": msg.get("subtype"),
                    "epoch": epoch,
                    "text_raw": content, "text_plain": plain, "html": html_out,
                    "has_files": 1 if files else 0,
                    "reply_count": int(msg.get("reply_count") or 0),
                    "edited": 1 if msg.get("edited") else 0,
                })
                for f in files:
                    if not isinstance(f, dict):
                        continue
                    fid = f.get("id") or ""
                    file_rows.append({
                        "id": fid, "conv_id": cid, "msg_ts": ts,
                        "name": f.get("name") or f.get("title") or fid,
                        "title": f.get("title") or "",
                        "mimetype": f.get("mimetype") or "",
                        "filetype": f.get("filetype") or "",
                        "size": int(f.get("size") or 0),
                        "local_path": file_index.get(fid),
                        "permalink": f.get("permalink") or "",
                    })

        # Refine DM names from who actually posted: in a 1:1 DM the only non-self
        # author is the real partner, so @-tagged third parties never leak into the name.
        if conv["type"] == "im":
            authors = sorted({m["user_id"] for m in msg_rows
                              if m["user_id"] and m["user_id"] != self_id and not _is_bot(m["user_id"])})
            if authors:
                conv["name"] = _names(authors)
                conv["real_name"] = conv["name"]

        if msg_rows:
            conn.executemany(
                """INSERT OR IGNORE INTO messages
                   (conv_id,ts,thread_ts,user_id,type,subtype,epoch,
                    text_raw,text_plain,html,has_files,reply_count,edited)
                   VALUES(:conv_id,:ts,:thread_ts,:user_id,:type,:subtype,:epoch,
                          :text_raw,:text_plain,:html,:has_files,:reply_count,:edited)""",
                msg_rows,
            )
        if file_rows:
            conn.executemany(
                """INSERT OR REPLACE INTO files
                   (id,conv_id,msg_ts,name,title,mimetype,filetype,size,local_path,permalink)
                   VALUES(:id,:conv_id,:msg_ts,:name,:title,:mimetype,:filetype,:size,:local_path,:permalink)""",
                file_rows,
            )
        conv["msg_count"] = len(msg_rows)
        counts["messages"] += len(msg_rows)
        counts["files"] += len(file_rows)
        if verbose and msg_rows:
            print(f"  + {conv['name'] or cid}: {len(msg_rows)} messages", file=sys.stderr)

    if bot_names:
        conn.executemany(
            "INSERT OR IGNORE INTO users(id,name,real_name,display_name,is_bot,deleted) "
            "VALUES(?,?,?,?,1,0)",
            [(bid, name, name, name) for bid, name in bot_names.items()],
        )

    conn.executemany(
        """INSERT OR REPLACE INTO conversations
           (id,type,name,real_name,topic,purpose,num_members,is_archived,source_dir,msg_count)
           VALUES(:id,:type,:name,:real_name,:topic,:purpose,:num_members,:is_archived,:source_dir,:msg_count)""",
        list(convs.values()),
    )
    counts["conversations"] = len(convs)
    return counts


def _placeholder_conv(cid: str, ctype: str, user_lookup: dict[str, str]) -> dict:
    name = user_lookup.get(cid, cid) if ctype == "im" else cid
    return {
        "id": cid, "type": ctype, "name": name, "real_name": "",
        "topic": "", "purpose": "", "num_members": None,
        "is_archived": 0, "source_dir": None, "msg_count": 0,
    }
