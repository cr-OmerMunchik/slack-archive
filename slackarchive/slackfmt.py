"""Render Slack ``mrkdwn`` into safe display HTML and a searchable plain-text form.

Slack stores message text with ``&`` ``<`` ``>`` escaped as ``&amp; &lt; &gt;``
and uses *real* angle brackets only for entities like ``<@U123>``, ``<#C1|name>``,
``<http://x|label>``. We therefore:

1. pull out code spans/blocks (so their contents are never reformatted),
2. resolve ``<...>`` entities to mentions / channel refs / links,
3. unescape the remaining Slack entities, then escape for HTML and apply
   ``*bold* _italic_ ~strike~`` + blockquotes + line breaks.

``render()`` returns ``(html, plain)``. ``plain`` is what gets indexed by FTS5,
so a search for a colleague's display name or a link's label will match.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Callable, Mapping

# A private-use sentinel that won't appear in real text, used for placeholders.
_SENT = "\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")

_ENTITY_RE = re.compile(r"<([^<>]+)>")
_CODEBLOCK_RE = re.compile(r"```(.*?)```", re.DOTALL)
_INLINECODE_RE = re.compile(r"`([^`\n]+)`")

_BOLD_RE = re.compile(r"\*([^*\n]+)\*")
_ITALIC_RE = re.compile(r"(?<![\w/])_([^_\n]+)_(?![\w/])")
_STRIKE_RE = re.compile(r"~([^~\n]+)~")

NameLookup = Mapping[str, str]

# Slack emoji shortcodes (:smile:) -> Unicode, via a bundled map (no runtime dependency).
_SHORTCODE_RE = re.compile(r":([A-Za-z0-9_+\-]+):")
_EMOJI_MAP: dict | None = None


def _emoji_map() -> dict:
    global _EMOJI_MAP
    if _EMOJI_MAP is None:
        try:
            _EMOJI_MAP = json.loads(
                Path(__file__).with_name("emoji_shortcodes.json").read_text(encoding="utf-8")
            )
        except Exception:
            _EMOJI_MAP = {}
    return _EMOJI_MAP


def _emojize(text: str) -> str:
    """Replace :shortcodes: with Unicode emoji; unknown codes are left as-is."""
    if ":" not in text:
        return text
    m = _emoji_map()
    if not m:
        return text
    return _SHORTCODE_RE.sub(
        lambda mt: m.get(mt.group(1)) or m.get(mt.group(1).lower()) or mt.group(0), text
    )


def _slack_unescape(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def render(
    text: str | None,
    users: NameLookup | None = None,
    channels: NameLookup | None = None,
) -> tuple[str, str]:
    """Return ``(html, plain)`` for a Slack message's raw text."""
    if not text:
        return "", ""
    users = users or {}
    channels = channels or {}

    html_parts: list[str] = []   # final HTML for each placeholder
    plain_parts: list[str] = []  # plain text for each placeholder

    def stash(html_frag: str, plain_frag: str) -> str:
        idx = len(html_parts)
        html_parts.append(html_frag)
        plain_parts.append(plain_frag)
        return f"{_SENT}{idx}{_SENT}"

    # 1) Code blocks and inline code -> placeholders (contents escaped, never reformatted).
    def _codeblock(m: re.Match) -> str:
        inner = _slack_unescape(m.group(1)).strip("\n")
        return stash(f"<pre class=\"code\"><code>{html.escape(inner)}</code></pre>",
                     inner)

    def _inlinecode(m: re.Match) -> str:
        inner = _slack_unescape(m.group(1))
        return stash(f"<code>{html.escape(inner)}</code>", inner)

    text = _CODEBLOCK_RE.sub(_codeblock, text)
    text = _INLINECODE_RE.sub(_inlinecode, text)

    # 2) <...> entities -> placeholders.
    def _entity(m: re.Match) -> str:
        body = m.group(1)
        # link with optional |label
        if body.startswith(("http://", "https://", "mailto:")):
            url, _, label = body.partition("|")
            label = label or url
            url = _slack_unescape(url)
            label_plain = _slack_unescape(label)
            safe_url = html.escape(url, quote=True)
            return stash(
                f'<a href="{safe_url}" target="_blank" rel="noopener">{html.escape(label_plain)}</a>',
                label_plain,
            )
        if body.startswith("@"):  # <@U123> or <@U123|name>
            uid, _, label = body[1:].partition("|")
            name = label or users.get(uid, uid)
            disp = f"@{name}"
            return stash(f'<span class="mention">{html.escape(disp)}</span>', disp)
        if body.startswith("#"):  # <#C123|name> or <#C123>
            cid, _, label = body[1:].partition("|")
            name = label or channels.get(cid, cid)
            disp = f"#{name}"
            return stash(f'<span class="mention">{html.escape(disp)}</span>', disp)
        if body.startswith("!subteam^"):
            _, _, label = body.partition("|")
            disp = label or "@group"
            return stash(f'<span class="mention">{html.escape(disp)}</span>', disp)
        if body.startswith("!date^"):
            # <!date^TS^fmt|fallback>
            _, _, fallback = body.partition("|")
            disp = fallback or body
            return stash(html.escape(disp), disp)
        if body.startswith("!"):  # <!here> <!channel> <!everyone>
            kw, _, label = body[1:].partition("|")
            disp = f"@{label or kw}"
            return stash(f'<span class="mention">{html.escape(disp)}</span>', disp)
        # Unknown entity: show its label or raw body.
        _, _, label = body.partition("|")
        disp = _slack_unescape(label or body)
        return stash(html.escape(disp), disp)

    text = _ENTITY_RE.sub(_entity, text)

    # 3) leftover text: unescape Slack entities so we have real unicode.
    text = _slack_unescape(text)
    text = _emojize(text)   # :smile: -> 😄  (bundled shortcode map; no runtime dependency)

    plain = _restore(text, plain_parts, plain=True)
    html_out = _to_html(text, html_parts)
    return html_out, plain


