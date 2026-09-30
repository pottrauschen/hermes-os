# System agent: the tray icon

As of 2026-09-30. How Hermes shows up on the desktop without a terminal and
without a window that stays open all the time: an icon in the system tray, the
Kontor (the chat window, titled “Hermes Kontor”, German default: „Hermes-Kontor“)
with speech bubbles and images, and approvals as notifications.
Built, passed the gate and the tests, the window rendered offscreen in the test
VM, and the image path checked against the real gateway. Since 2026-09-26 and
2026-09-27, the icon and the Kontor have been in daily use in the Plasma session
of VM 112; the approval box and the approval notification ran there once on
2026-09-27 in a one-off check.

## What it does

- **Icon in the system tray** (StatusNotifierItem via `QSystemTrayIcon`)
  with four states: gray (gateway off or key missing), blue (ready),
  orange (working), yellow (asking for approval). The tooltip names the
  state and the Hermes version.
- **Click or Meta+H** opens a Kirigami window laid out like a messenger: at the
  top the Hermes icon as the other party, with a dot in the color of the state
  at its lower right, next to it the state as text (“Hermes is ready”, German
  default: „Hermes ist bereit“), on the right the buttons Library, Log, New and
  Set up (German defaults: „Bibliothek“, „Protokoll“, „Neu“, „Einrichten“;
  labeled in a wide window, icons with a tooltip in a narrow one). History and
  input sit in a reading column of at most 36 grid units (a little over 70
  characters), centered in a wide window. Your own messages sit on the right in
  a bubble in a muted accent color (at most 80% of the column), answers from
  Hermes on the left in a gray bubble (85%), errors in a red one; the corner
  facing the sender is sharper. Images appear as a small card above the
  message. Below each message, small and faint, is who wrote it and when
  (“Hermes · 18:31”, only the time for your own), with the date for earlier
  days. Text in the history is one step larger than the controls (system font
  size times 1.1; the typeface stays the system's). `tray/chat_text.py` sets
  answers from the Markdown: space below each paragraph, slightly more line
  height, lists with a narrow indent; Kirigami's text field can do neither of
  the first two. Answers are streamed.
  While Hermes is working and not writing, three dots pulse at the end of the
  history in a small bubble from Hermes: right after sending and between two
  tool steps (the backend's `waiting` property). Each
  tool call is a card (“✓ os_status · 0.3 s”, German default: „✓ os_status ·
  0,3 s“) that appears when the call starts and gets its duration or error at
  the end; text after it starts a new bubble below the cards. System notes
  (“Approval: Allow once”, German default: „Freigabe: Einmal erlauben“) sit
  between two thin lines. There is more space before each new question than
  between the parts of an answer. Text can be selected and copied, Markdown is
  rendered. Enter sends, Shift+Enter adds a new line (the tooltip on the round
  send button says so). An empty history shows the greeting as Hermes' first
  bubble and, at the lower right where your own message would go, three
  suggestions as pills; a click sends the suggestion. Escape hides the window,
  and so does closing it; the icon stays.
- **Attaching images**: with the button next to the text field (file dialog),
  with Ctrl+V from the clipboard (take a screenshot with Spectacle, then paste)
  or by dragging files into the window. Attached images appear as previews
  above the text field and can be removed one by one; they can also be sent
  without text. Images that Hermes leaves behind (screenshots, `image_generate`)
  appear in his bubble; a click opens them in the image viewer. Details
  under [Images](#images).
- **Approvals**: If a command needs approval under the boundary (README), the
  window shows a box with the command, the reason and the buttons Hermes allows
  (once, for this session, always, deny). A KDE notification with the same
  buttons appears as well, so you can answer without opening the window. If
  there is no answer within `approvals.timeout` (default 5 minutes), the
  command does not run.
- **Library**: The button in the header and the menu item on the icon open a
  page for adding addresses, files and folders (also by dropping them) that
  Hermes reads when needed; along with mirroring with progress, a search in the
  mirrors and the switches for the documentation servers; details in
  [bibliothek.md](bibliothek.md).
- **Log**: The button with the clock in the header and the menu item on the
  icon open a page with everything Hermes has done to the system: approvals
  with the decision, system commands with the result, app launches; details in
  [protokoll.md](protokoll.md). A click on an approval lands there too.
- **Seeing and hearing**: Meta+Shift+H selects a screen region and asks Hermes
  what it shows; holding Meta+Space records a question, the recognized text
  goes into the window, and the answer is read aloud. The camera button next to
  the text field attaches a region, the microphone button turns recording on
  and off; while Hermes listens or speaks, the icon shows a state of its own
  (red with a microphone, blue with a speaker).
  Details in [sehen-hoeren.md](sehen-hoeren.md).
- **Menu on the icon**: Open Kontor, New conversation, Library, Log, What am I
  looking at?, Talk to Hermes, Open dashboard, Set up Hermes, Start gateway,
  Chat in terminal, Quit (German defaults: Kontor öffnen, Neues Gespräch,
  Bibliothek, Protokoll, Was sehe ich hier?, Mit Hermes sprechen, Dashboard
  öffnen, Hermes einrichten, Gateway starten, Chat im Terminal, Beenden).
  “Open dashboard” starts the window `/usr/libexec/hermes-os-dashboard`
  ([dashboard.md](dashboard.md)) and only appears if it is executable.
- **Autostart** with every Plasma session. At the very first login the icon
  reports that Hermes is not set up yet and offers the setup assistant; after
  saving, the first-login script turns on the gateway, and the icon turns blue
  by itself.

## Files

| What | Where |
|---|---|
| Launcher, Python with PySide6 | `files/system/usr/libexec/hermes-os-tray` |
| Window, QML with Kirigami | `files/system/usr/share/hermes-os/tray/Main.qml` |
| Client for the API server, standard library only | `files/system/usr/share/hermes-os/tray/hermes_client.py` |
| Answers as HTML with paragraph spacing for the history (QTextDocument) | `files/system/usr/share/hermes-os/tray/chat_text.py` |
| Shortcuts and notifications with buttons, KGlobalAccel over D-Bus | `files/system/usr/share/hermes-os/tray/desktop.py` |
| Interface language: `is_english`, dictionary `EN`, `DictTranslator` for `Main.qml` | `files/system/usr/share/hermes-os/tray/lang.py`, for the boundary and the log `plugins/hermes_os/lang.py` |
| “What am I looking at?” (German default: „Was sehe ich hier?“) and push-to-talk, speech helper in the Hermes venv | `files/system/usr/share/hermes-os/tray/screenshot.py`, `voice.py`, `voice_worker.py`, see [sehen-hoeren.md](sehen-hoeren.md) |
| Menu entry “Hermes”, carries `X-KDE-Shortcuts=Meta+H` | `files/system/usr/share/applications/hermes-os-tray.desktop` |
| The same file for the global shortcut | `files/system/usr/share/kglobalaccel/hermes-os-tray.desktop` |
| Autostart in the Plasma session | `files/system/etc/xdg/autostart/hermes-os-tray.desktop` |
| Application icon (winged speech bubble with an H, pixel art as SVG, one path per color) and the six states (off, ready, working, asking, listening, speaking) | `files/system/usr/share/icons/hicolor/scalable/{apps,status}/` |
| Client test against a mock gateway | `tests/tray-client-check.py` |
| Render test of the window without a display | `tests/tray-gui-check.py` |
| Language test: dictionaries, coverage, translator on the real `Main.qml` | `tests/lang-check.py` |
| Showcase renders of the window for design changes (wide and narrow with a realistic-looking conversation, plus the greeting and the typing dots) | `tests/tray-showcase.py` |

Like the setup assistant, the icon runs with Fedora's Python and PySide6 from
Aurora, not with the Hermes venv. It imports nothing from Hermes; everything
goes over HTTP on localhost.

## The channel: the gateway's API server

Hermes' gateway (`hermes gateway run`, in hermes-os `hermes-gateway.service`)
comes with an API server that listens on `127.0.0.1:8642` as soon as
`~/.hermes/.env` contains an `API_SERVER_KEY` of at least 16 characters. The
first-login script creates it (random value, 48 hex characters, file mode 0600)
once a provider is set up, and restarts the gateway if needed.
Every request carries the key as a bearer token; the icon rereads it from
`.env` on every heartbeat, so no restart is needed.

Endpoints used (Hermes v2026.9.24):

| Endpoint | Purpose |
|---|---|
| `GET /health` | Heartbeat without a key, every 5 seconds |
| `POST /api/sessions` | Create the conversation, 409 if it already exists |
| `GET /api/sessions/{id}/messages?order=latest&limit=40` | History at startup, in chronological order |
| `POST /v1/runs` with `input` and `session_id` | Send a message, reply 202 with `run_id`; with images, `input` is a list of messages with `text` and `image_url` parts |
| `GET /v1/runs/{id}/events` | Event stream (SSE) |
| `POST /v1/runs/{id}/approval` with `choice` and `request_id` | Answer an approval |
| `POST /v1/runs/{id}/stop` | Cancel the run |

The chat goes through runs and not through the simpler sessions stream
(`/api/sessions/{id}/chat/stream`), because only the runs API exposes
approvals. The event stream carries `message.delta` (pieces of text),
`tool.started` and `tool.completed`, `approval.request` (with `request_id`,
command, reason, `choices`), `approval.responded` and finally
`run.completed`, `run.failed` or `run.cancelled`. The final event
carries the complete answer text in `output`; the icon replaces the streamed
text with it in case a provider sends no deltas.

The conversation is called `hermes-os-tray` and, like every Hermes session,
lives in `~/.hermes/state.db`; “New conversation” creates a session with a
timestamp and remembers its name in `~/.config/hermes-os/tray.json`.

## Images

**In.** When sending, the icon scales each attached image down in the worker
thread to at most 1600 pixels per side and encodes it as PNG (with
transparency) or JPEG until it is below 1.5 MB; at most four images per
message, and the API server accepts 10 MB per request. The image goes as a
`data:image/...` URL in an `image_url` part, the same form `/v1/responses`
accepts (`_normalize_multimodal_content` in `gateway/platforms/api_server.py`);
`/v1/runs` passes the content of the last message on to `run_conversation` in
that form. If the selected model cannot handle images, Hermes itself replaces
the image part with a description from `vision_analyze`
(`agent/vision_message_prep.py`); this needs a reachable vision model, which is
the case with OpenRouter. Checked on 2026-09-26 against the gateway in the test
VM: a generated test image was described correctly in just over three seconds.

**Out.** Hermes' tools put files into the answer text as a `MEDIA:<path>` tag.
Messaging platforms resolve the tags themselves, the runs endpoint does not;
`split_media_tags` in `hermes_client.py` strips them from the text following
the pattern of `MEDIA_TAG_CLEANUP_RE`, and the icon shows the files it finds
locally in the bubble. Other file types (PDF, audio) stay in the text.

**Display.** QML `Image` does not load `data:` URLs, so all images exist as
files. Images from the clipboard are saved as PNG under
`~/.cache/hermes-os/tray/`; large images get a scaled-down preview there
(`make_preview`) so that the history does not hold full-size photos in memory;
the next start removes files older than 14 days. In the stored history Hermes
replaces image parts with the placeholder `[screenshot]`
(`agent/session_persistence.py`); after the icon restarts, old images are
therefore no longer visible, and the icon shows “(image attached)” (German
default: „(Bild mitgeschickt)“) in their place.

## States and approvals

| State | When | Window |
|---|---|---|
| `off` | `/health` does not respond | Notice with “Set up Hermes” or “Start gateway” |
| `nokey` | Gateway is running, `.env` has no usable key | Notice with “Start gateway” (calls the first-login script, which creates the key) |
| `ready` | Heartbeat and key present | Text field active |
| `busy` | A run is in progress | Send becomes Stop |
| `asking` | `approval.request` is pending | Approval box with buttons |

The notification is created with `notify-send --action`, which waits and writes
the chosen action to stdout; it stays up for as long as
`approvals.timeout`. If you answer in the window, the waiting
`notify-send` is ended.

**Limitation:** The icon only sees approvals for runs it started itself.
Anything triggered in the terminal chat or via messaging platforms keeps asking
there. Cron and unattended runs are set to `deny` in the config template
anyway.

## Interface language

German is the default, like the whole system out of the box. If the session is
English, the Kontor, the menu on the icon, the tooltip, notifications, the
approval box, the Library and the Log show English text, for a demo recording,
for example. There is no gettext and there are no `.qm` files (the image lacks
`lrelease`): the German text is the key, and the `EN` dictionary in
`tray/lang.py` supplies the English one.

- **Who decides:** `lang.is_english()`, reading the environment on every call.
  `HERMES_OS_LANG=en` or `de` wins. Otherwise the first non-empty value
  from `LANGUAGE` (only the entry before the first colon), `LC_ALL`,
  `LC_MESSAGES` and `LANG` counts: English if it starts with `en`. Only
  that first value counts; `LC_ALL=C.UTF-8` with `LANG=en_US.UTF-8` stays German,
  as does `LANGUAGE=de` with `LANG=en_US.UTF-8`.
- **QML:** Every visible text in `Main.qml` is written in German inside `qsTr("…")`,
  numbers and shortcuts via `qsTr("… %1 …").arg()`. In an English session
  `hermes-os-tray` installs a `DictTranslator` (a subclass of `QTranslator` in
  `tray/lang.py`) before loading `Main.qml`; in a German session it installs
  none, and `qsTr` returns the source text.
- **Python:** `_()` from `tray/lang.py` wherever a text leaves the program:
  a property for QML, a notification, the menu, a message in the history.
  Constants such as `STATE_TEXT`, `CHOICE_LABEL`, `EFFORTS`, `DEFAULT_QUESTION`
  and `ACTIONS` stay German because tests compare against them.
- **Plugin:** The boundary (`boundary.py`) and the log (`audit.py`) have their
  own small dictionary, `plugins/hermes_os/lang.py`, with the same
  `is_english` as a code copy; the plugin runs in the gateway, the icon loads
  `audit.py` by path, and neither knows the other's folder. The boundary's
  message is created in the gateway and follows the gateway's environment; the
  backticks around the command stay in every language because
  `hermes_client.approval_command` reads the command from them. The icon builds
  the log lines when it reads them, so they follow the icon's language.
- **Formats:** duration in the history “0,3 s” or “0.3 s”, without a value
  “fertig” or “done”; date in the history “03.10. 18:31” or “Oct 03 18:31”
  (month names from `lang.MONTHS`); date in the log `29.09.2026` or `2026-09-29`.
- **Stays German:** messages from `library.py` on the Library page, error texts
  from the gateway (`GatewayError`) and from the speech helper
  (`voice_worker.py`), the preamble that passes context to the agent
  (`hermes_client.with_context`), the names of the shortcuts in System Settings
  (`desktop.py`), the setup assistant, the dashboard, the morning report and the
  plugin's system prompt. The language Hermes answers in, recognizes
  (`stt.language`) and reads aloud in (`tts.piper.voice`) is set in
  `~/.hermes/config.yaml`.
- **Switching:** Set the language of the Plasma session to English
  (System Settings, Region & Language; applies after the next login),
  or for Hermes only set `HERMES_OS_LANG=en` in
  `~/.config/environment.d/hermes-os-lang.conf`. Then restart the icon and
  `hermes-gateway`, otherwise both keep their old environment. The
  autostart files and the KRunner entry carry `[en]` keys.
- **New texts:** write them in German, wrap them in `qsTr()` or `_()`, add an
  EN entry to the dictionary. `tests/lang-check.py` finds missing
  keys, forgotten literals in `Main.qml`, mismatched placeholders and
  functions that bind `_` as a throwaway name.

## Testing

Without Qt, anywhere with Python 3.9 or newer, including the Windows workstation:

```sh
python3 tests/tray-client-check.py --tray-dir files/system/usr/share/hermes-os/tray
```

Starts a mock gateway on a free port and plays through heartbeat,
conversation, history (including image parts), sending with and without an
image, the event stream with approval and completion, and the MEDIA tags.
`make lint` runs it too.

Without a display, with PySide6 and Kirigami (image build, test VM, Aurora desktop):

```sh
tests/tray-gui-check.py --qml-dir files/system/usr/share/hermes-os/tray --out /tmp/shots
```

Renders the states with a stub instead of the gateway, attaches two generated
PNGs, removes one, sends with an image, shows images in both bubbles,
checks the answer as HTML from `chat_text.py` with “Hermes · time”
below it, clicks the approval buttons and treats every QML warning as an error. With `--out`
each step produces a PNG (off, ready-empty, attachments, typing, streaming,
approval, answered, nokey), useful for a look after changing the appearance.
The gate (`80-validate.sh`, 7d and 7e) runs both tests in the image build
and also checks `hermes-os-tray --check`, the desktop files and the
first-login script with a throwaway `.env`.

The language is checked by `tests/lang-check.py`: parts 1 to 4 without Qt, also
on Windows; the Qt part loads the real `Main.qml` with the stubs from
`tray-gui-check.py`, German without a translator, English with `DictTranslator`,
and then German again. The gate runs it in 7d.

```sh
python3 tests/lang-check.py --tray-dir files/system/usr/share/hermes-os/tray \
  --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
```

`audit-check.py`, `model-choice-check.py`, `runner-check.py` and
`sehen-hoeren-check.py` compare German texts and therefore set
`HERMES_OS_LANG=de` themselves; they pass in an English session too.
`tests/tray-showcase.py --lang en` draws English showcase renders.

From the Windows workstation the render test runs over SSH in the test VM
(copy files with `sed 's/\r$//'`, see `CLAUDE.md`); the PNGs from
`--out` can be fetched with `scp` and viewed.

In the test VM, from a directory instead of `/usr`, pushed into the running
session:

```sh
systemd-run --user --unit hos-tray --collect -p ExitType=cgroup \
  -E HERMES_OS_TRAY_DIR=$HOME/hos/share/hermes-os/tray \
  /usr/bin/python3 $HOME/hos/libexec/hermes-os-tray --show
```

If an instance from `/usr` is already running, it receives the `--show`
command; run `pkill -f hermes-os-tray` first.

## Pitfalls

- **Wayland does not set window positions.** The window cannot place itself
  next to the icon; KWin remembers the last position. A Plasma
  widget with a real popup would be the next step if that gets in the way.
- **Only one instance.** A local socket `hermes-os-tray-<uid>` passes
  “show” to the running instance; the menu entry and Meta+H call
  `hermes-os-tray --show`. The morning report's button „Im Chat besprechen“
  (discuss in chat) sends `discuss <path>` (`--discuss`) the same way, see
  [morgenbericht.md](morgenbericht.md); Meta+Shift+H sends `look`
  (`--look`), `--talk` toggles recording. If the socket is left behind after a crash,
  the next start cleans it up.
- **Shortcut**: KGlobalAccel reads defaults from
  `/usr/share/kglobalaccel/*.desktop` (`X-KDE-Shortcuts`), but launches the
  file of the same name under `applications/`. Both must be identical; the
  gate checks this. The user can change Meta+H in System Settings.
- **Icons by name**: The StatusNotifierItem transmits icon names, so the
  states live in hicolor. `20-agent-layer.sh` rebuilds the icon cache
  so that an old cache does not hide them.
- **`.env` is the source of the key.** `hermes setup` and the setup assistant
  write the same file through Hermes' `save_env_value`; existing lines are
  kept. Hermes treats a key shorter than 16 characters as missing, and the
  icon then shows `nokey`.
- **Gateway without API server**: If the gateway was already running before the
  key was in `.env`, it needs a restart; the first-login script only does that
  when it creates the key.
- **QML `Image` does not load `data:` URLs** (status Error), and `sourceSize`
  scales small images up instead of only limiting large ones. Hence: images
  as files, previews made by Python (`make_preview`).
- **Delegates are not in the QObject tree.** `findChild` from Python does not see
  items from a Repeater or ListView; `Main.qml` has `countNamed`
  and `clickNamed` for that, which search via `children`. PySide requires all
  parameters for QML functions; `None` stands for “not set”.
- **KDE suppresses `console.log`**: `/usr/share/qt6/qtlogging.ini` sets
  `*.debug=false`; use `console.info` for measurements in QML.
- **`atYEnd` includes the bottom margin of the list, `positionViewAtEnd`
  does not.** Combine the two and you get a “scroll to bottom” button that
  never goes away; the window checks the distance to the end instead. `originY`
  belongs to this too: the ListView shifts its origin when rows above it change
  height; without it the button stayed visible even at the end (VM 112, 2026-09-29).
- **No `Column` around the text field of a bubble.** A Column only measures its
  height at the next layout pass; combined with following the end (`positionViewAtEnd`
  on every new content height), the ListView kept recreating the rows,
  and the render test hung. So the text field sits directly in the bubble.
- **The text field has no paragraph or line spacing.**
  `Kirigami.SelectableLabel` is a TextEdit without `lineHeight`, and Qt sets
  Markdown tightly. `chat_text.py` sets the spacing in a
  QTextDocument and outputs HTML; the font family and size from its header
  are dropped, otherwise the Python document's font would win over the text
  field's. PySide does not read `textFormat` (no converter for the
  enum); the render test recognizes the HTML by its content.

- **`_` is not a throwaway name.** If a function calls `_()`, an
  `a, _ = …` inside it makes the name local for the whole function, and `_()` raises
  `UnboundLocalError`. Throwaway values are therefore named `_filter`, `_tool` or
  similar; `tests/lang-check.py` checks this.
- **`strftime("%b")` follows the locale.** `QApplication` calls
  `setlocale(LC_ALL, "")`; after that `%b` returns “Okt” in a German session,
  even when `HERMES_OS_LANG=en` is set. English month names come from
  `lang.MONTHS`.
- **The translator needs `isEmpty() == False`**, otherwise
  `installTranslator` returns False and sends no LanguageChange. Qt also queries
  its own contexts (`QGuiApplication`, `QIODevice`); for them the
  translator returns `None` (a null QString), and Qt then uses the source text. An empty
  text `""` would be a valid result for PySide6 and would leave Qt's own menus
  (Cut, Copy, Paste) empty.

## Planned

- Settings window “AI Assistant” (German: „KI-Assistent“): provider and model
  (opens the setup assistant), gateway, language, the boundary (`approvals`),
  reachable from the icon and in System Settings via
  `/usr/share/plasma/systemsettings/externalmodules/*.desktop`
  (`X-KDE-System-Settings-Parent-Category`).
- Dashboard button in the window header as well; today it is only in the menu on the icon.
- Show images from Hermes' answer while streaming (today only with the final
  event) and offer videos or PDFs from MEDIA tags for opening.
- Better-looking icons; the icon in the window header now carries a
  status dot in the color of the state.
