"""Command-line entry point: ``python -m slackarchive <backup|index|serve|list-channels>``."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DEFAULT_EXPORT = DATA_DIR / "export"
DEFAULT_DB = DATA_DIR / "search.db"
CHANNELS_FILE = REPO_ROOT / "channels.txt"
WORKSPACE_FILE = REPO_ROOT / "workspace.txt"


def default_workspace() -> str | None:
    """Default Slack workspace for login, resolved in order:
    1. the SLACK_ARCHIVE_WORKSPACE environment variable,
    2. a local ``workspace.txt`` file (first non-comment line),
    3. a built-in fallback ('cybereason').
    Override any time with ``--workspace``. Non-Cybereason users can set the env
    var, drop a workspace.txt, or change the fallback below."""
    env = os.environ.get("SLACK_ARCHIVE_WORKSPACE")
    if env and env.strip():
        return env.strip()
    if WORKSPACE_FILE.exists():
        for line in WORKSPACE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                return line
    return "cybereason"


# --------------------------------------------------------------------------- #
# slackdump helpers
# --------------------------------------------------------------------------- #
def find_slackdump() -> str | None:
    name = "slackdump.exe" if os.name == "nt" else "slackdump"
    local = REPO_ROOT / "bin" / name
    if local.exists():
        return str(local)
    return shutil.which("slackdump")


def _read_channel_tokens(path: Path) -> list[str]:
    """Read selected channel IDs/URLs, ignoring blank lines and # comments
    (both full-line and trailing inline comments)."""
    tokens: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()   # drop inline/full-line comments
            if not line:
                continue
            tokens.extend(line.split())
    return tokens


def _logged_in(sd: str, workspace: str | None) -> bool:
    try:
        out = subprocess.run([sd, "workspace", "list"], capture_output=True, text=True, timeout=30)
    except Exception:
        return False
    text = (out.stdout or "") + (out.stderr or "")
    if workspace:
        return workspace.lower() in text.lower()
    # any non-empty, non-error listing means at least one workspace
    return out.returncode == 0 and bool(text.strip()) and "no workspaces" not in text.lower()


def _ensure_login(sd: str, workspace: str | None, skip: bool) -> bool:
    if skip or _logged_in(sd, workspace):
        return True
    ws = workspace or ""
    print(f"Not logged in yet - launching slackdump login{(' for ' + ws) if ws else ''}...")
    rc = subprocess.run([sd, "workspace", "new"] + ([ws] if ws else [])).returncode
    return rc == 0


def _list_channels_json(sd: str, enterprise: bool, member_only: bool) -> list | None:
    cmd = [sd, "list", "channels", "-format", "JSON", "-no-json"]
    if member_only:
        cmd.append("-member-only")
    if enterprise:
        cmd.append("-enterprise")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        sys.stderr.write(res.stderr or "")
        return None
    out = (res.stdout or "").strip()
    start = out.find("[")
    try:
        data = json.loads(out[start:]) if start >= 0 else []
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else data.get("channels", [])


DIR_CACHE = DATA_DIR / ".channel_dir_cache.json"
DIR_CACHE_MAX_AGE = 24 * 3600   # seconds


def _public_channel_directory(sd: str, enterprise: bool) -> list[tuple[str, str]] | None:
    """Return [(name, id), ...] for every public channel, cached on disk so the
    (potentially huge, slow) directory fetch only happens once a day."""
    try:
        if DIR_CACHE.exists() and (time.time() - DIR_CACHE.stat().st_mtime) < DIR_CACHE_MAX_AGE:
            data = json.loads(DIR_CACHE.read_text(encoding="utf-8"))
            return [(d["name"], d["id"]) for d in data]
    except Exception:
        pass
    print("Loading the public-channel directory (one-time; can take a minute on large workspaces)...")
    allch = _list_channels_json(sd, enterprise, member_only=False)
    if allch is None:
        return None
    pub = [{"name": c.get("name"), "id": c.get("id")} for c in allch
           if isinstance(c, dict) and c.get("id") and c.get("name")
           and not c.get("is_im") and not c.get("is_mpim") and not c.get("is_private")]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DIR_CACHE.write_text(json.dumps(pub), encoding="utf-8")
    except Exception:
        pass
    return [(d["name"], d["id"]) for d in pub]


PICKED_FILE = DATA_DIR / ".picked_public.json"


def _load_picked() -> dict[str, str]:
    """Public channels chosen in a previous run (id -> name), so the picker remembers."""
    try:
        if PICKED_FILE.exists():
            return {d["id"]: d["name"] for d in json.loads(PICKED_FILE.read_text(encoding="utf-8"))}
    except Exception:
        pass
    return {}


def _save_picked(selected: dict[str, str]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PICKED_FILE.write_text(json.dumps([{"id": i, "name": n} for i, n in selected.items()]),
                               encoding="utf-8")
    except Exception:
        pass


def _interactive_select(sd: str, enterprise: bool) -> list[str] | None:
    """Search-driven terminal picker. Your DMs and group chats are always included.
    Every *named* channel you belong to is pre-selected, and you can search across both
    your channels and the full public directory by name - matches show ticked when
    they're already included, so you can confirm/untick yours and add new public ones.
    Remembers added public channels between runs. Returns channel IDs, or None to cancel."""
    try:
        import questionary
    except ImportError:
        print("error: 'questionary' is not installed. Re-run setup (or: pip install questionary).",
              file=sys.stderr)
        return None

    print("Loading your conversations...")
    mine = _list_channels_json(sd, enterprise, member_only=True)
    if mine is None:
        print("error: could not list your conversations (logged in? on Grid pass --enterprise).",
              file=sys.stderr)
        return None

    auto_ids: list[str] = []          # DMs + group DMs: always backed up, not shown
    your_named: list[tuple[str, str]] = []   # (name, id) channels you belong to (public + private)
    member_ids: set[str] = set()
    for c in mine:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        cid = c["id"]
        member_ids.add(cid)
        if c.get("is_im") or c.get("is_mpim"):
            auto_ids.append(cid)
        else:
            your_named.append((c.get("name") or cid, cid))
    your_named.sort(key=lambda x: x[0].lower())
    your_named_ids = {i for (_n, i) in your_named}

    directory = _public_channel_directory(sd, enterprise) or []
    directory = [(n, i) for (n, i) in directory if i not in member_ids]

    # Searchable pool = your channels + every other public channel.
    pool = your_named + directory
    pool_by_id = {i: n for (n, i) in pool}

    # Pre-select all your channels; restore remembered extra public picks.
    selected: dict[str, str] = {i: n for (n, i) in your_named}
    for i, n in _load_picked().items():
        if i in pool_by_id and i not in your_named_ids:
            selected[i] = pool_by_id[i]

    def show_selected() -> None:
        names = sorted(selected.values(), key=str.lower)
        if names:
            head = ", ".join("#" + x for x in names[:14])
            more = "" if len(names) <= 14 else f"  (+{len(names) - 14} more)"
            print(f"\n✓ Channels to back up ({len(names)}): {head}{more}")
        else:
            print("\n(no channels selected)")

    include_files = True
    try:
        print(f"\nYou belong to {len(your_named)} channel(s) — all pre-selected. "
              f"{len(directory):,} more public channels are available.")
        print("Search by name to add public channels, or to find one of yours and untick it.")
        while True:
            # ---- search & toggle phase ----
            while True:
                show_selected()
                kw = questionary.text("Search channels to add/remove (blank to review & finish):").ask()
                if kw is None:
                    print("Cancelled.")
                    return None
                kw = kw.strip().lower()
                if not kw:
                    break
                matches = sorted((m for m in pool if kw in m[0].lower()), key=lambda m: m[0].lower())
                if not matches:
                    print(f"  no channels match '{kw}'.")
                    continue
                if len(matches) > 100:
                    print(f"  {len(matches)} matches — showing the first 100; refine to narrow.")
                    matches = matches[:100]
                choices = [questionary.Choice(title=f"#{n}", value=i, checked=(i in selected))
                           for (n, i) in matches]
                label = "Space = toggle (ticked = included), Enter = apply:"
                try:
                    picks = questionary.checkbox(label, choices=choices,
                                                 use_search_filter=True, use_jk_keys=False).ask()
                except TypeError:
                    picks = questionary.checkbox(label, choices=choices).ask()
                if picks is None:    # skip this batch, keep current selection
                    continue
                pickset, names = set(picks), {i: n for (n, i) in matches}
                for (_n, i) in matches:   # add/remove only what was shown
                    if i in pickset:
                        selected[i] = names[i]
                    else:
                        selected.pop(i, None)

            # ---- review & confirm phase ----
            inc = questionary.confirm(
                "Also back up file attachments (images, files)? They can be large.",
                default=include_files,
            ).ask()
            if inc is None:
                print("Cancelled.")
                return None
            include_files = bool(inc)

            print("\n=== This backup will include ===")
            print(f"  - all {len(auto_ids)} of your DMs and group chats")
            if selected:
                print(f"  - {len(selected)} channel(s):")
                for n in sorted(selected.values(), key=str.lower):
                    print(f"      #{n}")
            else:
                print("  - no channels")
            print(f"  - attachments: {'yes' if include_files else 'no (text only)'}")
            action = questionary.select(
                "Proceed?",
                choices=["Yes - back up this selection", "No - keep choosing", "Cancel"],
            ).ask()
            if action is None or action.startswith("Cancel"):
                print("Cancelled.")
                return None
            if action.startswith("Yes"):
                break
            # "No - keep choosing" -> outer loop repeats the search phase
    except Exception as exc:
        print(f"error: the interactive picker needs a real terminal ({exc}).", file=sys.stderr)
        return None

    _save_picked({i: n for i, n in selected.items() if i not in your_named_ids})
    return auto_ids + list(selected.keys()), include_files


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_backup(args: argparse.Namespace) -> int:
    sd = find_slackdump()
    if not sd:
        print("error: slackdump not found. Run the setup script (setup.ps1 / setup.sh) first.",
              file=sys.stderr)
        return 2

    archive_dir = DATA_DIR / "archive"          # resumable SQLite archive + attachments
    export_dir = Path(args.out)                 # files-free export the indexer reads
    resuming = (archive_dir / "slackdump.sqlite").exists() and not args.fresh

    include_files = not args.no_files
    channels: list[str] = []

    if resuming:
        print(f"Found an existing archive at {archive_dir} — resuming it (incremental update).")
        print("The channel set comes from the archive; use --fresh to choose a new set.\n")
    else:
        if args.fresh and archive_dir.exists():
            shutil.rmtree(archive_dir, ignore_errors=True)
        if args.pick:
            if not _ensure_login(sd, args.workspace, args.skip_login):
                print("error: login did not complete.", file=sys.stderr)
                return 1
            sel = _interactive_select(sd, args.enterprise)
            if not sel:
                print("Selection cancelled; nothing backed up.", file=sys.stderr)
                return 1
            channels, include_files = sel
        else:
            channels = list(args.channels or [])
            if not args.no_channels_file:
                channels += _read_channel_tokens(Path(args.channels_file))

    files_flag = "-files" if include_files else "-files=false"
    common: list[str] = []
    if args.enterprise:
        common.append("-enterprise")
    if args.workspace:
        common += ["-workspace", args.workspace]

    if resuming:
        # resumable + incremental; skip threads we already have in full to cut rate-limit hits
        capture = [sd, "resume", str(archive_dir), "-threads", "-skip-complete-threads", files_flag] + common
    else:
        archive_dir.mkdir(parents=True, exist_ok=True)
        capture = [sd, "archive", "-o", str(archive_dir), files_flag] + common
        capture += channels if channels else ["-member-only"]
    if args.yes:
        capture.append("-y")

    # Convert the archive to an export WITHOUT copying files (-files=false): attachments
    # live only in the archive, so we never store gigabytes twice. The indexer reads the
    # text from here and resolves attachments straight from the archive.
    convert = [sd, "convert", "-f", "export", "-files=false", "-o", str(export_dir), str(archive_dir)]

    print("\nStep 1/2 - capture (slackdump):\n  " + " ".join(_quote(c) for c in capture))
    print("Step 2/2 - convert to a searchable export:\n  " + " ".join(_quote(c) for c in convert) + "\n")
    if args.dry_run:
        print("(dry run - not executed)")
        return 0

    if not _ensure_login(sd, args.workspace, args.skip_login):
        print("error: login did not complete.", file=sys.stderr)
        return 1

    _print_capture_banner(resuming)
    rc, elapsed = _run_capture(capture, "Resume" if resuming else "Archive")
    if rc != 0:
        print(f"\nslackdump exited with code {rc} after {_fmt_dur(elapsed)}. "
              "Re-run backup to resume where it stopped.", file=sys.stderr)
        return rc
    print(f"\n✓ Capture finished in {_fmt_dur(elapsed)}.")

    print("Converting the archive into a searchable export ...")
    if export_dir.exists():
        shutil.rmtree(export_dir, ignore_errors=True)
    rc = subprocess.run(convert).returncode
    if rc != 0:
        print(f"\nconvert failed (code {rc}).", file=sys.stderr)
        return rc
    print("\nDone. Next:\n  python -m slackarchive index\n  python -m slackarchive serve")
    return 0


def _conv_label(c: dict) -> tuple[str, str]:
    """Return (type_label, name) for a channel object from `list channels` JSON."""
    if c.get("is_im"):
        return "DM", (c.get("name") or c.get("user") or c.get("id"))
    if c.get("is_mpim"):
        return "Group DM", (c.get("name") or c.get("id"))
    if c.get("is_private") or c.get("is_group"):
        return "Private", (c.get("name") or c.get("id"))
    return "Channel", (c.get("name") or c.get("id"))


_TYPE_ORDER = {"Channel": 0, "Private": 1, "Group DM": 2, "DM": 3}


def cmd_pick_channels(args: argparse.Namespace) -> int:
    """Write an editable channels.txt listing the conversations you're in, all
    pre-selected. Comment out (#) any to skip; paste extra public-channel links."""
    sd = find_slackdump()
    if not sd:
        print("error: slackdump not found. Run setup first.", file=sys.stderr)
        return 2

    cmd = [sd, "list", "channels", "-member-only", "-format", "JSON", "-no-json"]
    if args.enterprise:
        cmd.append("-enterprise")
    print("Fetching your conversation list from Slack (this can take a moment)...")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        sys.stderr.write(res.stderr or "")
        print("\nerror: could not list channels (are you logged in? on Grid, pass --enterprise).",
              file=sys.stderr)
        return res.returncode or 1

    out = (res.stdout or "").strip()
    start = out.find("[")
    try:
        data = json.loads(out[start:]) if start >= 0 else []
    except json.JSONDecodeError:
        print("error: could not parse the channel list from slackdump.", file=sys.stderr)
        return 1
    channels = data if isinstance(data, list) else data.get("channels", [])

    rows = []
    for c in channels:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        tlabel, name = _conv_label(c)
        rows.append((_TYPE_ORDER.get(tlabel, 9), tlabel, c["id"], name or c["id"]))
    rows.sort(key=lambda r: (r[0], str(r[3]).lower()))

    target = Path(args.out)
    if target.exists():
        bak = target.with_suffix(target.suffix + ".bak")
        bak.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")

    lines = [
        "# channels.txt - what `backup` will export.",
        "# Every conversation you're in is listed below and SELECTED.",
        "#   * Comment out a line (add # at the start) to SKIP that conversation.",
        "#   * Add extra PUBLIC channels you're not in by pasting their links at the bottom",
        "#     (in Slack: right-click the channel -> Copy link).",
        "# Lines starting with # are ignored. Re-run `pick-channels` to refresh this list",
        "# (your previous file is saved as channels.txt.bak).",
        "",
    ]
    last = None
    for order, tlabel, cid, name in rows:
        if tlabel != last:
            lines.append(f"\n# ---- {tlabel} ----")
            last = tlabel
        lines.append(f"{cid}    # {name}")
    lines += [
        "",
        "# ---- Extra public channels (not auto-listed) ----",
        "# https://yourworkspace.slack.com/archives/C0123ABCD",
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")

    by_type: dict[str, int] = {}
    for _, tlabel, _, _ in rows:
        by_type[tlabel] = by_type.get(tlabel, 0) + 1
    summary = ", ".join(f"{n} {t.lower()}{'s' if n != 1 else ''}" for t, n in by_type.items())
    print(f"\nWrote {len(rows)} conversations to {target}")
    if summary:
        print(f"  ({summary})")
    print("\nNext:\n  1) (optional) open channels.txt and comment out anything you don't want,\n"
          "     or paste extra public-channel links at the bottom\n"
          "  2) run the backup:   python -m slackarchive backup" +
          ("  --enterprise" if args.enterprise else ""))
    return 0


def cmd_list_channels(args: argparse.Namespace) -> int:
    sd = find_slackdump()
    if not sd:
        print("error: slackdump not found. Run setup first.", file=sys.stderr)
        return 2
    cmd = [sd, "list", "channels"]
    if args.enterprise:
        cmd.append("-enterprise")
    if args.member_only:
        cmd.append("-member-only")
    cmd += ["-format", "text", "-no-json"]
    return subprocess.run(cmd).returncode


def cmd_find_channels(args: argparse.Namespace) -> int:
    """Search ALL channels you can see (incl. public ones you're not in) by name,
    so you can copy the IDs into channels.txt and back them up."""
    sd = find_slackdump()
    if not sd:
        print("error: slackdump not found. Run setup first.", file=sys.stderr)
        return 2
    cmd = [sd, "list", "channels", "-format", "JSON", "-no-json"]  # NOT member-only
    if args.enterprise:
        cmd.append("-enterprise")
    print("Fetching the channel list from Slack (can be slow on large workspaces)...")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        sys.stderr.write(res.stderr or "")
        print("\nerror: could not list channels (logged in? on Grid, pass --enterprise).", file=sys.stderr)
        return res.returncode or 1
    out = (res.stdout or "").strip()
    start = out.find("[")
    try:
        data = json.loads(out[start:]) if start >= 0 else []
    except json.JSONDecodeError:
        print("error: could not parse the channel list.", file=sys.stderr)
        return 1
    channels = data if isinstance(data, list) else data.get("channels", [])

    q = args.query.lower()
    matches = []
    for c in channels:
        if not isinstance(c, dict) or c.get("is_im") or c.get("is_mpim"):
            continue
        name = c.get("name") or c.get("name_normalized") or ""
        if q in name.lower():
            kind = "private" if c.get("is_private") else "public"
            member = "  [already a member]" if c.get("is_member") else ""
            matches.append((name, c.get("id"), kind, member))
    matches.sort(key=lambda m: m[0].lower())

    if not matches:
        print(f"\nNo channels matching '{args.query}'.")
        return 0
    print(f"\n{len(matches)} channel(s) matching '{args.query}':\n")
    for name, cid, kind, member in matches:
        print(f"  {cid}   #{name}   ({kind}){member}")
    print("\nTo include any of these, add its ID (or channel link) to channels.txt, then:")
    print("  python -m slackarchive backup" + ("  --enterprise" if args.enterprise else ""))
    print("  python -m slackarchive index")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from . import ingest
    if args.export:
        dirs = [Path(d) for d in args.export]
    else:
        dirs = _discover_exports()
        if not dirs:
            print(f"error: no exports found under {DATA_DIR}. Run the backup first, or pass --export.",
                  file=sys.stderr)
            return 2
    missing = [str(d) for d in dirs if not d.exists()]
    if missing:
        print("error: export directory not found: " + ", ".join(missing), file=sys.stderr)
        return 2

    # Attachments may live only in the resumable archive (we convert files-free to save
    # disk), so point the indexer at it too for attachment resolution.
    archive_dir = DATA_DIR / "archive"
    attachment_roots = [str(archive_dir)] if archive_dir.exists() else []

    print("Indexing:\n  " + "\n  ".join(str(d) for d in dirs) + f"\n-> {args.db}\n")
    result = ingest.index_paths([str(d) for d in dirs], args.db,
                                attachment_roots=attachment_roots, verbose=not args.quiet)
    print(f"\nDone: {result['messages']} messages, {result['files']} files, "
          f"{result['conversations']} conversations, {result['users']} users.")
    print(f"Database: {args.db}")
    print("Next:  python -m slackarchive serve")
    return 0


def _discover_exports() -> list[Path]:
    """Any directory under data/ that looks like an export (has users.json)."""
    found: list[Path] = []
    if DATA_DIR.exists():
        if (DATA_DIR / "users.json").exists():
            found.append(DATA_DIR)
        for d in sorted(DATA_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and (d / "users.json").exists():
                found.append(d)
    return found


def cmd_serve(args: argparse.Namespace) -> int:
    db = Path(args.db)
    if not db.exists():
        print(f"error: database '{db}' not found. Run 'python -m slackarchive index' first.",
              file=sys.stderr)
        return 2
    from . import server
    server.run(str(db), host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def _quote(s: str) -> str:
    return f'"{s}"' if " " in s else s


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _print_capture_banner(resuming: bool) -> None:
    bar = "-" * 68
    print("\n" + bar)
    print(("Resuming" if resuming else "Capturing") + " your Slack history into the archive.")
    print("  - Progress = the message / 'stream result' lines slackdump prints below.")
    print("  - Pauses such as 'rate limited, sleeping' are NORMAL: Slack throttles thread")
    print("    history; slackdump waits the requested seconds and continues on its own.")
    print("  - No exact ETA (Slack sets the pace). Rough guide: small histories take a few")
    print("    minutes; large multi-year ones can take 30 min to several hours the FIRST time.")
    print("  - RESUMABLE: press Ctrl+C anytime, then re-run backup to continue where it stopped.")
    print(bar + "\n")


def _run_capture(cmd: list[str], what: str) -> tuple[int, float]:
    """Run the (long) slackdump capture with native output, plus a periodic elapsed-time
    heartbeat so it's obvious the run is still alive during rate-limit pauses."""
    start = time.time()
    stop = threading.Event()

    def _heartbeat() -> None:
        # first tick after 60s, then every 60s, until the process finishes
        while not stop.wait(60):
            print(f"\n   ⏳ {what} still running — {_fmt_dur(time.time() - start)} elapsed. "
                  "Throttle pauses are normal; Ctrl+C is safe (it resumes).\n", flush=True)

    beat = threading.Thread(target=_heartbeat, daemon=True)
    beat.start()
    try:
        rc = subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        rc = 130
    finally:
        stop.set()
    return rc, time.time() - start


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="slackarchive",
        description="Back up your Slack history with slackdump and search it locally in your browser.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pb = sub.add_parser("backup", help="export your Slack history via slackdump")
    pb.add_argument("--workspace", default=default_workspace(),
                    help="Slack workspace subdomain. Default: SLACK_ARCHIVE_WORKSPACE env var, "
                         "then workspace.txt, then 'cybereason'. e.g. acme")
    pb.add_argument("--out", default=str(DEFAULT_EXPORT), help="output export directory")
    pb.add_argument("--pick", action="store_true", help="interactively choose public channels to include (terminal checkbox)")
    pb.add_argument("--channels", nargs="*", help="specific channel IDs/URLs to export (instead of member-only)")
    pb.add_argument("--channels-file", default=str(CHANNELS_FILE), help="file listing extra channels (default: channels.txt)")
    pb.add_argument("--no-channels-file", action="store_true", help="ignore channels.txt")
    pb.add_argument("--no-files", action="store_true", help="don't download file attachments (much smaller backup)")
    pb.add_argument("--fresh", action="store_true", help="start a new archive instead of resuming the existing one")
    pb.add_argument("--enterprise", action="store_true", help="required for Slack Enterprise Grid workspaces")
    pb.add_argument("--skip-login", action="store_true", help="don't auto-run login even if not authenticated")
    pb.add_argument("-y", "--yes", action="store_true", help="pass -y to slackdump (answer yes to prompts)")
    pb.add_argument("--dry-run", action="store_true", help="print the slackdump command and exit")
    pb.set_defaults(func=cmd_backup)

    pp = sub.add_parser("pick-channels", help="write an editable channels.txt of your conversations to choose from")
    pp.add_argument("--enterprise", action="store_true", help="required for Slack Enterprise Grid")
    pp.add_argument("--out", default=str(CHANNELS_FILE), help="file to write (default: channels.txt)")
    pp.set_defaults(func=cmd_pick_channels)

    pl = sub.add_parser("list-channels", help="print the conversations you can see")
    pl.add_argument("--enterprise", action="store_true")
    pl.add_argument("--member-only", action="store_true", help="only channels you belong to")
    pl.set_defaults(func=cmd_list_channels)

    pf = sub.add_parser("find-channels", help="search public channels by name (to add to channels.txt)")
    pf.add_argument("query", help="substring to search channel names for")
    pf.add_argument("--enterprise", action="store_true", help="required for Slack Enterprise Grid")
    pf.set_defaults(func=cmd_find_channels)

    pi = sub.add_parser("index", help="build the search database from export(s)")
    pi.add_argument("--export", action="append", help="export dir (repeatable; default: auto-discover under data/)")
    pi.add_argument("--db", default=str(DEFAULT_DB), help="output SQLite database path")
    pi.add_argument("-q", "--quiet", action="store_true", help="less output")
    pi.set_defaults(func=cmd_index)

    ps = sub.add_parser("serve", help="launch the local search web UI")
    ps.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    ps.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    ps.add_argument("--port", type=int, default=8731, help="port (default: 8731)")
    ps.add_argument("--no-browser", action="store_true", help="don't auto-open the browser")
    ps.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
