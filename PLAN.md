# Slack History Archiver + Local Search: Project Plan

> **Working title:** `slack-archive`
> **Status:** **IMPLEMENTED 2026-06-29**: all milestones (§8) complete and validated on real sample data (search, threads, attachments, multi-export indexing, cross-platform scripts). Remaining: run the full real backup; optional polish. Decisions locked (Python+Flask, attachments included, MIT license). Step-0 feasibility passed, see §3a.
> **Author context:** Personal backup of one's own accessible Slack history ahead of a company migration from Slack to Microsoft Teams. Intended to be open-sourced internally and shared with colleagues.
>
> **Note (post-implementation):** the capture step evolved beyond the original `export`-based design in §7.1. It now uses slackdump's **resumable `archive`/`resume`** with a **default 6-month time window**, an interactive `--pick` channel selector, and gentle API pacing. **See [README.md](README.md) for current, authoritative usage**: the commands in §7.1 below are historical.

---

## 1. Goal

Let any colleague, on their own machine, **save their own accessible Slack history** (DMs, private channels, public channels, group DMs, and attachments) **fully offline**, and **search it through a local web UI** with fast full-text search.

Success = a teammate clones the repo, runs one setup command and one "backup" command, logs into Slack in a browser window, waits, then opens a local web page and can type a phrase and instantly find the message, months later, with no Slack access.

### Non-goals
- Not a server/multi-user product. Each person runs it locally for their own data.
- Not exporting *other people's* private data, only what the logged-in user can already see.
- Not a Teams importer. (Could be a future add-on; out of scope here.)

---

## 2. Hard requirements (from the user)

1. **Save locally**: no third-party cloud; data never leaves the machine.
2. **Web-based search**: searchable via a browser UI, good textual search.
3. **Runs on Windows** (primary dev/test machine) …
4. **…but as platform-independent as possible**: Mac and Linux should "just work" too.
5. **Dependencies are handled for the user**: setup scripts must detect and install (or fetch) everything needed. No "go install X yourself" gaps.
6. **Shareable on GitHub**: clean repo, real README, turnkey instructions.

---

## 3. Important caveats to surface to users (and to ourselves)

These go in the README prominently; they affect whether this works at all.

- **Authorization / policy.** This captures company communications during a sanctioned migration. Users should confirm it's compatible with their org's data-retention/governance policy, and **keep the data local** (the `.gitignore` enforces never committing it).
- **Admin visibility.** slackdump's own docs warn that automated access *may trigger Slack security alerts or notify workspace admins*, especially on **Enterprise Grid**. Not necessarily blocked, just not silent. Document this honestly.
- **SSO / 2FA.** Browser auto-login ("EZ-Login") works for most workspaces; SSO/Okta/2FA setups sometimes need the manual token+cookie method. Document both.
- **Workspace lockdown.** Some orgs disable token creation/exports entirely. We add a **Phase 0 feasibility check** so users find out in 2 minutes, not after a 2-hour export attempt.
- **Time.** Slack rate-limits scraping. Big histories can take minutes to hours. The capture is **resumable** (SQLite archive mode) so interruptions aren't fatal.

---

## 3a. Feasibility results (validated 2026-06-29, slackdump v4.4.1, Windows x64)

Step-0 ran end-to-end against a real Slack Enterprise Grid workspace:

