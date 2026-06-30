"""Storage + FTS query layer."""
import pytest

from slackarchive import db


# --- query builder (pure, no FTS needed) ------------------------------------ #
def test_to_match_query_implicit_and():
    assert db.to_match_query("hello world") == '"hello" "world"'


def test_to_match_query_prefix():
    assert db.to_match_query("plat*") == '"plat"*'


def test_to_match_query_phrase_kept_intact():
    assert db.to_match_query('"exact phrase"') == '"exact phrase"'


def test_to_match_query_empty():
    assert db.to_match_query("") == ""
    assert db.to_match_query("   ") == ""


def test_to_match_query_balances_stray_quotes():
    # A stray quote in a token must not produce an unbalanced MATCH expression.
    out = db.to_match_query('foo"bar')
    assert out.count('"') % 2 == 0


# --- search round-trip (needs FTS5) ----------------------------------------- #
@pytest.fixture
def conn():
    c = db.connect(":memory:")
    if not db.fts5_available(c):
        pytest.skip("SQLite build lacks FTS5")
    db.init_schema(c)
    c.execute("INSERT INTO conversations(id,type,name) VALUES('C1','public_channel','general')")
    return c


def _add_msg(conn, ts, text):
    conn.execute(
        "INSERT INTO messages(conv_id,ts,type,epoch,text_raw,text_plain,html) "
        "VALUES('C1',?,'message',?,?,?,?)",
        (ts, float(ts), text, text, text),
    )


def test_search_finds_message(conn):
    _add_msg(conn, "1.0", "hello sunbird release")
    conn.commit()
    db.rebuild_fts(conn)
    rows, total = db.search(conn, "sunbird")
    assert total == 1
    assert rows[0]["conv_id"] == "C1"


def test_search_snippet_is_marked(conn):
    _add_msg(conn, "1.0", "find the keyword here")
    conn.commit()
    db.rebuild_fts(conn)
    rows, total = db.search(conn, "keyword")
    assert total == 1
    assert "<mark>keyword</mark>" in rows[0]["snippet"]


def test_search_empty_query_returns_nothing(conn):
    assert db.search(conn, "") == ([], 0)


def test_search_type_filter(conn):
    _add_msg(conn, "1.0", "alpha beta")
    conn.commit()
    db.rebuild_fts(conn)
    assert db.search(conn, "alpha", types=["public_channel"])[1] == 1
    assert db.search(conn, "alpha", types=["im"])[1] == 0
