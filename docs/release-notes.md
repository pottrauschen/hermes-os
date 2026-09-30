# Release notes

One section per version, newest first. The text of a section is the text of the
release on GitHub.

## hermes-os 0.1

First release, 2026-10-01.

### What hermes-os is

An atomic desktop Linux in which an AI agent is part of the system. hermes-os is a
working title: it leans on Hermes Agent and can read as a Nous Research product, which it
is not; a new name is planned for 0.2.

- **Base:** Aurora DX (Universal Blue, Fedora bootc, KDE Plasma on Wayland), Fedora 44.
  The system under `/usr` is read-only; updates arrive as a whole image and can be
  rolled back.
- **Agent:** Hermes Agent by Nous Research, pinned to release v2026.9.24 (0.21.5),
  baked into the image and read-only under `/usr`. Hermes is updated only with a new
  image; `hermes update` refuses and points to `ujust update`.
- **German by default:** system language, keyboard, Plasma language and time zone
  Europe/Berlin, changeable in System Settings. The agent's windows follow the session:
  English when the session is English (the first set value of `LANGUAGE`, `LC_ALL`,
  `LC_MESSAGES` and `LANG` starts with `en`, or `HERMES_OS_LANG=en`), German otherwise.
- **Images**, public on ghcr.io, rebuilt on pushes to `main` that change the image and weekly:
  `ghcr.io/pottrauschen/hermes-os` (AMD and Intel) and
  `ghcr.io/pottrauschen/hermes-os-nvidia` (NVIDIA).
- **Source:** [github.com/pottrauschen/hermes-os](https://github.com/pottrauschen/hermes-os).

### What is in it

- **Tray icon and the Kontor (the chat window):** The icon shows what Hermes is doing (grey
  off, blue ready, orange working, yellow asking). A click or Meta+H opens the Kontor, with images (file, Ctrl+V, drag and drop) and a choice of model and
  reasoning effort.
- **Hermes knows the system:** image, services, apps, hardware, network, journal,
  updates, language and keyboard, read-only and without root.
- **The boundary:** Work in the home directory runs freely, apart from a few risky commands
  (see docs/grenze.md). Anything that touches the
  system (updates, system services, `/etc`, `/usr`, sudo except for pure read commands)
  asks first, as a box in the Kontor and as a KDE notification with buttons. Hermes
  never reboots or shuts down the machine itself; it asks you to. The Log page in the
  Kontor shows what it did to the system.
- **“What am I looking at?”** (German default: „Was sehe ich hier?“): Meta+Shift+H
  selects a screen region, and Hermes explains it.
- **Ask Hermes in KRunner:** Alt+Space, then `hermes <question>` or `h: <question>`.
- **Library:** web addresses, files and folders where Hermes looks things up and which
  it cites as sources.
- **Also:** a setup assistant at first login, Hermes' web dashboard as a window, a
  morning report as a notification, push-to-talk (Meta+Space) with speech recognition
  and speech output on your own machine, and optionally a local model on your own GPU
  (Ollama, downloaded into the home directory on request, not in the image).

### Installation

From an existing bootc system (Aurora, Bluefin, Silverblue, Kinoite):

```sh
sudo bootc switch ghcr.io/pottrauschen/hermes-os:latest          # AMD / Intel
sudo bootc switch ghcr.io/pottrauschen/hermes-os-nvidia:latest   # NVIDIA
sudo reboot
```

After the reboot and the first login, the setup assistant opens: provider (for example
OpenRouter), key and model, or a local model. Details are in the
[setup guide](https://github.com/pottrauschen/hermes-os/blob/main/docs/einrichtung.md),
day-to-day use in the
[manual](https://github.com/pottrauschen/hermes-os/blob/main/docs/handbuch.md).

To go back to the previous system: `sudo bootc rollback`, then reboot.

### What is missing

- **No real hardware:** hermes-os has so far run only in a virtual machine
  (Proxmox), not yet on real hardware.
- **Not signed:** The hermes-os image itself is not signed yet. The signature of the
  Aurora base image is verified before every CI build.
- **English only in part:** In an English session, the setup assistant, the dashboard,
  the morning report, messages on the Library page and error texts from the gateway
  still show German. The agent's windows exist in German and English only.
- **Not everything tried in daily use:** Speaking and reading aloud are untested in a
  real session; the test VM has no microphone. Morning report, dashboard window,
  approvals and the Log ran in the test VM in individual checks, not yet in daily use.
- **Phase 3 is a plan:** Hermes clicking and typing by itself (AT-SPI, based on
  agent-cu) exists only as a
  [plan](https://github.com/pottrauschen/hermes-os/blob/main/docs/phase3-desktop.md).
- **The boundary recognises commands, not effects:** It does not see what a script or
  `python3 -c` does inside. The actual barrier against system changes is that the user
  has no root without a password; the boundary makes sure Hermes asks before it tries.
  Details under
  [The boundary](https://github.com/pottrauschen/hermes-os/blob/main/docs/grenze.md).

### Credits and license

hermes-os is built on [Hermes Agent](https://github.com/NousResearch/hermes-agent)
by Nous Research (MIT) and [Aurora](https://getaurora.dev) by Universal Blue
(Apache 2.0). Hermes Agent is Nous Research's project; hermes-os brings it to the
desktop as part of the system.

hermes-os is licensed under the MIT license, © 2026 pottrauschen.
