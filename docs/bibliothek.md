# Library: knowledge sources for the agent

As of 2026-09-26, stage two. In the Kontor (the chat window), the user enters
addresses, files and folders that Hermes should know about; the agent reads
them when needed and cites the source. It is meant for manuals such as
docs.kde.org and the user's own documents. Stage one (2026-09-26) was the
simple form: the store, the page, `library_list` and `library_fetch`. Stage two
(same day, separate branch) adds a mirror per entry in the cache, a full-text
index with SQLite FTS5 and `library_search`, and switches for the doc servers
from Hermes' MCP catalog; the page gains drag and drop, search, mirroring and
note editing. The store `bibliothek.json` stayed unchanged.

## What it does

- **“Library” page in the Kontor** (German default: „Bibliothek“), reachable
  from the button in the header and the menu item on the tray icon: an entry
  with address or path, title and note, file and folder dialogs, a drop area
  (files and folders from the file manager, addresses from the browser), a
  search field with a list of hits, for each entry the mirror status with a
  “Mirror” or “Cancel” button (German defaults: „Spiegeln“, „Abbrechen“),
  editing title and note, opening and removing, and at the bottom the switches
  for the doc servers. Escape or the arrow leads back to the chat. Mirroring
  and searching run in worker threads; progress reaches the event loop via
  signals.
- **Store** `~/.config/hermes-os/bibliothek.json` (format below). The icon
  writes, the plugin reads; both go through `plugins/hermes_os/library.py`. The
  icon loads the module by its file path and does not import the plugin
  package; the module needs neither Hermes nor Qt.
- **Prompt section**: With every new session the agent gets the list with ID,
  title, source, note and mirror status, plus the rules: first
  `library_search`, then `library_fetch` with the source of a hit; without a
  mirror, `library_fetch` and follow the links, or offer `library_mirror` (the
  plugin API takes a callable, which reads the file and the index fresh each
  time). An empty library tells the agent where the user can add sources.
  `library_list` shows the list with its status at any time.
- **`library_fetch`** gets a page or a file. `target` is the ID of an entry,
  an address below a listed address, a listed file, or a path below a listed
  folder; a folder returns its file list. HTML becomes text with headings,
  lists and image descriptions, plus the links on the same host, which the
  agent follows with another call. PDF goes through `pdftotext` (first 60
  pages); text formats are read directly. Long texts come in chunks (`start`,
  `max_chars`, default 12 000 characters). Addresses stay in the cache under
  `~/.cache/hermes-os/bibliothek` for 24 hours; `refresh` fetches them again.
- **`library_mirror(entry_id, depth, max_pages, refresh)`** creates or renews
  an entry's mirror; the button on the page does the same. An address is
  mirrored breadth-first from the start page: links on the same host below the
  path prefix, down to the depth (`depth`, default 2, 0 for the page only, at
  most 5) and up to the page limit (`max_pages`, 100 for the tool, 200 for the
  page, at most 2000). It is polite: it fetches and honors the host's
  `robots.txt` (Disallow, and Crawl-delay up to 10 s), waits half a second
  between two network fetches, pages from the 24-hour cache cost no fetch,
  links to images, archives, scripts and stylesheets are never fetched, and it
  sends the same User-Agent as the fetcher. Files and folders are indexed, not
  copied: the text goes into the index, the files stay where they are
  (folders: readable text formats and PDF, no hidden entries, up to the limit).
  Status per entry: page count, time, error count and the first errors
  (robots, foreign host, 404, binary file). A complete run removes pages from
  the index that no longer exist; a cancelled run leaves what is there. The
  tool runs synchronously within the call and can take minutes for many pages;
  its description tells the agent to announce that beforehand.
- **Index** `~/.cache/hermes-os/bibliothek/index.sqlite`: table `pages`
  (entry, source, title, text up to 400 000 characters, plus a folded copy for
  the fallback), `mirrors` (status per entry), and on top of them `pages_fts`,
  an external-content FTS5 table with the tokenizer
  `unicode61 remove_diacritics 2`, rebuilt after every mirror run. Both
  interpreters ship FTS5: the Python 3.13 of the Hermes venv (uv,
  python-build-standalone, SQLite 3.50 with `ENABLE_FTS5`, checked on
  2026-09-26) for the plugin, and Fedora's Python for the icon; the gate
  reports both. **Fallback**: if FTS5 is missing, `open_index` reports it when
  creating the virtual table, and `library_search` searches with `LIKE` in the
  folded column (lowercase, ß to ss, umlauts and accents stripped of their
  marks), with a snippet around the first hit, ordered by text length; the tool
  then notes „LIKE-Suche“ (LIKE search). The test forces the fallback once.
