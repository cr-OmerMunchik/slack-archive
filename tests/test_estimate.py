"""The --estimate size math: attachment bytes come from file `size` metadata,
deduped by file id, and don't require downloading anything."""
import json

import pytest

from slackarchive import cli, db

_HAS_FTS = db.fts5_available(db.connect(":memory:"))
pytestmark = pytest.mark.skipif(not _HAS_FTS, reason="SQLite build lacks FTS5")


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _make_export(tmp_path):
    export = tmp_path / "export"
    archive = tmp_path / "archive"
    (export / "general").mkdir(parents=True)
    (archive / "__uploads").mkdir(parents=True)
    _w(export / "users.json", [{"id": "U1", "name": "a", "profile": {}}])
    _w(export / "channels.json", [{"id": "C1", "name": "general", "is_channel": True, "is_private": False}])
    _w(export / "groups.json", [])
    _w(export / "mpims.json", [])
    _w(export / "dms.json", [])
    return export, archive


def test_human_size():
    assert cli._human_size(0) == "0 B"
    assert cli._human_size(1024) == "1.0 KB"
    assert cli._human_size(5 * 1024 * 1024) == "5.0 MB"
    assert cli._human_size(3 * 1024 ** 3) == "3.0 GB"


def test_estimate_sums_attachment_sizes(tmp_path):
    export, archive = _make_export(tmp_path)
    _w(export / "general" / "2026-06-01.json", [
        {"type": "message", "ts": "1.0001", "user": "U1", "text": "a",
         "files": [{"id": "F1", "name": "a.bin", "size": 1000}]},
        {"type": "message", "ts": "2.0001", "user": "U1", "text": "b",
         "files": [{"id": "F2", "name": "b.bin", "size": 2000}]},
    ])
    n = cli._estimate_numbers(export, archive)
    assert n["messages"] == 2
    assert n["files"] == 2
    assert n["attachment_bytes"] == 3000
    assert n["text_bytes"] > 0          # the export JSON sitting on disk


def test_estimate_dedupes_files_by_id(tmp_path):
    # The same file shared across two messages must be counted once.
    export, archive = _make_export(tmp_path)
    shared = {"id": "F9", "name": "shared.bin", "size": 5000}
    _w(export / "general" / "2026-06-01.json", [
        {"type": "message", "ts": "1.0001", "user": "U1", "text": "x", "files": [shared]},
        {"type": "message", "ts": "2.0001", "user": "U1", "text": "y", "files": [shared]},
    ])
    n = cli._estimate_numbers(export, archive)
    assert n["files"] == 1
    assert n["attachment_bytes"] == 5000


def test_estimate_no_attachments(tmp_path):
    export, archive = _make_export(tmp_path)
    _w(export / "general" / "2026-06-01.json", [
        {"type": "message", "ts": "1.0001", "user": "U1", "text": "just text"},
    ])
    n = cli._estimate_numbers(export, archive)
    assert n["files"] == 0
    assert n["attachment_bytes"] == 0
    assert n["messages"] == 1
