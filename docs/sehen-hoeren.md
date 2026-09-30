# Seeing and hearing

As of 2026-09-27. Two ways to reach Hermes without typing, both in the tray
icon ([systemagent.md](systemagent.md)): a screen region with the question
“What am I looking at?” (German default: „Was sehe ich hier?“), and
push-to-talk with a spoken answer. Built; `make lint` and the hardware-free
test pass, and the window was rendered offscreen with stubs. “What am I looking
at?” has been running in the Plasma session of VM 112 since 2026-09-27. Of
push-to-talk, only the shortcut has been checked there; recording, recognition
and read-aloud are unchecked because VM 112 has no microphone, see
[Open items](#open-items).

## What am I looking at?

**Meta+Shift+H** opens Spectacle's region selector. After Enter or a
double-click, the region goes to Hermes:

- **Window closed:** Hermes gets the image and the default question (“What am
  I looking at here? Briefly describe …”, German default: „Was sehe ich hier?
  Beschreibe kurz …“) silently, in a separate conversation per day
  (`hermes-os-look-<date>`), as with lookups from KRunner
  ([krunner.md](krunner.md)). The answer arrives as a notification with the
  region as its icon and the button **Discuss in chat** (German default:
  „Im Chat besprechen“). The button brings question, image and answer into the
  window, attaches the region for a follow-up question and passes the answer
  to the next message as context. If Hermes asks for an approval during this,
  the approval is denied and the answer says so.
- **Window open** (or the camera button next to the text field, or the menu
  item on the icon while the window is open): the region lands as an
  attachment, the default question sits in the input field and can be edited,
  and Enter sends both. This is the way to ask your own question about the
  image.
- Escape in the region selector cancels without a message.

`hermes-os-tray --look "question"` does the same with your own question, also
from scripts; the running instance receives the command over the local socket.

## Visual check: Hermes looks for itself

After a visible change to the desktop (panel, wallpaper, theme, windows,
widgets), Hermes only reports “done” once a screenshot shows the change. The
reason: it once reported the taskbar change (floating to fixed) as done because
`evaluateScript` returned `floating=false` while the panel was still floating.
The rule is in the plugin's system prompt (section „Ehrlich berichten“, “report
honestly”, in `plugins/hermes_os/__init__.py`), the recipe is in the skill
(section „Änderungen am Desktop“, “changes to the desktop”). No new
dependencies are needed:

1. **Screenshot:** Hermes calls Spectacle from its terminal tool,
   `spectacle --new-instance --background --nonotify --fullscreen --output <file>`.
   This works because the gateway runs as a user service attached to the
   Plasma session and inherits its environment (`WAYLAND_DISPLAY`,
   `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`); Hermes' local shell passes
   it on. Before that,
   `systemd-run --user --wait --collect -q kscreen-doctor --dpms on` wakes a
   display that has been switched off.
2. **Look:** `vision_analyze` (toolset `vision`, also part of the toolset of
   the API server that the Kontor (the chat window) talks to) reads the file
   from the local path. If the main model can handle images, for example
   Claude via OpenRouter, the image goes straight into its context
   (`_vision_analyze_native` in `tools/vision_tools.py`); otherwise an
   auxiliary vision model describes it. The full screenshot arrives scaled
   down to at most 1568 pixels per side; `region` (in screenshot pixels)
   enlarges a section at full resolution.
3. **Show:** `MEDIA:<path>` in the answer puts the screenshot into the bubble
   in the Kontor ([systemagent.md](systemagent.md), section Images).

The screenshots live under `$XDG_RUNTIME_DIR/hermes-os/` (tmpfs, gone on
logout), with a timestamp in the name: a new name per screenshot keeps an old
one from passing as new. If `vision_analyze` is missing (a model without image
support and no auxiliary model reachable), Hermes reads the setting back and
asks the user to check, instead of saying “done”. Invisible settings
(keyboard, shortcuts, behavior) don't show up in a screenshot; there Hermes
reads the setting back and says “set, please try it once”.

**The panel lies.** Plasma docks a floating panel to the screen edge as long
as a non-minimized window touches it, which a maximized window always does: in
`views/Panel.qml` of the Plasma shell (6.7.5), `touchingWindow` sets the float
to zero, and only “Show Desktop” (German: „Desktop anzeigen“) lifts that. A
screenshot with such a window shows the panel docked although it is still set
to floating, and the gap of a floating panel is only a few pixels wide in the
scaled-down screenshot. So the recipe inspects the panel's edge through
`region`, asks whether a window touches the panel, and in that case, or when
in doubt, takes another screenshot under “Show Desktop”: `qdbus-qt6 org.kde.KWin /KWin
org.kde.KWin.showDesktop true`, screenshot, `… showDesktop false` brings the
windows back. The plugin's boundary and Hermes' detector both let the two
calls through.

