"""End-to-end ingest: a synthetic Slack export -> SQLite index.

Covers the behaviours that were the trickiest to get right: DM naming from the
non-self participant, bot/app messages whose content lives in attachments, both
attachment on-disk layouts, mention rendering, and FTS searchability.
"""
import json

import pytest

from slackarchive import db, ingest

_HAS_FTS = db.fts5_available(db.connect(":memory:"))
pytestmark = pytest.mark.skipif(not _HAS_FTS, reason="SQLite build lacks FTS5")


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def indexed(tmp_path):
    export = tmp_path / "export"
    archive = tmp_path / "archive"
    (export / "general" / "attachments").mkdir(parents=True)
    (export / "D1").mkdir(parents=True)
    (export / "D2").mkdir(parents=True)
    (archive / "__uploads" / "F100").mkdir(parents=True)

    _w(export / "users.json", [
        {"id": "UME", "name": "omer", "real_name": "Omer M", "profile": {"display_name": "omer"}},
        {"id": "UAL", "name": "alice", "real_name": "Alice Smith", "profile": {"display_name": "alice"}},
        {"id": "UBOB", "name": "bob", "real_name": "Bob Jones", "profile": {"display_name": ""}},
    ])
    _w(export / "channels.json", [{"id": "C1", "name": "general", "is_channel": True, "is_private": False}])
    _w(export / "groups.json", [])
    _w(export / "mpims.json", [])
    # UME is in every DM -> detected as "self"; DMs are named after the other person.
    _w(export / "dms.json", [
        {"id": "D1", "members": ["UME", "UAL"]},
        {"id": "D2", "members": ["UME", "UBOB"]},
    ])
    _w(export / "D1" / "2026-06-01.json",
       [{"type": "message", "ts": "1716000000.000100", "user": "UAL", "text": "hey omer"}])
    _w(export / "D2" / "2026-06-01.json",
       [{"type": "message", "ts": "1716000001.000100", "user": "UBOB", "text": "yo"}])
    _w(export / "general" / "2026-06-01.json", [
        {"type": "message", "ts": "1716000100.000100", "user": "UAL",
         "text": "hello <@UME> check this",
         "files": [{"id": "F200", "name": "doc.pdf", "mimetype": "application/pdf"}]},
        {"type": "message", "ts": "1716000101.000100", "user": "UME", "text": "pic",
         "files": [{"id": "F100", "name": "pic.png", "mimetype": "image/png"}]},
        # bot/app message: text is empty, content is in attachments.
        {"type": "message", "subtype": "bot_message", "bot_id": "B1", "ts": "1716000102.000100",
         "attachments": [{"color": "#f00", "fallback": "Build FAILURE",
                          "fields": [{"title": "", "value": "*Sunbird build* <http://ci/42|#42> FAILURE",
                                      "short": False}]}]},
    ])
    (archive / "__uploads" / "F100" / "pic.png").write_bytes(b"img")          # __uploads/F<id>/name
    (export / "general" / "attachments" / "F200-doc.pdf").write_bytes(b"pdf")  # F<id>-name

    dbpath = tmp_path / "search.db"
    res = ingest.index_paths([str(export)], str(dbpath),
                             attachment_roots=[str(archive)], verbose=False)
    return res, db.connect(dbpath)


def test_message_count(indexed):
    res, _ = indexed
    assert res["messages"] == 5


def test_dm_named_after_other_participant(indexed):
    _, conn = indexed
    d1 = conn.execute("SELECT name FROM conversations WHERE id='D1'").fetchone()["name"]
    d2 = conn.execute("SELECT name FROM conversations WHERE id='D2'").fetchone()["name"]
    assert d1 in ("alice", "Alice Smith")
    assert "bob" in (d2 or "").lower()


def test_attachments_resolved_in_both_layouts(indexed):
    _, conn = indexed
    f100 = conn.execute("SELECT local_path FROM files WHERE id='F100'").fetchone()["local_path"]
    f200 = conn.execute("SELECT local_path FROM files WHERE id='F200'").fetchone()["local_path"]
    assert f100 and f100.endswith("pic.png") and "F100" in f100
    assert f200 and f200.endswith("doc.pdf") and "F200" in f200


def test_bot_message_content_rendered_and_indexed(indexed):
    _, conn = indexed
    bot = conn.execute(
        "SELECT html, text_plain FROM messages WHERE subtype='bot_message'").fetchone()
    assert bot is not None
    assert "FAILURE" in bot["html"]      # field value rendered, not blank
    assert "<a " in bot["html"]          # the <http://ci/42|#42> link became a real link
    assert "Sunbird" in (bot["text_plain"] or "")   # searchable


def test_mention_rendered_as_handle(indexed):
    _, conn = indexed
    row = conn.execute("SELECT html FROM messages WHERE text_raw LIKE 'hello%'").fetchone()
    assert "@omer" in row["html"]


def test_full_text_search(indexed):
    _, conn = indexed
    assert db.search(conn, "Sunbird")[1] >= 1
    assert db.search(conn, "hey")[1] >= 1
