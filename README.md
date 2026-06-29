# 🗄️ slack-archive

**Back up your own Slack history — DMs, group chats, private & public channels, and file attachments — to your computer, and search it in your browser. Fully offline. No admin rights needed.**

Built for the situation where your company is leaving Slack (e.g. migrating to Microsoft Teams) and you don't want to lose the conversations, decisions, and links that live in your message history.

- 🔒 **Private & local** — your data is downloaded to *your* machine and never leaves it.
- 🔎 **Real full-text search** — fast SQLite FTS5 with ranked results, highlighted snippets, and filters by conversation, person, type, and date.
- 🧵 **Reads like Slack** — threads, @mentions, links, code blocks, inline images and file attachments.
- 💻 **Cross-platform** — Windows, macOS, Linux. One setup script handles all dependencies.
- 🙅 **No admin / no app approval** — uses [`slackdump`](https://github.com/rusq/slackdump) with your normal Slack login.
- ⏯️ **Resumable & incremental** — captures the last 6 months by default (configurable); stop and re-run anytime to continue, and routine backups only fetch what's new.

> You can only back up what *you* can already see in Slack. This is your own history, saved for your own reference.

---

## Requirements

- **Windows, macOS, or Linux.**
- **Python 3.9+** — the setup script installs it for you if it's missing (via winget / Homebrew / your package manager).
  - On **Debian/Ubuntu**, make sure venv + pip are present first: `sudo apt install -y python3 python3-venv python3-pip`.
- An internet connection for the one-time download of the `slackdump` binary.

Everything else (the `slackdump` binary, the Python packages) is fetched automatically into the project folder.

---

## Quickstart

### Windows (PowerShell)

```powershell
# 1. One-time setup: downloads slackdump, sets up Python + dependencies
powershell -ExecutionPolicy Bypass -File .\setup.ps1

# 2. Back up your Slack history. Opens a browser to log in, then interactively lets you
#    pick channels, choose whether to include attachments, and how far back (default 6 months).
.\backup.ps1 -Enterprise -Pick                # Slack Enterprise Grid (e.g. Cybereason)
.\backup.ps1 -Pick                             # non-Grid workspaces

# 3. Build the search index and open the search UI in your browser
.\search.ps1
```

### macOS / Linux

```bash
chmod +x setup.sh backup.sh search.sh

./setup.sh                                     # one-time setup
./backup.sh --enterprise --pick                # log in, then pick channels + attachments + how far back
./backup.sh --pick                             # non-Grid workspaces
./search.sh                                    # builds the index and opens the browser
```

That's it. The search UI runs at **http://localhost:8731** and only listens on your own machine.

> **Logging in:** the backup step opens a browser window. Pick **Interactive** when asked for a login method (works with SSO/Okta/password). If your company uses *Sign in with Google*, choose **QR Code** and scan it with the Slack app on your phone. Your workspace name is the part before `.slack.com` — to find it, right-click any message in Slack → *Copy link*. The backup uses a **default workspace**, so you usually don't need to enter it; override with `-Workspace <name>` / `--workspace <name>`, a local `workspace.txt`, or the `SLACK_ARCHIVE_WORKSPACE` env var.

---

## Choosing what to back up

By default, `backup` saves **every conversation you belong to**: direct messages, group DMs, and the private/public channels you've joined.

### How far back (time window)

This is the key to a backup that actually **finishes**. Slack throttles thread history hard, so grabbing *all of time* on big channels can take days. By default `backup` captures the **last 6 months** — the interactive picker asks, and you can set it explicitly:

```powershell
.\backup.ps1 -Enterprise -Months 12      # last 12 months
.\backup.ps1 -Enterprise -Since 2025-01-01
.\backup.ps1 -Enterprise -AllTime        # everything (can be very large/slow)
```
```bash
./backup.sh --enterprise --months 12   # or --since 2025-01-01  /  --all-time
```

A longer window means **much more time and disk** — start modest; you can always widen it later (re-run with a larger window).

### Recommended: the interactive picker (`-Pick`)

This is the easiest way to back up, and what the Quickstart uses. Add `-Pick` / `--pick` to `backup` and it walks you through everything in the terminal — which channels, whether to include attachments, and how far back — no files to edit:

```powershell
.\backup.ps1 -Enterprise -Pick      # Windows
./backup.sh --enterprise --pick     # macOS/Linux
```

It always keeps your own conversations (DMs, group chats, private channels). Then — because a workspace can have **tens of thousands** of public channels — it's **search-driven** instead of one endless list:

```
You belong to 5 channel(s) — all pre-selected. 31,402 more public channels are available.

✓ Channels to back up (5): #team-private, #engineering, #releases, ...
Search channels to add/remove (blank to review & finish): platform
Space = toggle (ticked = included), Enter = apply:
 ❯ ◉ #platform
   ◯ #platform-eu
   ◯ #platform-fyi
  -> 6 channel(s) selected so far.

=== This backup will include ===
  - all of your DMs and group chats
  - 6 channel(s):  #team-private  #engineering  #releases  #platform  ...
Proceed?  ❯ Yes - back up this selection / No - keep choosing / Cancel
```

Type part of a name, tick matches with **Space**, **Enter** to apply, repeat for more, then approve. It's built to be hard to lose track:

- **Shows your running selection** before every search (`✓ Channels to back up (3): #engineering, …`).
- **Pre-ticks the channels you belong to** (and anything you added before) — untick to remove them.
- **Remembers your picks between runs**, so you curate your channel list once and reuse it.
- The 30k-channel directory is fetched once and **cached**, so searching is instant after the first run.

Cross-platform (Windows/macOS/Linux via `questionary`).

> **Enterprise Grid note:** Slack/slackdump can't reliably report which *public* channels you belong to, so your sidebar's public channels are **not** auto-included — search for and add the ones you want here (the picker remembers them afterward).

### Or edit a file

Prefer not to use the interactive picker? Generate an editable `channels.txt` with every conversation you're in, all pre-selected:

```powershell
.\pick.ps1 -Enterprise        # Windows  (drop -Enterprise if not on Grid)
./pick.sh --enterprise        # macOS/Linux
```

Then open **`channels.txt`** and:
- **Comment out** (put `#` in front of) anything you *don't* want to back up.
- **Add extra public channels** you're *not* in by pasting their links/IDs at the bottom.

Don't know a public channel's link or ID? **Search for it by name:**

```powershell
.\find.ps1 -Enterprise releases     # Windows  → lists public channels matching "releases" + their IDs
./find.sh --enterprise releases     # macOS/Linux
```

Then paste the IDs you want into `channels.txt`:

```
# ---- Private ----
C01ABCDEFGH    # team-private
# C01IJKLMNOP  # design-private      <-- commented out = skipped

# ---- Extra public channels ----
C01QRSTUVWX    # engineering   (found via find-channels)
https://yourworkspace.slack.com/archives/C0123ABCD
```

The next `backup` exports exactly that selection. (1:1 DMs appear as user IDs in the picker file, but real names show up everywhere in the search UI.)

> Prefer not to use the picker? Just create `channels.txt` by hand (see `channels.example.txt`). If `channels.txt` is absent or empty, `backup` falls back to everything you belong to.

---

## Searching

Open the UI and type in the search box. You can:

- **Filter** by type (channels / private / group DMs / DMs), by a specific conversation, by who sent it, and by date range.
- **Click any result** to jump into the conversation with surrounding context and the hit highlighted.
- **Expand threads** inline, and **view image attachments and files** that were downloaded with the backup.

---

## How it works

Three decoupled stages:

```
 slackdump archive ─► data/archive/ ─► convert ─► data/export/ ─► index ─► data/search.db ─► serve
 (login + resumable    SQLite + files   (files-free  text-only      SQLite     full-text       Flask
  capture)             (one copy)        export)      JSON           FTS5        search          localhost
```

1. **Capture** — [`slackdump`](https://github.com/rusq/slackdump) saves your conversations into a **resumable SQLite archive** (`data/archive/`) using your own login. Interrupt it anytime — re-running **resumes** where it left off, and later runs are **incremental** (only new messages).
2. **Convert + index** — the archive is converted to a *files-free* export (so attachments aren't stored twice), then a small Python step parses it, resolves @mentions/links, renders HTML, and builds a SQLite **FTS5** index. Attachments are read straight from the archive.
3. **Serve** — a tiny local Flask app gives you the search + browse UI. No external requests are ever made.

---

## Updating later

Just run `backup` again — it **resumes/append-updates** your existing archive (only fetching new messages, and skipping threads it already has in full, which keeps it fast and avoids most rate-limiting). Then re-index: `search.ps1 -Reindex` / `./search.sh --reindex`.

- **Stopped halfway?** Safe — re-run `backup` and it continues from where it stopped.
- **Want to change your channel selection?** Run `backup -Fresh` / `--fresh` to start a new archive.
- **Disk filling up?** Re-run with `-NoFiles` / `--no-files` (or answer *no* to attachments in the picker) to keep text only — drops the size dramatically.
- **Watching it run?** The console stays quiet on purpose: a progress line with a **rough ETA** prints every ~30s, and full slackdump logs go to `data/last-backup.log`. Requests are paced gently via `slackdump.gentle.toml` (this can't beat Slack's limits — it just reduces retry churn; `--no-pacing` uses slackdump defaults).

---

## Security & privacy

- **Your data stays on your machine.** The web server binds to `127.0.0.1` (localhost) only and makes no outbound connections.
- **Nothing sensitive is committed to git.** `.gitignore` excludes `data/` (your messages and files), `bin/` (the binary), and `.venv/`. Only the *code* is meant to be shared.
- **Check your company policy.** Backing up your own conversations during a sanctioned migration is normal, but confirm it's consistent with your organisation's data-handling rules, and keep the data local.
- **Enterprise Grid visibility.** On Slack Enterprise Grid, automated access *can* be visible to workspace admins. This is expected behaviour of `slackdump`, not something this tool hides.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **`auth error` / nothing exports** | You're not logged in. Run `backup` again — it launches the login. On Enterprise Grid, add `-Enterprise` / `--enterprise`. |
| **Login window won't complete (SSO/Okta)** | Re-run and choose **QR Code**, scan with the Slack mobile app. |
| **"Sign in with Google" workspace** | Choose **QR Code** or **User Browser** at the login-method prompt. |
| **Enterprise Grid** | Always pass `-Enterprise` (Windows) / `--enterprise` (macOS/Linux). |
| **`sqlite3 was built without FTS5`** | Use a python.org build of Python (its bundled SQLite includes FTS5), then re-run setup. |
| **Port 8731 in use** | `.\search.ps1 -Port 9000` or `./search.sh --port 9000`. |
| **Huge workspace / slow / rate-limited** | Normal — Slack throttles thread fetches. The archive is **resumable**: stop and re-run `backup` to continue, and repeat runs are incremental. Use `-NoFiles` / `--no-files` to skip attachments. |
| **ETA keeps climbing / stuck fetching threads** | Slack throttles thread *replies* to a crawl — full thread history can be impractically slow. Finish now with `-NoThreads` / `--no-threads` (skips remaining thread replies; keeps all messages + threads already saved), or grab just recent ones with `-SkipStale p30d` / `--skip-stale p30d`. |
| **Windows blocks slackdump.exe** | Setup already unblocks it; if prompted, choose *More info → Run anyway*. |

---

## Project layout

```
slack-archive/
├── setup.ps1 / setup.sh        # one-time bootstrap (slackdump + Python + venv)
├── pick.ps1  / pick.sh         # generate an editable channels.txt to choose channels
├── find.ps1  / find.sh         # search public channels by name (to add to channels.txt)
├── backup.ps1 / backup.sh      # export your Slack history
├── search.ps1 / search.sh      # build index + open the search UI
├── channels.example.txt        # template; your real channels.txt is git-ignored
├── slackdump.gentle.toml       # gentle API pacing passed to slackdump (-api-config)
├── requirements.txt            # Python deps (Flask + questionary)
├── slackarchive/               # the Python package
│   ├── cli.py  db.py  ingest.py  server.py  slackfmt.py
│   ├── templates/  static/
├── bin/                        # slackdump binary (downloaded; git-ignored)
└── data/                       # archive/ + export/ + search.db (git-ignored)
```

---

## Credits & license

- Capture powered by [**slackdump**](https://github.com/rusq/slackdump) by Rustam Gilyazov (GPL-3.0; downloaded as a standalone binary, not bundled).
- This project is released under the **MIT License** — see [LICENSE](LICENSE).
