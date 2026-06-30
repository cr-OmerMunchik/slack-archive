"""Slack mrkdwn -> HTML/plain rendering. Pure functions, no DB or network."""
from slackarchive.slackfmt import render, display_name


def test_plain_text_passes_through():
    html, plain = render("hello world")
    assert html == "hello world"
    assert plain == "hello world"


def test_empty_and_none():
    assert render("") == ("", "")
    assert render(None) == ("", "")


def test_user_mention_resolved_from_lookup():
    html, plain = render("hey <@UME> there", users={"UME": "omer"})
    assert "@omer" in html
    assert "@omer" in plain
    assert 'class="mention"' in html


def test_user_mention_inline_label():
    html, _ = render("hey <@UME|omer>")
    assert "@omer" in html


def test_channel_mention():
    html, plain = render("see <#C1|general>")
    assert "#general" in html
    assert "#general" in plain


def test_link_with_label():
    html, plain = render("docs <https://example.com|the docs>")
    assert '<a href="https://example.com"' in html
    assert ">the docs</a>" in html
    assert "the docs" in plain


def test_bare_link():
    html, plain = render("<https://example.com>")
    assert 'href="https://example.com"' in html
    assert "https://example.com" in plain


def test_bold_italic_strike():
    html, plain = render("*b* _i_ ~s~")
    assert "<strong>b</strong>" in html
    assert "<em>i</em>" in html
    assert "<del>s</del>" in html
    # the plain (indexed) form drops * and ~ emphasis markers
    assert "*" not in plain
    assert "~" not in plain


def test_inline_code_is_not_reformatted():
    html, plain = render("use `*not bold*`")
    assert "<code>*not bold*</code>" in html  # asterisks inside code stay literal
    assert "not bold" in plain


def test_code_block():
    html, _ = render("```\nline1\nline2\n```")
    assert "<pre" in html
    assert "line1" in html


def test_html_injection_is_escaped():
    # Slack stores < > as &lt; &gt;; rendering must never emit a live tag.
    html, _ = render("a &lt;script&gt; tag")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_display_name_preference_order():
    assert display_name({"display_name": "om", "real_name": "Omer M"}) == "om"
    assert display_name({"real_name": "Omer M"}) == "Omer M"
    assert display_name({"name": "omer"}) == "omer"
    assert display_name({}) == "unknown"
    assert display_name(None) == "unknown"
