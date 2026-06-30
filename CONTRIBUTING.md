# Contributing to slack-archive

Thanks for helping out! This is a small, focused tool — back up your own Slack
history and search it locally. Bug reports, docs fixes, and PRs are all welcome.
macOS testing and anything that smooths out first-run setup are especially valued.

## Dev setup

```bash
git clone https://github.com/cr-OmerMunchik/slack-archive
cd slack-archive

# the same one-time bootstrap users run (downloads slackdump, makes a venv, installs deps)
./setup.sh                 # Windows: powershell -ExecutionPolicy Bypass -File .\setup.ps1

# extra dev/test dependency
.venv/bin/python -m pip install -r requirements-dev.txt      # Windows: .venv\Scripts\python.exe
```

## Running the tests

```bash
.venv/bin/python -m pytest          # Windows: .venv\Scripts\python.exe -m pytest
```

The suite is offline and fast — it never calls slackdump or the network. It
covers the rendering, storage/search, ingest, and CLI-helper layers. Tests that
need SQLite FTS5 skip automatically if your Python build lacks it. CI runs the
same suite on Linux, macOS, and Windows for Python 3.9 and 3.12.

Please add or update tests for any behaviour you change.

## How the code is laid out

All the real logic lives in the **`slackarchive/` Python package** and is shared
by every platform:

| file | responsibility |
|---|---|
| `cli.py` | command-line entry point (`backup` / `index` / `serve` / pick / find) |
| `ingest.py` | parse a Slack export into the database |
| `db.py` | SQLite schema + FTS5 search |
| `slackfmt.py` | render Slack mrkdwn -> HTML + searchable plain text |
| `server.py` | the local Flask search UI |

`CLAUDE.md` has a fuller operational map of the pipeline.

## Key principles (please keep these)

- **Fix behaviour in the Python package, not in the wrapper scripts.** `backup.ps1`
  and `backup.sh` (and friends) are thin wrappers that just forward to
  `python -m slackarchive`. Logic added there would have to be duplicated and
  would drift between Windows and macOS/Linux. The Python is the single source of truth.
- **Never commit user data or credentials.** Everything under `data/`, the
  downloaded `bin/`, `.venv/`, `channels.txt`, and `workspace.txt` is git-ignored
  and must stay that way. Don't paste real tokens, cookies, or private message
  content into issues or PRs.
- **Match the surrounding style** — the code favours small, well-commented functions.
- **Keep it self-contained and offline** — the tool makes no outbound calls beyond
  Slack (via slackdump) during a backup; the search UI is localhost-only.

## Submitting changes

1. Branch off `main`.
2. Make your change; add/adjust tests; run `pytest`.
3. Update `README.md` / `CLAUDE.md` if you changed behaviour or commands.
4. Open a PR describing **what** changed and **why**. Make sure CI is green.

## Reporting bugs

Use the issue templates. Include your OS, Python version, slackdump version
(`bin/slackdump version`), and whether you're on Enterprise Grid. If you attach
logs from `data/last-backup.log`, **scrub tokens, cookies, and message content** first.
