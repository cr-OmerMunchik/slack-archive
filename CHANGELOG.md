# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH).

## [1.2.0] - 2026-07-01

### Added
- Emoji rendering: message shortcodes like `:smile:` now show as real emoji (😄). Uses a bundled shortcode map (5,316 codes), so it stays fully offline with no new dependency. Custom workspace emoji that were never downloaded are left as their `:shortcode:` text.

### Fixed
- Right-to-left text: Hebrew (and other RTL) messages now display in the correct direction, matching the Slack app, instead of being forced left-to-right. Direction is detected per message, so mixed English and Hebrew each render correctly.

> To see these on an existing backup, re-index once: `.\search.ps1 -Reindex` (Windows) or `./search.sh --reindex`. Emoji are baked in at index time; the right-to-left fix applies as soon as you restart the search UI.

## [1.1.1] - 2026-07-01

### Fixed
- The **"From person"** filter (and the conversation, type, and date filters) now work on their own, with an empty search box. Previously a filter only applied alongside a text query, so picking a person and clicking "Apply filters" showed the landing page instead of that person's messages. Filter-only results are listed newest first.

## [1.1.0] - 2026-06-30

### Added
- **Auto-resume** (`--retries N`, default 2): if slackdump exits mid-capture from a transient network or API error, `backup` now re-runs `resume` automatically (with backoff) instead of stopping. This makes long and `--all-time` runs much more reliable. Set `--retries 0` to disable.
- **Attachment size limit** (`--max-file-size MB`): delete downloaded attachments larger than the given size, to keep the backup small.
- **Attachment pattern filter** (`--prune-attachments FILE`): a file of glob patterns (e.g. `Sensor*.exe`, `*.db`); matching attachments are removed after download. See `attachments.example.txt`.
- **`--version` flag**, and the web UI footer now shows the running version.

### Notes
- Pruning runs after slackdump downloads attachments, so it reclaims disk, not download time. Pair it with `--estimate` to check sizes first.

## [1.0.0] - 2026-06-30

First public release: back up your own Slack history and search it locally, fully offline.

### Added
- Resumable, incremental capture via slackdump (`archive` / `resume`) with a default 6-month time window (`--months`, `--since`, `--all-time`).
- Interactive channel picker (`--pick`) with search across the public-channel directory; DMs, group DMs, and private channels are always included.
- Files-free export plus a SQLite FTS5 index, and a local Flask search UI at `http://localhost:8731` (binds to localhost only, makes no outbound requests).
- Rendering of threads, @mentions, links, code blocks, inline images, and bot/app message content.
- `--estimate` / `--get-size`: a metadata-only dry run that reports estimated attachment size before downloading anything.
- `--no-files` text-only mode, gentle API pacing, and a progress line with a rough ETA.
- A Slack-flavored web UI theme.
- Cross-platform setup and run scripts (Windows PowerShell and macOS/Linux shell) with one-command setup.

[1.2.0]: https://github.com/cr-OmerMunchik/slack-archive/releases/tag/v1.2.0
[1.1.1]: https://github.com/cr-OmerMunchik/slack-archive/releases/tag/v1.1.1
[1.1.0]: https://github.com/cr-OmerMunchik/slack-archive/releases/tag/v1.1.0
[1.0.0]: https://github.com/cr-OmerMunchik/slack-archive/releases/tag/v1.0.0
