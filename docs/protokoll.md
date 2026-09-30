# Log: what Hermes did to the system

The Kontor (the chat window) has a “Log” page (German default: „Protokoll“)
that answers, without a terminal: what did Hermes do to the system today? It
shows every approval request with its decision, every terminal command with a
system effect along with its result, and every app launch via `app_launch`.
With that it replaces the item “independent audit log” from phase 4, in the
form that needs no service of its own; see [Limits](#limits).

## What it does

- **“Log” page**, reachable from the clock button in the Kontor's header and
  the menu item on the tray icon. Each row: time (with the date if not from
  today), group, command, the decision and who made it, and the result with
  the exit code; the shortened output expands. The symbol on the left shows
  the result: executed, ended with error, not executed, waiting, app launched.
  Escape or the arrow leads back to the chat.
- **Filter**: period today, last 7 days or all; the “Changes only” checkbox
  (German default: „Nur Änderungen“) shows only system commands that actually
  ran (successfully or with an error). Denied, refused and pending requests
  and app launches drop out.
- **Export**: “Export” (German default: „Exportieren“) writes the rows shown to
  a text file via the file dialog, oldest first, with a header (computer, time,
  filter).
- **Language**: `audit.py` builds the texts of the rows (group, decision, who
  decided, result) and of the export when reading, in the icon's language
  ([systemagent.md](systemagent.md), “Interface language”). In an English
  session a row reads, for example, “Denied (user in tray icon) · Not
  executed” or “Executed, exit 0”, and the date is `2026-09-29` instead of
  `29.09.2026`. The file itself contains nothing language-dependent.
- **Updates**: While the page is open, the icon rereads the file on every
  change (`QFileSystemWatcher` on file and folder, debounced to 0.5 s). While
  the page is closed, it only notes that something arrived.

## Who writes what

The file is `$XDG_STATE_HOME/hermes-os/audit.jsonl` (default
`~/.local/state/hermes-os/audit.jsonl`), file 0600, folder 0700. One JSON line
per event, append only. At 5 MB the file becomes `audit.jsonl.1`, and an older
predecessor is dropped. Both sides use `plugins/hermes_os/audit.py`; the icon
loads the module by its file path, as with `library.py`, and the module needs
neither Hermes nor Qt.

| Event | Who | Hook or place | Content |
|---|---|---|---|
| `approval.request` | Plugin | `pre_approval_request` | Command, description, `pattern_key`, surface (cli, gateway, smart) |
| `approval.decision` | Plugin | `post_approval_response` | The same plus `choice` and `decided_by` |
| `command.result` | Plugin | `post_tool_call` for `terminal` | Status (ok, error, blocked), exit code, shortened output, error, duration |
| `app.launch` | Plugin | `post_tool_call` for `app_launch` | App ID, target, result text |
| `tray.decision` | Tray icon | Click on the card or the notification | Displayed command, choice, `request_id` |

All events of one tool call carry the same `call` (`tool_call_id`) and become
one row when read. A click in the icon does not know this ID; it attaches
itself to the most recent request from the last hour with the same displayed
command and adds “in tray icon” (German default: „im Leisten-Symbol“).

The plugin writes a result only for terminal commands that the approval hook
recognized as system commands (`classify_system_command`, the same groups as in
the boundary) or that went through the approval dialog (Hermes' own detector,
for example `rm -r`). Free commands in the home directory do not end up in the
log. The `pre_tool_call` hook keeps its match in memory only; nothing is
written until the request or the result, so that dry runs (gate,
`venv-smoke.sh`) do not create a file.

`__init__.py` has two lines for this: `audit.record_flagged` in the hook and
`audit.register_hooks` in `register()`. Everything else lives in `audit.py`.

## Decision and who decided

| Display | Source |
|---|---|
| Allowed once, Allowed for the session, Always allowed, Denied (user); German defaults: Einmal erlaubt, Für die Sitzung erlaubt, Immer erlaubt, Abgelehnt (Nutzer) | `choice` once, session, always, deny |
| Allowed by Guardian or Denied by Guardian (Guardian); German defaults: Vom Guardian erlaubt, Vom Guardian abgelehnt | `choice` smart_approve, smart_deny, `decided_by` aux_llm |
| Timed out, Withdrawn, Not deliverable (no answer); German defaults: Zeitüberschreitung, Zurückgezogen, Nicht zustellbar (keine Antwort) | `choice` timeout, cancelled, notify_failed |
| Refused (cron refusal); German default: Verweigert (Cron-Verweigerung) | Result `blocked` with the cron text from `approvals.cron_mode: deny`; no approval hook fires in cron |
| Refused (no one reachable); German default: Verweigert (niemand erreichbar) | Result `blocked` with no human and no gateway |
| Without asking (saved approval); German default: Ohne Rückfrage (gespeicherte Freigabe) | Result without an approval hook: allowed earlier “for this session” or “always”, or approvals off (`approvals.mode: off`, yolo) |

If the plugin and Hermes' own detector both ask for the same call, one after
the other (as with `systemctl restart` in 0.21.5), it stays one row; the last
decision counts.

## Hook contract in Hermes 0.21.5

Looked up in the tag `v2026.9.24`:

- `hermes_cli/plugins.py`, `VALID_HOOKS`: besides `pre_tool_call` there are
  `post_tool_call` and the observers `pre_approval_request` and
  `post_approval_response`. Observers cannot prevent anything; their return
  value is ignored.
- `model_tools._emit_post_tool_call_hook`: `tool_name`, `args`, `result`,
  `task_id`, `session_id`, `tool_call_id`, `turn_id`, `api_request_id`,
  `duration_ms`, `status` (ok, error, blocked), `error_type`,
  `error_message`. A call blocked by the `pre_tool_call` hook also gets
  `post_tool_call`, with `status="blocked"` and the blocking message.
  `post_tool_call` runs with `plugins.hook_callback_timeout`.
- `tools/approval_gateway_wait.py`, `tools/approval.py`,
  `tools/approval_smart.py`: the approval hooks get `command`,
  `description`, `pattern_key`, `pattern_keys`, `session_key`, `surface`,
  and through the context also `tool_call_id`, `turn_id`, `session_id`;
  `post_approval_response` additionally gets `choice` and, for the Guardian,
  `decided_by`. For a plugin approval, `command` is the placeholder
  `<terminal> (plugin approval rule)` and `pattern_key` is
  `plugin_rule:hermes-os:<group>`; the log knows the real command from the
  match of its own hook.
- The terminal result is JSON with `output`, `exit_code`, `error`.

## Limits

- **The log is not independent.** It lives in the home directory and is
  written by the process it observes. Anyone with write access to the home
  directory, user or agent, can change it. A tamper-proof log (a service of
  its own, a user of its own, a sealed journal) remains part of phase 4.
- **Only what goes through Hermes' hooks.** `execute_code`, file tools
  (`write_file`, `patch`) and MCP tools do not appear in the log, and neither
  do commands the user types in a terminal.
- **Output shortened and redacted.** 800 characters, start and end; obvious
  secrets (`password=`, `token`, `Bearer`, `sk-…`, credentials in URLs) are
  replaced with `***`. This is a heuristic, not a guarantee.
- **Several profiles**: Every Hermes process of the user writes to the same
  file, gateway or terminal chat. That is intended; the surface does not appear
  in the row, only in the event (`surface`).

## Testing

```sh
python3 tests/audit-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
```

Without Qt and without Hermes. It covers approval with a click and a result,
two requests for one call, denial, Guardian, timeout, cron refusal, saved
approval, the fallback via `classify`, free commands, `app_launch`, file
permissions, broken lines, filter, export, redaction, shortening, rotation.
`make lint` and the gate (`80-validate.sh`, 7h) run it. Step 6 of the gate
loads the plugin through the real loader, checks that the three hooks are
attached, and sends a `post_tool_call` through Hermes' `invoke_hook` all the
way into the file. `tests/tray-gui-check.py` renders the page offscreen: open,
symbols, expanding the output, period, changes only, export, empty, menu,
switching to the Library.

## Pitfalls

- **The “Changes only” checkbox also counts failed commands.** A
  `systemctl restart` with exit 5 may still have changed something.
- **Pending requests without a result** stay “Waiting” (German default:
  „Wartet“) if the gateway was stopped between request and answer.
- **PySide6 requires all parameters for QML functions**, so always call
  `auditSetFilter(period, changesOnly)` with both.
- **The watcher loses the file on rotation**; the icon adds it back after
  every change to the folder.
- **The row date and “today” on the page belong together.** For rows from
  today, `Main.qml` shows only the time; to decide, it compares `date` from
  `audit.py` (`%d.%m.%Y`, English `%Y-%m-%d`) with
  `Qt.formatDate(new Date(), qsTr("dd.MM.yyyy"))` (English `yyyy-MM-dd`).
  If one of the formats changes, change the other with it;
  `tests/lang-check.py` checks both languages.
- **The red message depends on words.** The page colors a message red if it
  contains “failed” or “not available” (German: „fehlgeschlagen“ or „nicht
  verfügbar“); new export error messages need one of them.
