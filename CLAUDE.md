# CLAUDE.md — guide for Claude Code / AI assistants (and curious humans)

This repo is **slack-archive**: back up your own Slack history and search it locally
in your browser, fully offline. `README.md` is the full human guide; this file is the
quick operational map so an AI assistant can help a teammate set it up.

## What it does
`slackdump` (a downloaded binary) saves your Slack into a **resumable SQLite archive**
(`data/archive/`) → that's converted to a *files-free* export → a small Python step indexes
it into **SQLite FTS5** → a local **Flask** app serves search at `http://localhost:8731`.
Backups are **resumable + incremental**; attachments are stored once (in the archive).
No data ever leaves the machine.

## Helping a user — the 3 steps
Run everything **from the repo root**. Windows uses the `.ps1` scripts; macOS/Linux use `.sh`.

1. **One-time setup** (downloads slackdump, creates a Python venv, installs deps):
   - Windows: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
   - macOS/Linux: `./setup.sh`
2. **Pick channels + back up** (opens a browser for the Slack login):
   - Windows: `.\backup.ps1 -Pick`   (add `-Enterprise` on Slack Enterprise Grid)
   - macOS/Linux: `./backup.sh --pick`   (add `--enterprise`)
3. **Index + open the search UI**:
   - Windows: `.\search.ps1`
   - macOS/Linux: `./search.sh`

Re-index after a later backup: `.\search.ps1 -Reindex` / `./search.sh --reindex`.

## The CLI under the scripts
`python -m slackarchive <command>`:
- `backup [--pick] [--enterprise] [--workspace NAME] [--channels …] [--no-files] [--fresh]` —
  capture via slackdump. Creates/updates `data/archive` (resume if it exists; `--fresh` rebuilds),
  then converts to `data/export`. `--no-files` = text only (much smaller). The interactive `--pick`
  flow also asks whether to include attachments (default yes).
- `pick-channels` — write an editable `channels.txt`; `find-channels <kw>` — search public channels by name
- `index` — build `data/search.db` from `data/export`; resolves attachments from `data/archive`
- `serve` — Flask UI on `127.0.0.1:8731`

## Rules & gotchas (read before changing things)
- **Never commit user data.** Anything under `data/` (real messages + attachments), `bin/`
  (the binary), `.venv/`, and `channels.txt` is git-ignored and must stay that way.
- **Enterprise Grid:** pass `--enterprise` / `-Enterprise`. Slack does **not** reliably report
  which *public* channels a user belongs to, so the picker can't auto-include them — the user
  searches by name and ticks them; picks are remembered in `data/.picked_public.json`.
- **Default workspace** is resolved from `SLACK_ARCHIVE_WORKSPACE` env → `workspace.txt` →
  built-in fallback (`cybereason`), so the login won't prompt for it. Override with `--workspace`.
- **Archive is the master store.** `backup` runs `slackdump archive` (or `resume`) into
  `data/archive` (SQLite + `__uploads`), then `convert -f export -files=false` into `data/export`.
  Files are deliberately NOT copied into the export (avoids double-storing GBs); the indexer reads
  attachments straight from `data/archive/__uploads` (handled in `ingest._build_file_index`, which
  understands both `F<id>-name` and `__uploads/F<id>/name` layouts).
- **slackdump login is interactive** (a browser window) and must be run by the user.
  `slackdump` is pinned in the setup scripts (currently v4.4.1).
- **Code layout:** `slackarchive/{cli,db,ingest,server,slackfmt}.py` + `templates/` + `static/`.
  Storage/queries live in `db.py`; export parsing in `ingest.py`; the web app in `server.py`.
