"""Local Flask web app: search + browse the indexed Slack archive, fully offline.

Binds to localhost only. Serves downloaded attachments straight from the export
directory recorded in the database. No external requests are ever made.
"""

from __future__ import annotations

import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from flask import (
    Flask, abort, g, render_template, request, send_from_directory, url_for,
)

from . import __version__
from . import db as dbmod

PAGE_SIZE = 25
CONTEXT_BEFORE = 40   # messages loaded before an anchored search hit
CONTEXT_AFTER = 15

TYPE_BADGES = {
    "public_channel": ("#", "channel"),
    "private_channel": ("🔒", "private"),
    "mpim": ("👥", "group"),
    "im": ("@", "dm"),
}


def create_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    @app.context_processor
    def _inject_version():
        return {"version": __version__}

    # ---- per-request DB connection ----
    def get_db():
        if "db" not in g:
            g.db = dbmod.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def _close_db(_exc):
        d = g.pop("db", None)
        if d is not None:
            d.close()

    # ---- jinja helpers ----
    @app.template_filter("dt")
    def _dt(epoch: Optional[float]) -> str:
        if not epoch:
            return ""
        return datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M")

    @app.template_filter("daystamp")
    def _daystamp(epoch: Optional[float]) -> str:
        if not epoch:
            return ""
        return datetime.fromtimestamp(float(epoch)).strftime("%A, %d %B %Y")

    @app.template_filter("timestamp")
    def _timestamp(epoch: Optional[float]) -> str:
        if not epoch:
            return ""
        return datetime.fromtimestamp(float(epoch)).strftime("%H:%M")

    app.jinja_env.globals["TYPE_BADGES"] = TYPE_BADGES
    app.jinja_env.globals["type_label"] = lambda t: dbmod.CONV_TYPE_LABELS.get(t, t)

    # ---- routes ----
    @app.route("/")
    def index():
        conn = get_db()
        q = (request.args.get("q") or "").strip()
        types = request.args.getlist("type")
        conv_ids = request.args.getlist("conv")
        user_id = (request.args.get("user") or "").strip() or None
        date_from = _parse_date(request.args.get("from"), end=False)
        date_to = _parse_date(request.args.get("to"), end=True)
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1

        conversations = dbmod.list_conversations(conn)
        authors = dbmod.distinct_authors(conn)
        st = dbmod.stats(conn)

        # querystring for pagination links (everything except 'page')
        from urllib.parse import urlencode
        base_pairs = [(k, v) for k, v in request.args.items(multi=True) if k != "page"]
        base_qs = urlencode(base_pairs)

        # A search happens when there's a text query OR any filter is set (filter-only
        # listing, e.g. "everything from this person").
        filtering = bool(conv_ids or types or user_id or date_from is not None or date_to is not None)
        results: list[dict] = []
        total = 0
        if q or filtering:
            results, total = dbmod.search(
                conn, q,
                conv_ids=conv_ids or None,
                types=types or None,
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                limit=PAGE_SIZE,
                offset=(page - 1) * PAGE_SIZE,
            )
        pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        return render_template(
            "search.html",
            q=q, results=results, total=total, page=page, pages=pages, filtering=filtering,
            page_size=PAGE_SIZE, conversations=conversations, authors=authors, stats=st,
            sel_types=types, sel_convs=conv_ids, sel_user=user_id,
            date_from=request.args.get("from", ""), date_to=request.args.get("to", ""),
            base_qs=base_qs, args=request.args,
        )

    @app.route("/c/<conv_id>")
    def conversation(conv_id: str):
        conn = get_db()
        conv = dbmod.get_conversation(conn, conv_id)
        if not conv:
            abort(404)
        anchor = (request.args.get("ts") or "").strip()
        before_epoch = after_epoch = None
        anchor_epoch = None
        if anchor:
            row = conn.execute(
                "SELECT epoch FROM messages WHERE conv_id=? AND ts=?", (conv_id, anchor)
            ).fetchone()
            if row:
                anchor_epoch = row["epoch"]

        if anchor_epoch is not None:
            older = dbmod.conversation_messages(
                conn, conv_id, limit=CONTEXT_BEFORE, before_epoch=anchor_epoch + 0.000001
            )
            newer = dbmod.conversation_messages(
                conn, conv_id, limit=CONTEXT_AFTER, after_epoch=anchor_epoch
            )
            messages = older + newer
        else:
            messages = dbmod.conversation_messages(conn, conv_id, limit=300)

        # attach files to messages that have them
        _attach_files(conn, conv_id, messages)
        return render_template(
            "conversation.html",
            conv=conv, messages=messages, anchor=anchor,
            stats=dbmod.stats(conn),
        )

    @app.route("/thread/<conv_id>/<thread_ts>")
    def thread(conv_id: str, thread_ts: str):
        conn = get_db()
        conv = dbmod.get_conversation(conn, conv_id)
        if not conv:
            abort(404)
        messages = dbmod.thread_messages(conn, conv_id, thread_ts)
        _attach_files(conn, conv_id, messages)
        template = "_thread.html" if request.args.get("fragment") else "thread.html"
        return render_template(template, conv=conv, messages=messages, thread_ts=thread_ts)

    @app.route("/file/<path:relpath>")
    def serve_file(relpath: str):
        conn = get_db()
        root = dbmod.get_meta(conn, "export_root")
        if not root or not Path(root).exists():
            abort(404)
        return send_from_directory(root, relpath)

    @app.errorhandler(404)
    def _not_found(_e):
        return render_template("404.html"), 404

    return app


def _attach_files(conn, conv_id: str, messages: list[dict]) -> None:
    for m in messages:
        if m.get("has_files"):
            m["files"] = dbmod.files_for_message(conn, conv_id, m["ts"])
        else:
            m["files"] = []


def _parse_date(value: Optional[str], *, end: bool) -> Optional[float]:
    if not value:
        return None
    try:
        dt = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    if end:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.timestamp()


def run(db_path: str, *, host: str = "127.0.0.1", port: int = 8731,
        open_browser: bool = True) -> None:
    app = create_app(db_path)
    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}/"
    print(f"\n  slack-archive search is running at:  {url}")
    print("  Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)
