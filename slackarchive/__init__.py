"""slack-archive: index a slackdump export into SQLite FTS5 and search it locally.

The package has three small, decoupled pieces:

* ``db``       - SQLite schema (incl. FTS5) and all read/write queries.
* ``ingest``   - parse a slackdump *standard* export into the database.
* ``server``   - a tiny Flask app that serves the search + browse UI.

``slackfmt`` renders Slack's ``mrkdwn`` into safe HTML for display.

Everything is driven from ``cli`` (``python -m slackarchive ...``).
"""

__version__ = "0.1.0"
