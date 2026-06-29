# CLAUDE.md — guide for Claude Code / AI assistants (and curious humans)

This repo is **slack-archive**: back up your own Slack history and search it locally
in your browser, fully offline. `README.md` is the full human guide; this file is the
quick operational map so an AI assistant can help a teammate set it up.

## What it does
`slackdump` (a downloaded binary) exports your Slack → a small Python step indexes it
into **SQLite FTS5** → a local **Flask** app serves search at `http://localhost:8731`.
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
- `backup [--pick] [--enterprise] [--workspace NAME] [--channels …] [--out DIR]` — export via slackdump
- `pick-channels` — write an editable `channels.txt`; `find-channels <kw>` — search public channels by name
- `index` — build `data/search.db` from the export(s) under `data/`
- `serve` — Flask UI on `127.0.0.1:8731`

## Rules & gotchas (read before changing things)
- **Never commit user data.** Anything under `data/` (real messages + attachments), `bin/`
  (the binary), `.venv/`, and `channels.txt` is git-ignored and must stay that way.
- **Enterprise Grid:** pass `--enterprise` / `-Enterprise`. Slack does **not** reliably report
  which *public* channels a user belongs to, so the picker can't auto-include them — the user
  searches by name and ticks them; picks are remembered in `data/.picked_public.json`.
- **slackdump login is interactive** (a browser window) and must be run by the user.
  `slackdump` is pinned in the setup scripts (currently v4.4.1).
- **Code layout:** `slackarchive/{cli,db,ingest,server,slackfmt}.py` + `templates/` + `static/`.
  Storage/queries live in `db.py`; export parsing in `ingest.py`; the web app in `server.py`.
