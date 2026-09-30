# hermes-os

An atomic desktop Linux with an AI agent as part of the system. The base is
[Aurora DX](https://getaurora.dev) (Universal Blue, Fedora bootc, KDE Plasma on Wayland). The
agent is [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research, pinned
to one release and baked into the image.

hermes-os is a working title. It leans on Hermes Agent and can read as a Nous Research product,
which it is not. A new name is planned for 0.2, picked from the replies to the video post: the
best suggestion, not the most liked. The name sits in `.github/workflows/build.yml`
(`IMAGE_BASENAME`), `Dockerfile` and `Dockerfile.nvidia` (`ARG IMAGE_NAME`, `LABEL title`),
the `Makefile` (`IMAGE_NAME`) and in file and path names under `/usr` (`hermes-os-*`).

## Try it

From an existing bootc system (Aurora, Bluefin, Silverblue, Kinoite):

```sh
sudo bootc switch ghcr.io/pottrauschen/hermes-os:latest          # AMD / Intel
sudo bootc switch ghcr.io/pottrauschen/hermes-os-nvidia:latest   # NVIDIA
sudo reboot
```

At the first login a setup assistant opens. You pick a provider from Hermes' catalogue (for
example OpenRouter), enter your key, which it checks, and choose a model, or set up a local
model instead. Later it is “Set up Hermes” in the menu (German default: „Hermes einrichten“) or
`ujust hermes-setup`. Details: [docs/einrichtung.md](docs/einrichtung.md).

The image ships German defaults: system locale, keyboard, Plasma language, time zone
Europe/Berlin, all changeable in System Settings. In an English session (the first of
`LANGUAGE`, `LC_ALL`, `LC_MESSAGES` and `LANG` that is set starts with `en`, or
`HERMES_OS_LANG=en`) the Kontor (the chat window), tray menu, notifications, approvals, library
and log are in English. The setup assistant, dashboard and morning report are still German, and
so are messages on the Library page and error texts from the gateway.

To undo an update: `sudo bootc rollback`, then reboot. There is no `ujust rollback`, and
`ujust rebase-helper` switches to upstream Aurora, which is wrong here.

## What it does

The status column comes from the test VM. *seen* means in use in its Plasma session, *tried*
means it ran there in individual checks but not in daily use, *built* means it is in the
image with tests passing but has not run in a session.

| What | How | Status |
|---|---|---|
| Tray icon: grey while the gateway is off, blue when ready, orange while working, yellow when it needs an approval | appears at login | seen |
| The Kontor: chat with images in and out (file, Ctrl+V, drag and drop) and a picker for model and reasoning effort | click the icon or Meta+H | seen |
| Ask from KRunner. Enter opens the Kontor with the question; “Look up only” (German default: „Nur nachschlagen“) answers as a notification | Alt+Space, then `hermes <question>` or `h: <question>` | seen |
| “What am I looking at?” (German default: „Was sehe ich hier?“): select a screen region and Hermes explains it | Meta+Shift+H | seen |
| Approvals: dangerous commands ask first, with a box in the Kontor and a KDE notification (allow once, this session, always, deny). Unanswered after five minutes, the command does not run | ask for a system update | tried |
| The log: approvals with the decision, system commands with the result, app launches, with filter and export | clock button in the Kontor | tried |
| Reboot and shutdown are refused outright, even with sudo. Hermes asks you to do that | ask for a reboot | tried: Hermes refused and asked the user; the block with sudo is covered by the boundary tests |
| Hermes knows its own system: image, services, apps, hardware, network, journal, updates, language and keyboard, read-only and without root | ask in the Kontor | seen |
| Apps start on request | ask in the Kontor | built |
| Local model on your own GPU. Ollama is loaded into your home, it is not in the image. The default for 12 GB is `qwen3.5:9b`; small models stay weaker than cloud models | card in the setup assistant, `ujust hermes-lokal-ein` | tried on an RTX 3060 with CUDA, not yet on AMD |
| Voice: speak, and the answer is read aloud. Recognition (faster-whisper) and speech (piper) run locally | hold Meta+Space; in a terminal `hermes`, then `/voice on` | built, tests without hardware pass, untested in a session: the test VM has no microphone |
| Library: web addresses, files and folders that Hermes reads when needed and cites. Entries can be mirrored with full-text search (SQLite FTS5); the doc servers context7 and deepwiki are switches | “Library” in the Kontor (German default: „Bibliothek“) | seen |
| Morning report: once a day a notification on updates, new journal errors, disk space and services, with a button that opens it in the Kontor | `ujust hermes-morgenbericht-ein` | tried |
| Hermes' own web dashboard in a window: models, keys, sessions, cron, plugins, skills, environment. Its chat tab stays empty because the Hermes TUI is not built | menu, tray icon, `ujust hermes-dashboard` | tried |
| From Hermes itself: checkpoints before writes, patches and destructive shell commands allow undo in project files; the gateway serves messaging platforms, cron and voice messages | `ujust hermes-gateway-enable` | Hermes features: checkpoints on, gateway configured |
| Clicking, typing and reading widgets through AT-SPI, based on agent-cu | not available | plan for phase 3 |

## The boundary

Hermes works freely in your home, in containers and Flatpak, starts apps, uses `systemctl --user`
and runs read-only commands, even with sudo. It asks first for bootc, rpm-ostree, `ujust update`,
system services, `/etc`, `/usr`, the firewall, users, sudo beyond pure reads, root shells,
partitions and system-wide language and keyboard (`localectl set-*`). Reboot and shutdown are
blocked outright.

This is a system boundary, not a data boundary. User units, autostart and network access in
the home stay open (Hermes' own detector still asks before writing to `~/.ssh`). The real barrier is that the user has no root without a password;
the boundary makes Hermes ask before it tries. It recognises commands, not effects: what a
script or `python3 -c` does inside, it cannot see.

Three places enforce it: a section of the system prompt, `approvals.smart_policy` for what
Hermes' own detector flags, and a `pre_tool_call` hook in `plugins/hermes_os/boundary.py`. The
hook parses each command like a shell, unwraps `sh -c`, `xargs`, `find -exec`,
`flatpak-spawn --host` and other wrappers, and sends matches to Hermes' approval dialog. With
no human there the answer is no; if the check itself fails, it asks. `tests/boundary-check.py`
runs 211 cases: 125 asked or refused, 86 free. Details and known gaps:
[docs/grenze.md](docs/grenze.md).

## How it is built

```
Base image (Aurora DX)          /usr, read-only, bootc, rollback
  + Hermes v2026.9.24 (0.21.5)  /usr/lib/hermes-agent, own Python 3.13 venv (uv), precompiled
  + Local model, optional       user service ollama.service; Ollama 0.34.4 not in the image
  + Agent layer                 /usr/share/hermes-os: plugin, skill, config template, ujust recipes
  + Setup, tray, dashboard      /usr/libexec/hermes-os-setup, -tray, -dashboard (Kirigami, QtWebEngine, PySide6)
  + Service                     hermes-gateway.service (user unit, bound to graphical-session), API on 127.0.0.1:8642
User data                       ~/.hermes: config, sessions, memory, checkpoints, lazy-packages
Apps                            Flatpak
Development                     Distrobox / Podman
```

Four layers, four update cycles. Hermes only changes with a new image: the launcher catches
`hermes update` and points to `ujust update`, and Hermes itself refuses with exit 2. Backends
that Hermes loads on first use go to `~/.hermes/lazy-packages`, never into the read-only venv.
CI rebuilds both images on every push to `main` that changes the image (pushes touching only
docs, tests, README or LICENSE are skipped) and every Monday, and pushes them to ghcr.io.
Before every CI build, the Aurora base image signature is checked against `aurora-cosign.pub`.

## Status

- Both images build in CI, on Aurora with Fedora 44. The build checks that Hermes 0.21.5 starts
  from the read-only venv, the plugin loads, the approval hook fires, `hermes update` refuses
  and `ujust --list` shows the recipes. The Hermes tree in the image is about 1 GB.
- First boot on 2026-09-26, in a Proxmox VM. It has not run on real hardware yet.
- The image is not signed yet; that waits for the secret `SIGNING_SECRET` and a `cosign.pub`.
- A multi-stage review (five investigators, one sceptic each) raised 51 findings before the
  first boot: 31 confirmed and fixed, 20 rejected.

## Building it yourself

Locally, with Podman on Linux: `make lint` checks syntax anywhere, `make image` builds for
AMD/Intel, `make image VARIANT=nvidia` for NVIDIA, and `make qcow2 && make run-qemu-qcow`
boots a disk image in QEMU. A Hermes bump is a change of `HERMES_REF` in `Dockerfile`, `Dockerfile.nvidia` and the `Makefile`. An
image pushed by Actions starts out private; make the package public before switching to it.
The workflow is in [docs/entwicklung.md](docs/entwicklung.md), the test VM in
[docs/testumgebung.md](docs/testumgebung.md).

## Documentation

- [docs/handbuch.md](docs/handbuch.md): using hermes-os, shortcuts, commands, troubleshooting.
- [docs/einrichtung.md](docs/einrichtung.md): the setup assistant and what it writes.
- [docs/systemagent.md](docs/systemagent.md): tray icon and Kontor, approvals, UI language.
- [docs/krunner.md](docs/krunner.md): asking Hermes from KRunner.
- [docs/sehen-hoeren.md](docs/sehen-hoeren.md): screen regions and push-to-talk.
- [docs/grenze.md](docs/grenze.md): the boundary, what asks and what runs freely.
- [docs/protokoll.md](docs/protokoll.md): the log of what Hermes did to the system.
- [docs/bibliothek.md](docs/bibliothek.md): the library Hermes reads and cites.
- [docs/morgenbericht.md](docs/morgenbericht.md): the daily morning report.
- [docs/dashboard.md](docs/dashboard.md): Hermes' web dashboard as a window.
- [docs/lokales-modell.md](docs/lokales-modell.md): a local model on your own GPU.
- [docs/phase3-desktop.md](docs/phase3-desktop.md): the plan for desktop control (phase 3).
- [docs/entwicklung.md](docs/entwicklung.md): how hermes-os is developed, built and tested.
- [docs/testumgebung.md](docs/testumgebung.md): building a disk image and booting it in a VM.
- [docs/release-notes.md](docs/release-notes.md): notes per release.

## License

MIT, © 2026 pottrauschen, see [LICENSE](LICENSE). Hermes Agent is MIT (Nous Research). Aurora
is Apache 2.0 (Universal Blue).

Built on Hermes Agent by Nous Research.
