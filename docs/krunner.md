# KRunner: ask Hermes

Alt+Space opens KRunner. Type `hermes <question>` there, or `h: <question>` for
short, and the top match reads “Ask Hermes: <question>” (German default:
„Hermes fragen: <Frage>“). Enter opens the Kontor (the chat window) of the tray
icon and sends the question right away. The match's action “Look up only”
(German default: „Nur nachschlagen“; the button on the right of the match)
asks Hermes without opening the window and delivers the answer as a
notification.

It recognizes `hermes` followed by a space, colon or comma, and `h:`, in any
case: `Hermes: …`, `hermes, …`, `H:…`. The question stays as it was typed.
`hermes` alone, `h:` without a question, `hermesfoo` or `hermes-os` produce no
match; `hermes` alone still finds the menu entry “Hermes”.

In an English session ([systemagent.md](systemagent.md), “Interface
language”) the match reads “Ask Hermes: <question>” with the subtitle
“Enter: ask in the Kontor”, and the action “Look up only”; messages from a
lookup are in English (“Hermes: lookup failed”, “Hermes is not ready”). Name,
description and syntax help of the desktop file have `[en]` variants
(`X-Plasma-Runner-Syntax-Descriptions[en]`). The prefixes `hermes` and `h:`
are the same in every language.

## Structure

| File | Purpose |
|---|---|
| `files/system/usr/share/krunner/dbusplugins/hermes-os.desktop` | registers the runner with KRunner: `X-Plasma-API=DBus`, service `io.github.pottrauschen.hermesos.tray*`, path `/runner`, filter regex and minimum length |
| `files/system/usr/share/hermes-os/tray/runner.py` | prefix, match, actions, run, pending question, lookup; `install()` attaches the runner to the tray icon's Qt loop |
| `files/system/usr/share/hermes-os/tray/dbus_peer.py` | small D-Bus binding on the standard library alone: authentication, Hello, RequestName, reading and writing the wire format |
| `files/system/usr/libexec/hermes-os-tray` | calls `runner.install(...)` after startup; `--check` checks that `runner.py` can be imported |

The runner lives in the tray icon's process, because the event loop, the
gateway client and the window are already there. KRunner talks to it via
`org.kde.krunner1`:

- **Match(s) → a(sssida{sv})**: one match (ID `frage:<question>`, text, icon
  `hermes-os`, category relevance 100 = Highest, relevance 1.0, properties
  `subtext`, `category`, `actions`), otherwise an empty list.
- **Actions → a(sss)**: `lookup`, “Look up only”. Because of
  `X-Plasma-Request-Actions-Once=true`, KRunner asks for this only once.
- **SetActivationToken(s)**: arrives under Wayland right before Run; the token
  goes into `XDG_ACTIVATION_TOKEN`, and Qt uses it when activating the window.
- **Run(ss)**: an empty action sends the question to the window; `lookup`
  looks it up.
- **Teardown**, **Config** (only with `DBus2`), **Introspect**, **Ping**.

The service name in the desktop file ends in `*`. KRunner then only calls
services that are on the bus at that moment and does not attempt D-Bus
activation: if the tray icon is not running, there is no match and no error
log. The filter `X-Plasma-Runner-Match-Regex` makes KRunner call Match only
for input with a prefix.

**Into the window:** The window opens immediately. If Hermes is ready (gateway
up, history loaded, no run in progress), the question goes out at once;
otherwise it waits up to 90 seconds and goes out as soon as things are ready;
a newer question from KRunner replaces a waiting one. If that does not happen
in time, the question sits in the input field and a notification says so. The
question takes the same path as a typed one (`backend.send`), so it also
carries images that are attached in the window at that moment.

**Look up only:** a separate run in the conversation
`hermes-os-krunner-<date>`, one conversation per day, so that follow-up
questions on the same day have context and the window's history stays clean.
The answer arrives via `notify-send`, cut to 900 characters, with `MEDIA:`
paths removed. If Hermes asks for an approval during the lookup, the lookup
denies it and says so in the notification: without a window, nobody grants an
approval knowingly. After 180 seconds the run is stopped.

**Who can trigger the runner:** any process of the user on the session bus.
`Run` puts a question to Hermes without the caller knowing the API key. That
opens nothing new: the same user can read `~/.hermes/.env` anyway, approvals
still go through the window and notifications, and a lookup denies them. If
the project is renamed, the service name `io.github.pottrauschen.hermesos.tray`
in `runner.py` and in the desktop file has to change with it.

## Testing

```sh
python3 tests/runner-check.py            # also runs in make lint and in the gate (80-validate.sh, 7h)
```

The test needs neither Qt nor Hermes nor Plasma. It checks prefix detection,
umlauts, empty input, match and relevance, Run, the pending question, lookup
against a mock client, the wire format and the desktop file (required keys,
service name and path match `runner.py`, the filter matches the detection,
`desktop-file-validate` if available). If `dbus-daemon` and `dbus-send` are
present, it starts a private bus and calls Match, Run, Actions and Introspect
over the real bus.

In the Plasma session (VM 112):

```sh
busctl --user list | grep hermesos                        # name is owned by the tray icon
gdbus call --session -d io.github.pottrauschen.hermesos.tray -o /runner \
  -m org.kde.krunner1.Match 'hermes What time is it?'     # match as a(sssida{sv})
kquitapp6 krunner                                         # KRunner rereads dbusplugins
```

Then Alt+Space, `h: Which image is booted?`, Enter, and once more via
“Look up only”. A test build of the runner comes along when the tray icon is
started from the home directory (`HERMES_OS_TRAY_DIR`, see
[systemagent.md](systemagent.md)); the desktop file then belongs in
`~/.local/share/krunner/dbusplugins/`.

## Pitfalls

- **QtDBus from PySide6 is not enough.** Match has to return `a(sssida{sv})`,
  an array of structs. For that, `QDBusArgument.beginArray` needs a C++ type
  registered with `qDBusRegisterMetaType`, which does not exist from Python
  (“type … is not registered with D-Bus”); with a wrong element type, libdbus
  kills the process with `abort()`. KRunner does not accept a reply with `av`,
  because `QDBusPendingReply` compares the signature. Hence `dbus_peer.py`.
  Side note: in PySide6, `QDBusArgument << 5` writes a byte, not an `int32`.
- **KConfig escaping:** in desktop files, `\s` turns into a space when read.
  So the filter in `X-Plasma-Runner-Match-Regex` does without a backslash
  (`(?i)^ *(hermes[ :,]|h *:)`); the test checks this.
- **Lists in the desktop file** are split at commas by KConfig. So the
  entries of `X-Plasma-Runner-Syntax-Descriptions` must not contain a comma.
- **Avoid `X-Plasma-API=DBus2` with `*` in the service name:** with `DBus2`,
  KRunner requests Config from the first matching service at load time; if
  none is running at that moment, KRunner accesses an empty set. So filter and
  minimum length live in the desktop file, and `Config` only answers in case
  someone switches over.
- **Run IDs:** KRunner hands back the match ID without its own prefix
  (`X-Plasma-Runner-Unique-Results` is off). The question is contained in full
  in the ID, even when the text in the match is shortened.