## Push-to-talk

**Hold Meta+Space** to record, release to stop. A short **tap** (under
0.35 s) turns recording on and the next press ends it; the microphone button
in the window and `hermes-os-tray --talk` work the same way. Recording stops
after 90 seconds at the latest. Then:

1. The recording (16 kHz, mono, WAV) goes to the **speech helper** in the
   Hermes venv, which transcribes it with faster-whisper: model from
   `stt.local.model`, language from `stt.local.language` or `stt.language`
   in `~/.hermes/config.yaml` (the template sets `small` and `de`).
2. The text goes into the Kontor like a typed message (`backend.send`), the
   window opens, and the answer streams in.
3. Once the answer is complete, Piper reads it aloud (voice from
   `tts.piper.voice`, template `de_DE-thorsten-medium`), without Markdown,
   tables as lists, links as “Link”, at most 1500 characters; the window shows
   the rest.

While Hermes listens, the tray icon is red with a microphone and the window
header says “Hermes is listening …” (German default: „Hermes hört zu …“);
while it speaks, the icon is blue with a speaker. Pressing the shortcut while
Hermes speaks interrupts it and starts recording; in both states the
microphone button in the window turns into a stop button. On first use the
helper downloads the Whisper model and the voice; the header then says
“Loading speech model small …” (German default: „Lade Sprachmodell small …“).