- **`library_search(query, entry_id, limit)`** returns hits with title, source
  (address or path), entry ID and a snippet with the matches marked, sorted by
  `bm25` (the title counts four times). Words are searched as word prefixes
  (“Datei” finds “Dateien”), a quoted phrase as a word sequence, several words
  are combined with AND. German spellings are added because the tokenizer only
  strips the umlaut dots: ß and ss, ae/oe/ue and umlaut (`grosse`, `Größe`,
  `GROESSE` find the same, `Strasse` finds `Straße`). Special characters of the
  FTS syntax are removed. Without a mirror, the answer points to
  `library_mirror`; without hits, it names what is mirrored. On the page, the
  same search field returns up to 30 hits; “Open” (German default: „Öffnen“)
  shows the source in the browser or in an application.
- **Doc servers (MCP)**: Hermes 0.21.5 has a catalog
  (`optional-mcps/<name>/manifest.yaml` in the Hermes repo,
  `hermes mcp install <name>`); context7 (`https://mcp.context7.com/mcp`,
  documentation and code examples for libraries) and deepwiki
  (`https://mcp.deepwiki.com/mcp`, questions about public GitHub projects) are
  in it, both anonymous, both Streamable HTTP. Installing through the CLI is
  interactive (tool selection in curses), so the switch writes the same entry
  itself: `mcp_servers.<name>` with `url` and `enabled: true` in
  `~/.hermes/config.yaml`. Only the server's block is changed, line by line, so
  the comments in the file stay; where PyYAML is available, it checks the
  result before writing. Switching off removes a block that consists only of
  `url` and `enabled`; a block with keys of its own (such as `headers` with an
  API key) is only set to `enabled: false`, and switching on reverses that. The
  switch leaves an `mcp_servers` in flow style alone. **No restart needed**,
  unlike in the plan: the gateway watches `config.yaml` and connects or
  disconnects servers within about a minute (`gateway/run_profile_reconcile.py`,
  docs `mcp.md`, “Reloading”); the API server the Kontor talks to picks up all
  enabled servers unless `platform_toolsets.api_server` says otherwise. A
  running conversation does not see the new tools; the next new conversation
  does. The tools are called `mcp__context7__<tool>` and
  `mcp__deepwiki__<tool>`.
- **Limits**: Only what the user listed is fetched: the same host including
  the path prefix, the file itself, paths below the folder. Redirects to
  foreign hosts are discarded, responses over 8 MB are not read, binary files
  are rejected. Fetched text sits between markers as external text; the rules
  in the prompt tell the agent that instructions inside it do not apply. The
  index is a copy of the text in the user's cache, nothing more; removing an
  entry removes its mirror too.

## Format

```json
{
  "version": 1,
  "entries": [
    {"id": "docs-kde-org", "kind": "url", "source": "https://docs.kde.org/",
     "title": "KDE-Handbücher", "note": "deutsch unter stable5/de",
     "added": "2026-09-26T18:30:00"}
  ]
}
```

`kind` is `url`, `file` or `folder`. The ID is derived from the host or the
file name (`docs-kde-org`, `handbuch-pdf`), with `-2` appended for a duplicate.
If the title is missing, the host or the file name takes its place. The mirror
status is not stored here but in `index.sqlite` (table `mirrors`: `status`
`running`, `done`, `error` or `cancelled`, `pages`, `started`, `finished`,
`depth`, `page_limit`, `error_count`, `errors` as a JSON list).

The entry the switch creates in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  context7:
    url: "https://mcp.context7.com/mcp"
    enabled: true
```

## docs.kde.org as the first entry

Address `https://docs.kde.org/`, with a note along these lines: “Manuals for
the KDE applications. German under stable_kf6/de/<program>/<program>/index.html,
overview at index.php?language=de&package=<program>”. The agent fetches the
overview, follows the link to the application and reads the chapter. Some of
the manuals are older than the running Plasma; the agent checks what they say
against the system with the os_* tools.