- **Auth:** `workspace new` → **Interactive** login (system Edge browser) succeeded; creds cached locally.
- **Enterprise Grid confirmed** (org id `E0…`) → the full export must pass `-enterprise`; admin-visibility caveat applies.
- **Enumeration (`list channels -member-only`):** 101 conversations the user belongs to, **76 DMs, 21 group DMs, 4 private channels, 0 public channels**. (So this user's important content is private + DMs; public-channel scope is opt-in.)
- **Content extraction (`dump` of one private channel, last ~1 month):** pulled 68 top-level messages **with nested thread replies** and **29 attachments** (png/jpg/drawio) to local disk in ~39s.
- **Confirmed dump JSON schema** (drives the ingester): top-level `{channel_id, name, messages[]}`; each message has `ts, type, subtype, user, text, thread_ts, files, attachments, blocks, edited, reply_count, reply_users, latest_reply` and slackdump's `slackdump_thread_replies[]` (nested replies). User/channel names resolve via the export's `users.json`/`channels.json`.

**Conclusion:** the chosen approach works on this workspace. No blockers. Proceed to implementation.

---

## 4. Architecture overview

Three decoupled stages, so each can be re-run or swapped independently:

```
 ┌─────────────┐     ┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
 │   CAPTURE   │ --> │   INGEST     │ --> │   SEARCH INDEX    │ --> │   WEB UI        │
 │  slackdump  │     │  parse export│     │  SQLite + FTS5    │     │  Flask (local)  │
 │  (binary)   │     │  (Python)    │     │  data/search.db   │     │  localhost:8731 │
 └─────────────┘     └──────────────┘     └──────────────────┘     └─────────────────┘
   browser login        normalize msgs       BM25 ranked full-text     search box, filters,
   -> data/export/      users/channels       snippets, thread links    thread view, file links
```

- **Capture:** the mature `slackdump` binary (Go, single file, no runtime) handles auth, rate limits, pagination, all conversation types, and file downloads. We download the right prebuilt binary per OS/arch automatically, we do **not** reimplement Slack scraping.
- **Ingest:** a small Python step reads slackdump's **standard export** output (documented, stable Slack format) and normalizes it into our own clean SQLite schema. Decoupling from slackdump internals = resilient to their version changes.
- **Search index:** **SQLite FTS5** virtual table → BM25 relevance ranking + highlighted snippets, no external search engine, no Java/Solr, scales to large histories far better than in-memory JSON filtering.
- **Web UI:** a tiny **Flask** app serving server-rendered pages + a little vanilla JS. No npm/build toolchain, no CDN calls (offline-safe: all CSS/JS bundled locally).

### Why these choices
| Decision | Why | Alternatives rejected |
|---|---|---|
| `slackdump` for capture | No admin/app needed, all convo types + files, resumable, cross-platform, actively maintained | Official Slack export (admin-only, public channels only); custom Slack API client (reinventing auth+rate-limit) |
| Own the search layer (SQLite FTS5) | Genuinely good search (ranking, snippets, filters); single dependency; offline | `slack-export-viewer` (no index, in-memory filter only); `slack-history-viewer` (needs Solr/Java); SlackLogViewer (desktop-only, not web) |
| Python + Flask | Ubiquitous, readable, contributor-friendly, single runtime dep, no build step | Node (build toolchain); Go (zero-runtime but we'd have to cross-compile & ship per-OS binaries, see open decision) |
| Server-rendered + vanilla JS | Offline, no bundler, easy for colleagues to read/modify | React/Vite SPA (build step, heavier to share) |

---

## 5. Repository structure

```
slack-archive/
├── README.md                # quickstart, screenshots, troubleshooting, security note
├── PLAN.md                  # this file
├── LICENSE                  # e.g. MIT
├── .gitignore               # MUST exclude data/, bin/, .venv/  (never commit company data)
├── setup.ps1                # Windows bootstrap (PowerShell)
├── setup.sh                 # macOS/Linux bootstrap (bash)
├── backup.ps1 / backup.sh   # thin launchers -> slackdump login + export
├── requirements.txt         # Flask (+ minimal pins)
├── slackarchive/            # Python package (the parts we own)
│   ├── __init__.py
│   ├── cli.py               # `python -m slackarchive index|serve`
│   ├── ingest.py            # parse slackdump export -> SQLite
│   ├── db.py                # schema, FTS5 setup, queries
│   ├── slackfmt.py          # render Slack markup (mentions, links, code, emoji) -> HTML
│   ├── server.py            # Flask routes
│   ├── templates/           # Jinja: search, results, conversation/thread
│   └── static/              # bundled css + js (offline; no CDN)
├── bin/                     # slackdump binary, fetched by setup (gitignored)
└── data/                    # export output + search.db (gitignored)
```

**`.gitignore` is a safety feature here**, not an afterthought: it guarantees `data/` (actual messages) and `bin/` never get pushed to GitHub.

---

## 6. Cross-platform & dependency strategy

Principle: **two thin OS-specific bootstrap scripts, one shared Python core.** Per-OS scripts stay tiny so Windows/Mac/Linux can't drift.

`setup.ps1` (Windows) and `setup.sh` (Mac/Linux) each do the same four things:

1. **Detect OS + architecture** (x64 / arm64).
2. **Fetch slackdump**: download the matching prebuilt binary from a **pinned** GitHub release into `bin/`, verify checksum, mark executable. (No package manager required, but on Mac we can prefer `brew install slackdump` if Homebrew is present.)
3. **Ensure Python 3.9+**: if missing, attempt auto-install, - Windows: `winget install Python.Python.3.12` (fallback: direct python.org installer + clear message)
   - macOS: `brew install python` (fallback: python.org installer message)
   - Linux: `apt`/`dnf`/`pacman` detection (fallback: clear message)
   - *Optional upgrade:* use [`uv`](https://docs.astral.sh/uv/) to provision Python+venv in one step, fast and self-contained. Considered for v1.1.
4. **Create `.venv` + `pip install -r requirements.txt`** (just Flask + small pins).

After setup, **all real logic lives in the Python CLI**, called identically on every OS:
- `backup` → invokes the `slackdump` binary (login + export).
- `python -m slackarchive index` → build/refresh the search DB.
- `python -m slackarchive serve` → launch web UI + open browser.

This keeps the only genuinely platform-specific code in ~30 lines per bootstrap script.

---

## 7. Stage details

### 7.1 Capture (slackdump): v4.4.1 confirmed
- **Login (interactive, user-run once):** `slackdump workspace new <subdomain>` → choose **Interactive** → browser login. Credentials are cached (encrypted by default) in the OS cache dir, e.g. `%LOCALAPPDATA%\slackdump`. After this, all other commands run non-interactively.
- **Backup command (recommended):**
  `slackdump export -enterprise -member-only -type standard -o data/export`
  - `-enterprise` is **required on Slack Enterprise Grid** (the test workspace is on Grid, confirmed).
  - default `-chan-types` is already `mpim,im,public_channel,private_channel`; `-files` defaults to true.
  - `-member-only` = only conversations you belong to (recommended personal scope). To also capture specific public channels you are *not* a member of, append their IDs/URLs.
  - `-type standard` co-locates attachments per channel and stays `slack-export-viewer`-compatible.
- **Resumable for huge/interrupted runs:** `slackdump archive` (SQLite, supports `slackdump resume`) → `slackdump convert -f export`.
- **Auth fallbacks:** manual token (`xoxc-`) + cookie for locked/SSO workspaces; **QR-code** login (scan with Slack mobile app) bypasses Google SSO.

### 7.2 Ingest (Python → SQLite)
Parse the standard Slack export (`users.json`, `channels.json` + per-channel/day message JSON) into a normalized schema:

- `channels(id, name, type, topic, purpose)`, type ∈ public/private/im/mpim
- `users(id, name, real_name, display_name)`
- `messages(ts, channel_id, user_id, epoch, thread_ts, subtype, text, raw_json, has_files)`
- `files(id, message_ts, channel_id, name, mimetype, local_path, url)`
- `messages_fts`, **FTS5** virtual table over `text` (+ channel name, author) with `content=messages`, BM25 ranking, `snippet()` for highlights.

Idempotent + incremental: re-running after a fresh export updates the DB without duplicating.

### 7.3 Search Web UI (Flask)
- **Search box** → FTS5 `MATCH`, BM25-ranked, highlighted snippets.
- **Filters:** conversation (channel/DM picker), author, conversation type, date range.
- **Result item:** channel/DM name, author, timestamp, snippet → click to open **full thread/context** view.
- **Conversation view:** scroll an entire channel/DM; jump to a message; render Slack markup (bold/italic/code/blockquote), resolve `@mentions` and `#channels` to names, render emoji, and link attachments to their **locally downloaded** copies.
- **Quality-of-life:** pagination/lazy-load, empty/zero-result states, "open in folder" for files, copy-permalink-to-local-view.
- **Offline-safe:** all assets bundled; binds to `127.0.0.1` only.

---

## 8. Implementation milestones

1. **Scaffold**: repo tree, `.gitignore` (exclude data/bin/venv), LICENSE, README skeleton.
2. **Bootstrap scripts**: `setup.ps1` / `setup.sh`: OS/arch detect, fetch slackdump, ensure Python, venv, deps. *(Test on Windows now; structure for Mac/Linux.)*
3. **Capture wrapper**: `backup.*` + Phase-0 check; verify a real export lands in `data/export`.
4. **Ingest + schema**: `db.py` + `ingest.py`; build SQLite + FTS5 from an export.
5. **Search UI v1**: Flask: search box → ranked snippets with filters.
6. **Conversation/thread view + Slack markup rendering + local file links.**
7. **Polish**: pagination, errors, auto-open browser, friendly logs.
8. **Cross-platform pass**: verify Windows end-to-end; document/dry-run Mac/Linux.
9. **Docs**: README quickstart, screenshots, troubleshooting (SSO, enterprise alerts, locked workspaces), security/policy note.
10. **(Optional)** one-command launcher; encryption-at-rest note (OS disk encryption / password-protected archive); `uv` fast-path.

---

## 9. Testing strategy
- **Unit:** ingest parser against a tiny synthetic export fixture; Slack-markup renderer cases; FTS query building.
- **Integration:** fixture export → `index` → assert searches return expected hits/ranking; `serve` smoke test (routes return 200).
- **Manual E2E (Windows):** real small export → index → search a known phrase → open thread → open an attachment.
- **Cross-platform:** at minimum lint the bash script (shellcheck) and dry-run path logic; recruit a Mac/Linux colleague for a real run before publishing.

---

## 10. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Workspace blocks token/export | Phase-0 check fails fast; document manual token+cookie |
| Admin alerted by scraping | Document upfront; advise getting authorization |
| SSO/2FA login friction | Document manual auth method |
| Huge history / rate limits | Resumable `archive` mode; clear progress + "resume" guidance |
| Accidentally committing company data | `.gitignore` excludes `data/`; README warning; optional pre-commit guard |
| Python missing on Windows | setup auto-installs via winget; clear fallback |
| slackdump format changes | We parse the *standard export* format (stable) and pin a known-good slackdump release |

---

## 11. What gets shared on GitHub
- Code, scripts, README, LICENSE, PLAN.md.
- **Never** `data/` or `bin/` (gitignored).
- README includes: prerequisites, 3-step quickstart, screenshots, troubleshooting, and the security/authorization note.

---

## 12. Open decisions (for you)
1. **Runtime approach**: *Recommended:* Python+Flask (single, readable dependency; auto-installed). *Alternative:* ship zero-runtime Go binaries (no Python needed, but we must cross-compile and release per-OS binaries). 
2. **Attachments**: include downloaded files/images (richer, but larger `data/`) vs. text-only (smaller, faster). *Recommended:* include, with a flag to skip.
3. **Project name** for the public repo (working title `slack-archive`).
4. **License**: MIT assumed unless your company prefers otherwise.

---

## Sources
- [rusq/slackdump (GitHub)](https://github.com/rusq/slackdump)
- [slackdump export usage docs](https://github.com/rusq/slackdump/blob/master/doc/usage-export.md)
- [hfaran/slack-export-viewer (no real search index)](https://github.com/hfaran/slack-export-viewer)
- [mx-bernhard/slack-history-viewer (Solr-based)](https://github.com/mx-bernhard/slack-history-viewer)
- [Slack: Export your workspace data (admin/plan limits)](https://slack.com/help/articles/201658943-Export-your-workspace-data)
- [SQLite FTS5 full-text search](https://www.sqlite.org/fts5.html)
