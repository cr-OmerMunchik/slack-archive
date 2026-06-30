"""Attachment pruning: --max-file-size and --prune-attachments (glob patterns).
Pure filesystem logic, no FTS or network needed."""
from slackarchive import cli


def _mk(uploads, fid, name, size):
    d = uploads / fid
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(b"x" * size)


def test_prune_by_size(tmp_path):
    arch = tmp_path / "archive"
    up = arch / "__uploads"
    _mk(up, "F1", "small.png", 1000)
    _mk(up, "F2", "big.bin", 5_000_000)
    stats = cli._prune_attachments(arch, max_bytes=1_000_000, patterns=[])
    assert stats["removed"] == 1
    assert stats["bytes_freed"] == 5_000_000
    assert (up / "F1" / "small.png").exists()
    assert not (up / "F2" / "big.bin").exists()


def test_prune_by_pattern(tmp_path):
    arch = tmp_path / "archive"
    up = arch / "__uploads"
    _mk(up, "F1", "Sensor123.exe", 100)
    _mk(up, "F2", "notes.txt", 100)
    _mk(up, "F3", "data.db", 100)
    stats = cli._prune_attachments(arch, max_bytes=None, patterns=["Sensor*.exe", "*.db"])
    assert stats["removed"] == 2
    assert not (up / "F1" / "Sensor123.exe").exists()
    assert not (up / "F3" / "data.db").exists()
    assert (up / "F2" / "notes.txt").exists()


def test_prune_pattern_is_case_insensitive(tmp_path):
    arch = tmp_path / "archive"
    up = arch / "__uploads"
    _mk(up, "F1", "SENSOR_setup.EXE", 100)
    stats = cli._prune_attachments(arch, patterns=["sensor*.exe"])
    assert stats["removed"] == 1


def test_prune_no_uploads_dir(tmp_path):
    assert cli._prune_attachments(tmp_path / "archive", max_bytes=10) == {"removed": 0, "bytes_freed": 0}


def test_prune_nothing_matches(tmp_path):
    arch = tmp_path / "archive"
    _mk(arch / "__uploads", "F1", "keep.png", 100)
    stats = cli._prune_attachments(arch, max_bytes=10_000, patterns=["*.zip"])
    assert stats["removed"] == 0
    assert (arch / "__uploads" / "F1" / "keep.png").exists()


def test_load_prune_patterns(tmp_path):
    f = tmp_path / "patterns.txt"
    f.write_text("# attachments to drop\nSensor*.exe\n\n*.db   # databases\n", encoding="utf-8")
    assert cli._load_prune_patterns(f) == ["Sensor*.exe", "*.db"]


def test_load_prune_patterns_missing_file(tmp_path):
    assert cli._load_prune_patterns(tmp_path / "nope.txt") == []