def _to_html(text: str, html_parts: list[str]) -> str:
    lines = text.split("\n")
    out_lines: list[str] = []
    in_quote = False
    for line in lines:
        is_quote = line.startswith("> ") or line == ">"
        content = line[2:] if line.startswith("> ") else (line[1:] if line == ">" else line)
        rendered = _format_inline(content, html_parts)
        if is_quote and not in_quote:
            out_lines.append("<blockquote>" + rendered)
            in_quote = True
        elif is_quote and in_quote:
            out_lines.append("<br>" + rendered)
        elif not is_quote and in_quote:
            out_lines.append("</blockquote>" + rendered)
            in_quote = False
        else:
            out_lines.append(rendered)
    if in_quote:
        out_lines.append("</blockquote>")
    # Join with <br>, but don't add <br> right after a blockquote open/close boundary.
    html_str = "<br>".join(out_lines)
    html_str = html_str.replace("<blockquote><br>", "<blockquote>")
    html_str = html_str.replace("<br></blockquote>", "</blockquote>")
    html_str = html_str.replace("</blockquote><br>", "</blockquote>")
    return html_str


def _format_inline(segment: str, html_parts: list[str]) -> str:
    # Escape literal HTML, then apply emphasis (placeholders contain \x00 digits,
    # which escape() leaves untouched), then restore placeholders.
    esc = html.escape(segment)
    esc = _BOLD_RE.sub(r"<strong>\1</strong>", esc)
    esc = _ITALIC_RE.sub(r"<em>\1</em>", esc)
    esc = _STRIKE_RE.sub(r"<del>\1</del>", esc)
    return _restore(esc, html_parts, plain=False)


def _restore(text: str, parts: list[str], *, plain: bool) -> str:
    def repl(m: re.Match) -> str:
        return parts[int(m.group(1))]
    out = _PLACEHOLDER_RE.sub(repl, text)
    if plain:
        # collapse emphasis markers for the search/plain form
        out = out.replace("*", "").replace("~", "")
    return out


def display_name(user_row: Mapping | None) -> str:
    """Pick the best human label for a user row (dict-like)."""
    if not user_row:
        return "unknown"
    for key in ("display_name", "real_name", "user_name", "name"):
        val = user_row.get(key) if hasattr(user_row, "get") else None
        if val:
            return val
    return "unknown"