Without a microphone (no input source according to
`pactl list short sources`; monitors don't count), a notification says
“Hermes cannot listen” (German default: „Hermes kann nicht zuhören“); an
empty recording (pw-record does not abort without a source, the file stays at
0 seconds) reports “Hermes heard nothing” (German default: „Hermes hat nichts
gehört“). Without the gateway, the message says what was understood. None of
this crashes; the state goes back to `idle`.

**In an English session** ([systemagent.md](systemagent.md), “Interface
language”) the default question reads “What am I looking at here? Briefly
describe …”, the notification “Hermes: What am I looking at?” with the button
“Discuss in chat”. The header says “Hermes is listening …”, “Hermes is
transcribing …”, “Hermes is thinking …” and “Hermes is speaking …”, the
messages read “Hermes cannot listen”, “Hermes heard nothing” and so on; the
read-aloud text uses “Code block skipped” and “The rest is in the window”.
This does not switch recognition or voice: for that, set `stt.language: en`
and an English Piper voice in `tts.piper.voice`. Error texts of the speech
helper (`voice_worker.py`) stay German.

## What leaves the machine

The screen region and the recognized text go to the configured model provider
like any chat message; if you don't want that, set up a local model
([lokales-modell.md](lokales-modell.md)). Audio stays local: recognition
(faster-whisper) and speech output (Piper) run in the Hermes venv, and no
recording goes to the network. On first use the helper downloads the Whisper
model from Hugging Face to `~/.cache/huggingface/hub` and the voice to
`~/.hermes/cache/piper-voices`, without a checksum of its own. There is no
approval dialog: recording and screen region are tied to a user action
(holding the key, the region selector), and the signal is the red icon with
the microphone. This matches the boundary in the README: a system boundary,
not a data boundary.

## Structure

| File | Purpose |
|---|---|
| `files/system/usr/share/hermes-os/tray/desktop.py` | shared helpers: key sequences in Qt format, collision list, `notify` and `notify_actions` (notify-send with buttons), `GlobalShortcut` (KGlobalAccel over D-Bus with press and release) |
| `files/system/usr/share/hermes-os/tray/screenshot.py` | Spectacle call, `LookFlow` (the flow without Qt), `install()` with `look` for Main.qml |
| `files/system/usr/share/hermes-os/tray/voice.py` | recorders (pw-record, parecord, arecord), microphone check, `Worker` (speech helper as a process), `PushToTalk` (state machine), text for read-aloud, `install()` with `voice` for Main.qml |
| `files/system/usr/share/hermes-os/tray/voice_worker.py` | runs with the venv Python: faster-whisper and Piper, JSON lines on stdin/stdout, `--check` for the gate |
| `files/system/usr/share/hermes-os/tray/dbus_peer.py` | new: `add_match`, `subscribe`, `emit_signal` for signals |
| `files/system/usr/share/applications/hermes-os-sehen.desktop`, the same file under `kglobalaccel/` | menu entry “Hermes: What am I looking at?” (German default: „Hermes: Was sehe ich hier?“) with `X-KDE-Shortcuts=Meta+Shift+H`, `Exec=hermes-os-tray --look` |
| `files/system/usr/share/icons/hicolor/scalable/status/hermes-os-tray-{listening,speaking}.svg` | the states listening and speaking |
| `files/system/usr/libexec/hermes-os-tray` | registration: `--look`, `--talk`, socket commands `look` and `talk`, menu items, `answerFinished`, `discussAnswer` |
| `files/system/usr/share/hermes-os/tray/Main.qml` | state display in the header, camera and microphone buttons |
| `tests/sehen-hoeren-check.py` | test without hardware and without Qt, see below |

The speech helper is a separate process because the tray icon runs on Fedora's
Python and PySide6, while faster-whisper and Piper live in the Hermes venv
(Python 3.13). It starts with the first job, keeps the models loaded and exits
after ten minutes without a job. Recognition and synthesis go through Hermes'
own helpers first (`tools.transcription_tools.
transcribe_audio_local_fallback`, which evaluates `stt.*` in full, plus
`tools.voice_mode.is_whisper_hallucination`); Piper is called directly, with
the voice from the folder Hermes uses as well
(`~/.hermes/cache/piper-voices`, a populated legacy folder
`piper_voices_cache` or `tts.piper.voices_dir`); if the voice is missing,
`python -m piper.download_voices` downloads it there. If Hermes' helpers
cannot be imported, the helper calls faster-whisper directly, with the same
arguments as Hermes (`beam_size 5`, VAD, thresholds for `no_speech_prob` and
`avg_logprob`). None of this comes with a stability promise; the gate checks
the imports on every build, and a Hermes bump checks `voice_worker.py --check`
in the venv.

Heavy work never runs in the GUI thread: stopping the recording, recognition,
synthesis and playback sit in worker threads or in the helper process and
report back through a Qt signal; `PushToTalk` only sees events in the main
thread.

## Shortcuts

| Shortcut | Route | Why |
|---|---|---|
| Meta+Shift+H | desktop file under `/usr/share/kglobalaccel/`, kglobalacceld starts `hermes-os-tray --look` | like Meta+H, free in Plasma 6, fits the window shortcut; only a press is needed |
| Meta+Space | the running instance registers with `org.kde.kglobalaccel` (component `hermes-os-voice`, „Hermes: Sprechen“, “Hermes: Speak”) and receives `globalShortcutPressed` and `globalShortcutReleased` | holding needs a release, and only this route delivers one; a desktop file only starts programs. Meta+Space is free in KWin, Plasma and Spectacle; only fcitx5 uses it to switch input methods, when it is enabled |

Both can be changed in System Settings under Shortcuts (application
“Hermes: What am I looking at?” and component „Hermes: Sprechen“);
kglobalacceld restores the saved choice at login, and the window shows it in
the tooltip of the microphone button. One thing about kglobalacceld: it does
not watch its registrants, so on exit the icon releases the shortcut with
`setInactive`, and it registers again when `org.kde.kglobalaccel` gets a new
owner (KWin restarted). Since Plasma 6.7, kglobalacceld saves a shortcut that
is already taken anyway, and the action registered first silently wins; the
icon asks via `globalShortcutAvailable` and writes a warning to the journal.

## Testing

Without Qt, without audio, anywhere with Python 3.9 or newer:

```sh
python3 tests/sehen-hoeren-check.py      # also runs in make lint and in the gate (80-validate.sh, 7n)
```

It checks the desktop file (both copies identical, shortcut, Exec,
`desktop-file-validate` if available), key sequences and collisions,
registration with KGlobalAccel against a mock kglobalacceld on a private bus
(`doRegister`, `setShortcutKeys` as `a(ai)`, `getComponent`, signals for
press and release, saved binding, `setInactive`), `notify_actions` against a
mock notify-send, recording commands, the microphone check, the recorder
against a mock process, the state machine along every path, the speech helper
against fakes of `faster_whisper` and `piper` (model and language from
`config.yaml`, segment filter, synthesis, timeout, idle exit) and the image
path against a mock client (image as a data URL in the run, notification,
button, attachment with the window open). Without `dbus-daemon`, the bus part
is skipped.

In the image build, the gate also checks `voice_worker.py --check` with the
venv Python (faster-whisper, Piper and Hermes' helpers importable), and
`tests/tray-gui-check.py` renders the speech states in the window with stubs
for `voice` and `look`.

In the test VM (see [testumgebung.md](testumgebung.md)), with a test build
from the home directory as in [systemagent.md](systemagent.md):

```sh
busctl --user call org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel \
  shortcutKeys as 4 hermes-os-voice push-to-talk "Hermes: Sprechen" "Mit Hermes sprechen"   # shortcut registered?
pactl list short sources                                   # microphone present?
HERMES_HOME=$HOME/.hermes /usr/lib/hermes-agent/.venv/bin/python \
  /usr/share/hermes-os/tray/voice_worker.py --check         # helper in the venv
spectacle -i -b -n -r -o /tmp/test.png                     # region selector without the window
/usr/libexec/hermes-os-tray --look "What does it say?"     # image path
/usr/libexec/hermes-os-tray --talk                         # recording on; run again: off
journalctl --user -u hos-tray -f                           # warnings from the icon
```

## Pitfalls

- **`spectacle --background` returns a frozen image** when the display is off
  via DPMS ([testumgebung.md](testumgebung.md)). For the region selector the
  display is on; when calling it from a script, run `kscreen-doctor --dpms on`
  first.
- **Spectacle is a unique application.** If a Spectacle is already running, a
  second call hands its arguments to the first one and exits immediately;
  waiting for the process then tells you nothing. Hence `--new-instance`.
  Escape exits with code 0 and no file; the target file is deleted beforehand,
  so “no file” means cancelled.
- **The screenshot portal has no region mode.** Interactively,
  xdg-desktop-portal-kde only offers full screen, screen and window; without a
  dialog it takes the whole screen and asks for permission once. KWin's
  `ScreenShot2` can capture regions, but only from coordinates. Hence
  Spectacle.
- **QML `Image` does not load data URLs:** the region stays as a file under
  `~/.cache/hermes-os/tray/ausschnitt-*.png` (14 days); the gateway gets the
  data URL, as with any attachment.
- **A desktop file sends no release.** `KServiceActionComponent` only reacts
  to presses. So push-to-talk registers itself, under a component name of its
  own, not `hermes-os-tray.desktop`: under that name kglobalacceld manages the
  desktop file, and that sends no signals.
- **The release arrives with the first released part** of the shortcut, Meta
  or Space. Since Plasma 6.5, key repeat arrives as a separate signal,
  `globalShortcutRepeated`, which the icon ignores; a second “Pressed” while
  the key is held (older Plasma) fizzles out in the state machine.
- **pw-record does not abort without a microphone**; it writes 0 frames.
  Hence the check before and the length check after; SIGINT lets pw-record
  write the WAV header cleanly.
- **faster-whisper and Piper don't run on Fedora's Python.** The speech helper
  is a process with the venv Python; `HERMES_OS_VOICE_PYTHON` overrides the
  interpreter for tests. Hermes' `tools.*` helpers have no stability promise;
  if they are missing, the direct route is used.
- **The Whisper model lands in the Hugging Face cache**
  (`~/.cache/huggingface/hub`); Hermes sets no `download_root`, so terminal
  chat and tray icon share the file. `small` is about 460 MB, and the first
  call needs network access.
- **The language is English if `stt.language` is missing:** Hermes defaults to
  `en`. The config template sets `de`; if you don't use the template, set the
  key, or Whisper will take German questions for English.

## Open items

- The rest of the test in VM 112 (on 2026-09-27 the region selector, the
  notification with image and button, the attachment with the window open, and
  press, release and repeat of the shortcuts worked): the entry in System
  Settings, behavior after `kwin_wayland --replace`; microphone and speakers
  in the VM (audio device in Proxmox), first download of model and voice,
  latency of recognition and synthesis on the CPU; Meta+Space against fcitx5,
  if enabled.
- Speak the answer while it streams (sentence by sentence); today only after
  the run has finished.
- Your own question without the window: Plasma can show a notification with an
  input field (`inline-reply`), but `notify-send` does not return the reply;
  that would need a direct call to `org.freedesktop.Notifications` through
  `dbus_peer`.
- Wake word from the tray icon; today only shortcut and button.
- Rehearse the visual check in VM 112: screenshot from within the gateway,
  `vision_analyze` with the configured model, no follow-up question from
  Hermes' security scan (tirith) or approval gate during the recipe; the
  plugin's boundary lets all of its commands through. Also the panel with a
  window touching it, and the route via “Show Desktop”.
