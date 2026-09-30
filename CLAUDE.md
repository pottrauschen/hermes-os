# hermes-os — working rules and doc map

Atomic KDE Linux (Aurora DX, Fedora bootc, Wayland) with Hermes Agent as part
of the system. What it is and how to build it is in `README.md`. Status,
decisions, open items and pitfalls are kept outside the repo, in the
maintainer's notes.

## Doc map

| File | Purpose |
|---|---|
| `README.md` | What the system does, structure, the boundary, building, first login, status |
| `CLAUDE.md` | this file: working rules and doc map |
| `docs/handbuch.md` | for users: first start, the Kontor (the chat window), shortcuts, approvals, Library, morning report, updates and rollback, ujust commands, when something does not work |
| `docs/release-notes.md` | release notes per version, newest first; 0.1: what hermes-os is, what is in it, installation via `bootc switch`, what is missing, credits and license |
| `docs/entwicklung.md` | entry point for developers: who does what (PC, CI, VM), repo layout, how a change goes through, what runs under Windows, checking interfaces offscreen, test builds from the home directory, Hermes bump, pitfalls on the Windows workstation |
| `docs/testumgebung.md` | building and booting in the homelab: build VM 110, test VM 112, import, GPU passthrough, driving VM 112 from here (`tests/vm-hilfen.sh`), pitfalls, measurements, boot checklist |
| `docs/einrichtung.md` | setup assistant, bridge into the Hermes venv, the subscription question |
| `docs/dashboard.md` | dashboard: Node stage and `15-dashboard.sh`, window `hermes-os-dashboard` with `dashboard_server.py`, starting and stopping the server, gate, tests, limits, pitfalls |
| `docs/systemagent.md` | tray icon: states, the Kontor, images in and out, channel to the gateway's API server, approvals, interface language (German out of the box, English via locale or `HERMES_OS_LANG`), tests, pitfalls |
| `docs/morgenbericht.md` | morning report: daily cron job without a model, `os_report` and `desktop_notify`, button “Discuss in chat” (German default: „Im Chat besprechen“), ujust recipes, pitfalls |
| `docs/bibliothek.md` | Library: knowledge sources in the Kontor, storage, tools `library_list`, `library_fetch`, `library_search`, `library_mirror`, mirror and index with FTS5, docs server switch (MCP), limits, pitfalls |
| `docs/lokales-modell.md` | local model, optional: Ollama not in the image, downloaded into the home directory with a checksum, user service, connection to Hermes (custom, 64k context), model choice for 12 GB, recipes, card in the setup assistant, test in VM 112 |
| `docs/grenze.md` | the boundary: hook contract according to Hermes upstream, what Hermes catches itself, what the hook catches, allowlist, remaining gaps |
| `docs/protokoll.md` | Log: page in the Kontor showing what Hermes did to the system; storage `audit.jsonl`, hooks, deciders, limits |
| `docs/krunner.md` | KRunner runner “Ask Hermes” (German default: „Hermes fragen“): `hermes <question>` and `h: <question>`, D-Bus connection in the tray icon, “Look up only” (German default: „Nur nachschlagen“), test, pitfalls |
| `docs/phase3-desktop.md` | phase 3, desktop control based on agent-cu |
| `docs/sehen-hoeren.md` | seeing and hearing: “What am I looking at?” (German default: „Was sehe ich hier?“; Meta+Shift+H, screen region to Hermes) and push-to-talk (Meta+Space, faster-whisper and Piper from the Hermes venv), visual check after desktop changes (Spectacle and `vision_analyze`), shortcuts, tests, pitfalls |
| `files/system/usr/share/hermes-os/skills/hermes-os-system/SKILL.md` | skill for the agent, copied into the image; not project documentation, exception in `.doku-check-ignore` |

## Working rules

- **How a change goes through:** `make lint` locally, commit, push to `main`.
  CI builds both variants with the validation gate (`files/scripts/80-validate.sh`)
  and tests (`files/scripts/89-tests.sh`). Booting happens only in the homelab,
  following `docs/testumgebung.md`; the Windows PC cannot run a VM.
- **What goes into the image lives under `files/system/`**, build steps
  numbered under `files/scripts/`. Both Dockerfiles stay identical except for
  the FROM line; `make lint` checks this.
- **Hermes is pinned** (`HERMES_REF` in the Dockerfile, 0.21.x line). Before a
  bump, run `tests/venv-smoke.sh`, `hermes-os-setup --check`,
  `tests/setup-gui-check.py`, `tests/tray-client-check.py` and
  `tests/dashboard-check.py`, and build the frontend locally
  (`docs/dashboard.md`);
  the setup assistant's bridge uses internal Hermes helpers with no
  stability promise, the tray icon uses the gateway's runs API.
- **Testing the setup assistant and the tray icon without a new image:**
  `tests/setup-gui-check.py` and `tests/tray-gui-check.py` render offscreen,
  and every QML warning is a failure; `tests/dashboard-gui-check.py` runs the
  dashboard window offscreen against the real server; `tests/tray-client-check.py`
  and `tests/dashboard-check.py` run anywhere with Python. In the VM, start a test build from the home directory
  (`systemd-run --user … -p ExitType=cgroup`) with `HERMES_HOME` pointing to a
  throwaway directory; `/tmp` is empty after every reboot.
- **Windows workstation:** working tree CRLF, index LF. Before transferring
  files to the VM, run `sed 's/\r$//'`; check scripts with `sed 's/\r$//' | bash -n`;
  do not write files containing apostrophes via heredoc.
- **Ask first** before touching VMs of other projects, restarting or
  stopping VMs, putting secrets in files
  (`disk.local.toml` is ignored, `disk.toml` is only a template), and before
  anything that touches providers' terms.
- **Exception VM 110 (ainux-build):** The maintainer cleared it for
  hermes-os on 2026-09-30; it may be rebuilt, started and stopped without
  asking. ainux has no other VM in the homelab.
- **No session knowledge as files.** Handoffs, findings and dated plans
  belong in the Brain; the repo keeps what belongs to the code and is
  maintained.
