"""Pure CLI helpers (no slackdump / network involved)."""
import re

from slackarchive import cli


def test_quote_only_when_spaces():
    assert cli._quote("simple") == "simple"
    assert cli._quote("has space") == '"has space"'


def test_time_from_is_iso_utc():
    val = cli._time_from(6)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", val)


def test_default_workspace_env_wins(monkeypatch):
    monkeypatch.setenv("SLACK_ARCHIVE_WORKSPACE", "acme")
    assert cli.default_workspace() == "acme"


def test_default_workspace_is_nonempty(monkeypatch):
    monkeypatch.delenv("SLACK_ARCHIVE_WORKSPACE", raising=False)
    ws = cli.default_workspace()
    assert isinstance(ws, str) and ws  # workspace.txt or the built-in fallback


def test_conv_id_regex():
    assert cli._CONV_RE.search("processing <C01ABCDEF> now")
    assert cli._CONV_RE.search("dm <D01ABCDEF>")
    assert cli._CONV_RE.search("group <G01ABCDEF>")
    assert not cli._CONV_RE.search("a thread Thread[123] line")


def test_read_channel_tokens_strips_comments(tmp_path):
    f = tmp_path / "channels.txt"
    f.write_text(
        "# a full-line comment\n"
        "C01ABCDEF   # engineering\n"
        "\n"
        "# C01SKIPPED  commented out, must be ignored\n"
        "https://x.slack.com/archives/C0123ABCD\n",
        encoding="utf-8",
    )
    toks = cli._read_channel_tokens(f)
    assert "C01ABCDEF" in toks
    assert "https://x.slack.com/archives/C0123ABCD" in toks
    assert all("SKIPPED" not in t for t in toks)


def test_read_channel_tokens_missing_file(tmp_path):
    assert cli._read_channel_tokens(tmp_path / "nope.txt") == []