Checked on 2026-09-26 against the gateway in the test VM (stage one): asked
about the Dolphin manual, the agent called `library_list`, then `library_fetch`
several times along the links, and `web_search` with `site:docs.kde.org`; it
gave title, address and source in about 30 seconds and noted that the older
path `stable5/de` now returns 404.

For search, a narrower entry than the start page pays off: the overview links
to hundreds of applications, and a mirror with depth 2 and 200 pages gets stuck
in the overview. Better to add `https://docs.kde.org/stable_kf6/de/dolphin/` as
an entry of its own; then the whole manual is in the index.

## Testing

```sh
python3 tests/library-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
python3 tests/library2-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os \
    --config-template files/system/usr/share/hermes-os/config.yaml.default
```

Without Qt and without Hermes, anywhere with Python 3.9 or newer. Stage one
covers the store, IDs, mapping targets to entries, the fetcher against a mock
web server (HTML to text, links only from the same host, cache, `refresh`,
chunking, foreign hosts and binary files rejected), files and folders, and the
prompt section. Stage two covers mirroring against a mock server with
`robots.txt` (depth, page limit, Disallow, image links, redirect to a foreign
host, 404, progress, cancelling, a second run from the cache, `refresh`), folder
and file in the index, search with FTS5 (snippet, German spellings, phrase,
entry filter, limit, special characters), the forced LIKE fallback, tool texts,
the prompt section, removal clearing the index, and the switches against a copy
of the config template (on, a second one on, off, empty mapping, a block of its
own with `headers`, flow style rejected, missing file created, 0600 permissions
kept, PyYAML cross-check). `make lint` and the gate (`80-validate.sh`, 7g) run
both, the gate with the gateway's venv Python and a message on whether its
SQLite and Fedora's Python have FTS5. `tests/tray-gui-check.py` renders the
page offscreen: open, add an entry, show an error, remove, drop, mirror with
progress and the Cancel button, search with the hit list and Open, edit title
and note, the doc server switches, back.

## Pitfalls

- **New entries apply from the next conversation on.** The prompt section is
  frozen when a session is created; in a running conversation the agent sees
  new entries only through `library_list`. A new mirror, on the other hand, is
  searchable right away; `library_search` reads the index on every call.
- **A target must belong to an entry.** If the agent requests an address that
  is not listed, it gets a pointer to `library_list`, not a page. That is
  intentional: the library is not a general web fetcher; `web_extract` exists
  for that.
- **The model decides whether to look things up.** The rules in the prompt
  help, but they do not replace a model that uses tools reliably.
- **A mirror is only as good as its starting point.** Depth and page limit
  count from the listed address; list the start page of a large documentation
  server and you get overviews, not chapters. Narrower entries, one per manual,
  work better.
- **`library_mirror` blocks the conversation.** Up to 100 pages with a
  half-second pause come to a minute, plus fetch time. For large mirrors, use
  the button on the page: it runs in the background, shows progress and can be
  cancelled.
- **Two interpreters, one index.** The icon writes with Fedora's Python, the
  plugin reads with the venv's Python, both through the same SQLite file in WAL
  mode (next to it sit `index.sqlite-wal` and `-shm`). While a mirror is
  running, search reads the state as of the last commit. An interpreter without
  FTS5 can still read the index, just with the LIKE search.
- **The tokenizer does not know ß.** `remove_diacritics` turns ö into o, but
  not ß into ss; that is why `fts_query` adds the spellings. If you need other
  languages with rules of their own, extend `_term_variants`.
- **The switches write to the user's file.** `config.yaml` belongs to Hermes
  and the user; a switch changes only its own server's block and creates the
  file with a comment header if it is missing. Hermes itself writes the file
  with a ruamel round trip (`utils.atomic_roundtrip_yaml_save`); comments
  survive both.
- **Open: a check in the test VM.** The round trip (switch on, the gateway
  connects context7 within a minute, the agent uses `mcp__context7__*`) is
  backed by the source code but not yet observed in VM 112; the same goes for
  the page with real drag and drop from Dolphin and Firefox, and for a mirror of
  docs.kde.org.

## Next stage, open

- Renew mirrors automatically (age per entry, a background run via a gateway
  timer or the icon).
- More servers from the catalog as switches once there is a need; the
  `MCP_CATALOG` list in `library.py` is the only place for that.
- Take hits from the page straight into the conversation (“Discuss in chat”,
  German default: „Im Chat besprechen“, as in the morning report).
