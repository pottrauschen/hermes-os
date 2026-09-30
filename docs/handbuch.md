# User guide: using hermes-os

hermes-os is a Linux with KDE Plasma in which an assistant works alongside you:
**Hermes**. Hermes knows your computer (system, programs, hardware), can get
things done for you and asks first when something would change the system.
This page explains how to use it. How it is built is described in
[entwicklung.md](entwicklung.md).

## The first start

1. Log in as usual.
2. The **setup assistant** opens by itself (its texts are still German). There
   you choose which language model Hermes works with: a provider (for example
   OpenRouter), your key from that provider and a model. Later you find it in
   the menu as “Set up Hermes” (German default: „Hermes einrichten“).
3. After that, Hermes sits as an icon at the bottom right of the panel.

The color of the icon shows what Hermes is doing:

| Color | Meaning |
|---|---|
| gray | off, or not set up yet |
| blue | ready |
| orange | working |
| yellow | asking you for permission |
| red with microphone | listening |
| blue with speaker | speaking |

## Talking to Hermes

**The Kontor (the chat window):** the title bar and the start menu call it
“Hermes Kontor” (German default: „Hermes-Kontor“). Click the icon or press
**Meta+H**. Type a question; Enter sends it, Shift+Enter starts a new line.
Escape or closing only hides the window; Hermes stays.

- **Sending images:** the button with the picture, Ctrl+V (for example a
  screenshot) or drag the file into the window.
- **Model and reasoning effort:** the small button to the left of the send
  button, for example “Sonnet 5 · medium” (German default: „Sonnet 5 · mittel“).
  More reasoning effort means more thorough but slower answers. The same choice
  is in the icon's right-click menu.
- **New conversation:** the “New” button at the top (German default: „Neu“). An
  empty Kontor shows three suggestions at the bottom right; one click sends the
  suggestion right away.
- At the top you also find **Library**, **Log** and **Set up** (German
  defaults: „Bibliothek“, „Protokoll“, „Einrichten“).

**Faster without the window:**

| Shortcut | What happens |
|---|---|
| Meta+H | Open and close the Kontor |
| Meta+Shift+H | Select a screen region; Hermes says what it shows |
| Hold Meta+Space | Speak a question; the answer is read aloud |
| Alt+Space, then `h: your question` | Ask Hermes from KRunner; Enter opens the chat, “Look up only” (German default: „Nur nachschlagen“) answers as a notification |

It also works in the terminal: `hermes`.

## What Hermes may do and when he asks

Without asking, Hermes may do anything in your home folder, start programs,
install apps from Flathub and check how the system is doing.

**He asks first** when something changes the system itself: updates, system
services, files under `/etc` or `/usr`, the firewall, users, commands with
`sudo`. A box then appears in the Kontor, along with a notification with the
same buttons:

- **Allow once** (German default: „Einmal erlauben“): just this one time
- **This session** („Für diese Sitzung“): until the end of the conversation
- **Always allow** („Immer erlauben“): from now on without asking
- **Deny** („Ablehnen“)

If nobody answers within five minutes, the command does not run. Hermes never
reboots or shuts down by himself; he asks you to do it.

The **Log** (German default: „Protokoll“; the button with the clock) shows what
Hermes did to the system: approvals with your decision, system commands with
their result, launched programs.

## What else Hermes can do

- **Library:** add addresses, files and folders where Hermes should look things
  up, such as a handbook or your notes. He names the source when he quotes from
  it. Entries can be mirrored and then searched. More:
  [bibliothek.md](bibliothek.md).
- **Morning report:** every morning a notification about updates, errors, disk
  space and services; “Discuss in chat” (German default: „Im Chat besprechen“)
  opens the report in the chat. To switch it on:
  `ujust hermes-morgenbericht-ein 07:45`.
- **Dashboard:** Hermes' own settings in a window: models, keys, conversations,
  scheduled tasks, extensions, logs. In the icon's menu: “Open dashboard”
  (German default: „Dashboard öffnen“).
- **Local model:** Hermes without the cloud, on your graphics card. Small
  models are weaker than the large cloud models. To switch it on:
  `ujust hermes-lokal-ein`. More: [lokales-modell.md](lokales-modell.md).
- **Launching programs:** “Launch Firefox” is enough.

## Keeping the system up to date

hermes-os updates as a whole, like a phone: the new system is downloaded in
the background and takes effect with the next reboot. The old one stays as a
fallback.

- **Updates:** `ujust update`, then reboot. Hermes can start this for you, but
  asks first.
- **Back to the previous state**, if something breaks after an update:
  `sudo bootc rollback`, then reboot.
- **Programs:** through Discover or Flathub. They are updated separately from
  the system.
- Hermes himself comes with the system. `hermes update` does not exist here.

## Commands at a glance

All hermes-os commands start with `ujust hermes`. `ujust --list | grep hermes`
shows them with a short explanation.

| Command | Purpose |
|---|---|
| `ujust hermes-setup` | Choose provider, key and model |
| `ujust hermes-tray` | Open the Kontor |
| `ujust hermes-dashboard` | Open the dashboard |
| `ujust hermes-doctor` | Hermes checks himself |
| `ujust hermes-gateway-status` | Is the background service running? Latest messages |
| `ujust hermes-gateway-enable` | Switch on the background service |
| `ujust hermes-morgenbericht-ein` / `-aus` | Morning report on and off |
| `ujust hermes-lokal-ein` / `-aus` / `-entfernen` | Local model |
| `ujust hermes-os-info` | Which system and which Hermes are installed |

## When something does not work

| What you see | What helps |
|---|---|
| Icon stays gray, “The Hermes gateway is not running” (German default: „Das Hermes-Gateway läuft nicht“) | “Start gateway” (German default: „Gateway starten“) in the Kontor, or `ujust hermes-gateway-enable` |
| “not set up yet” (German default: „noch nicht eingerichtet“) | “Set up Hermes” (German default: „Hermes einrichten“) in the menu or in the window |
| Hermes answers with an error about the provider | Check your key and credit with the provider, then `ujust hermes-setup` |
| Speaking does not work | Check the microphone in System Settings; the icon tells you when there is none |
| Something stops working after an update | `sudo bootc rollback`, reboot, and report it |
| Unclear what Hermes did | The Log in the Kontor |

`ujust hermes-doctor` collects the most important checks at a glance.
