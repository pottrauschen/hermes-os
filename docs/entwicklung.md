# Development: working on hermes-os from the workstation

As of 2026-09-29. How hermes-os comes about, from the change on the Windows PC
to the test on the test VM's screen. This page is the entry point; whatever
belongs to a topic is in that topic's own docs (doc map in `CLAUDE.md`).
Status, decisions and open items are not kept in the repo but in the
maintainer's notes.

## Who does what

```
Windows PC            develop: repo, notes, GitHub access
  └ git push main
GitHub Actions        build: both images, gate, tests, push to GHCR (about 30 min)
  └ ghcr.io/pottrauschen/hermes-os, hermes-os-nvidia
Test VM 112           test: bootc upgrade, reboot, at the screen (KVM) or from here
  on the Proxmox host
```

The Windows PC cannot run a VM and cannot build images (no Podman, no Linux).
Images are built only in CI; build VM 110 is needed only for a new disk
([testumgebung.md](testumgebung.md)).

| What | Where |
|---|---|
| Working copy | `C:\Users\<user>\Desktop\hermes-os` (Git Bash or PowerShell) |
| Repo | `github.com/pottrauschen/hermes-os`, branch `main` |
| Images | `ghcr.io/pottrauschen/hermes-os` (AMD/Intel), `…/hermes-os-nvidia` |
| Hermes upstream | `NousResearch/hermes-agent`, pinned through `HERMES_REF` in the Dockerfile |
| Test VM | VM 112, `<user>@<test-vm>`, login with an SSH key |
| Proxmox host | `root@<proxmox-host>` (`qm …`) |

## Repo layout

| Folder, file | Contents |
|---|---|
| `Dockerfile`, `Dockerfile.nvidia` | identical except for the FROM line; a Node stage for the dashboard, then `build.sh` |
| `files/system/` | everything that goes into the image, path by path as in the system |
| `files/scripts/` | build steps `NN-*.sh` in order; `80-validate.sh` is the gate, `89-tests.sh` the tests in the build |
| `tests/` | checks without hardware, mostly Python with mocks; `tests/vm-hilfen.sh` for the VM |
| `docs/` | one page per topic, doc map in `CLAUDE.md` |
| `.github/workflows/build.yml` | the CI build |

The parts of hermes-os and their docs:

| Part | Program, files | Docs |
|---|---|---|
| Setup assistant | `usr/libexec/hermes-os-setup`, `usr/share/hermes-os/setup/` | [einrichtung.md](einrichtung.md) |
| Tray icon and the Kontor (the chat window) | `usr/libexec/hermes-os-tray`, `usr/share/hermes-os/tray/` | [systemagent.md](systemagent.md) |
| KRunner “Ask Hermes” (German default: „Hermes fragen“) | in the tray icon (`tray/runner.py`, `dbus_peer.py`) | [krunner.md](krunner.md) |
| Seeing and hearing | `tray/screenshot.py`, `voice.py`, `voice_worker.py` | [sehen-hoeren.md](sehen-hoeren.md) |
| Dashboard window | `usr/libexec/hermes-os-dashboard`, `usr/share/hermes-os/dashboard/` | [dashboard.md](dashboard.md) |
| Plugin: system knowledge, boundary, log, library, report | `usr/share/hermes-os/plugins/hermes_os/` | [grenze.md](grenze.md), [protokoll.md](protokoll.md), [bibliothek.md](bibliothek.md), [morgenbericht.md](morgenbericht.md) |
| Instructions for Hermes (skill) | `usr/share/hermes-os/skills/hermes-os-system/SKILL.md` | in the skill itself |
| Local model | `usr/libexec/hermes-os-lokal`, `usr/share/hermes-os/local/` | [lokales-modell.md](lokales-modell.md) |
| ujust recipes | `usr/share/hermes-os/hermes-os.just` | [handbuch.md](handbuch.md) |

## How a change goes in

1. **Change** it on the PC.
2. **Check locally** whatever works under Windows (next section): Python
   syntax of all changed files, shell scripts with `sed 's/\r$//' datei | bash -n`.
3. **Try it in the VM** before an image gets built: render interfaces
   offscreen, start programs as a test build from the home directory (sections
   below). That saves the half hour of CI for every attempt.
4. **Commit and push to `main`.** Commit message in German: the reason, what
   changed, how it was checked. Docs and tests go into the same commit as the
   code.
5. **Wait for CI** (`gh run watch`). It builds both variants, runs the gate
   and the tests in the image, and only then pushes.
6. **Update the VM:** `sudo bootc upgrade`, then reboot. Agree on the reboot
   beforehand with whoever is sitting at the VM.
7. **Check on the real screen**, through the KVM switch or from here
   ([testumgebung.md](testumgebung.md), “Operating VM 112 from here”).

## What runs under Windows

Without Qt/Kirigami and without Linux file permissions, some of the tests also
run on the PC; Python is `python3-64.exe`, and output is read with
`PYTHONIOENCODING=utf-8`. Git Bash has no `make`, so run the steps from
`make lint` one by one.

| Runs under Windows | Linux only (VM or build) |
|---|---|
| `tray-client-check.py`, `model-choice-check.py`, `library-check.py`, `boundary-check.py`, `runner-check.py`, `lang-check.py` (the Qt part reports SKIP) | `library2-check.py`, `audit-check.py` (file permissions 0600/0700), `report-check.py` (starts the icon), `dashboard-check.py` (starts the server), `lokales-modell-check.py` (GPU mock with Linux paths), `sehen-hoeren-check.py`, all `*-gui-check.py`, `tray-showcase.py`, `venv-smoke.sh`, `boot-check.sh` |

Whatever fails under Windows runs in the build's gate under Linux, and that is
the result that counts.

The interface is German out of the box and English in an English session
([systemagent.md](systemagent.md), “Interface language”). New visible texts go
into `qsTr()` or `_()` in German and get an entry in the dictionary
(`tray/lang.py`; for the boundary and the log, `plugins/hermes_os/lang.py`);
`lang-check.py` finds what is missing. `audit-check.py`,
`model-choice-check.py`, `runner-check.py` and `sehen-hoeren-check.py` compare
German texts and therefore set `HERMES_OS_LANG=de`, so that they pass in an
English session too.

## Checking interfaces without a screen

The Kontor, the assistant and the dashboard are QML with Kirigami. The render
tests draw them offscreen with mocks instead of the real backend, and every QML
warning counts as an error. They need PySide6 and Kirigami, so they run in the
VM, without disturbing the session there:

```sh
ssh <user>@<test-vm> 'mkdir -p ~/ui-test/qml'
for f in Main.qml chat_text.py; do
  sed 's/\r$//' files/system/usr/share/hermes-os/tray/$f | ssh <user>@<test-vm> "cat > ~/ui-test/qml/$f"
done
sed 's/\r$//' tests/tray-gui-check.py | ssh <user>@<test-vm> 'cat > ~/ui-test/tray-gui-check.py'
ssh <user>@<test-vm> 'cd ~/ui-test && python3 tray-gui-check.py --qml-dir ~/ui-test/qml --out ~/ui-test/bilder'
```

`--out` writes one PNG per step (`tray-streaming.png`, `tray-approval.png`
…). For design work, `tests/tray-showcase.py` draws a realistic-looking
conversation, wide and narrow, plus the greeting in the empty Kontor and the
typing dots at narrow width, with Breeze icons, so that before and after can
be compared; `--image` takes a real screenshot for the user bubble, and
`--prefix` puts something in front of the file name (`vorher-`, `nachher-`).
Both scripts load `chat_text.py` from the folder that holds `Main.qml`; other
changed files of the window (such as `tray/model_choice.py`) belong in the
test folder too. The colors come from the user's `kdeglobals`; for a dark
picture, set a throwaway `XDG_CONFIG_HOME` with a `kdeglobals` made from
`/usr/share/color-schemes/BreezeDark.colors` plus `[General]
ColorScheme=BreezeDark`.

A way of working that has held up: before picture, change, after picture, look
at both, and only then commit.

## Programs as a test build from the home directory

The programs find their modules through environment variables, so that a
changed version can run without touching `/usr`:

| Variable | Purpose |
|---|---|
| `HERMES_OS_TRAY_DIR` | folder with `Main.qml` and the tray icon's modules |
| `HERMES_OS_LOCAL_DIR` | folder with `local_model.py` |
| `HERMES_OS_LIBRARY_PY`, `HERMES_OS_AUDIT_PY` | the plugin's library and log |
| `HERMES_HOME` | the Hermes directory; for experiments a throwaway folder, never `/tmp` across reboots |

The tray icon runs only once per user; a second instance hands over to the
running one. For a test build, quit the running icon first, then start the
build as a user service, so that it outlives the SSH session:

```sh
systemd-run --user -p ExitType=cgroup -E HERMES_OS_TRAY_DIR=$HOME/ui-test/tray \
  python3 $HOME/ui-test/hermes-os-tray
```

`hermes-os-tray --check`, `hermes-os-setup --check` and
`hermes-os-lokal --check` check a build without opening a window.

## Moving Hermes to a new release

A bump is a change of `HERMES_REF` in the `Dockerfile` (both files). Before
it, run `tests/venv-smoke.sh`, `hermes-os-setup --check`,
`tests/setup-gui-check.py`, `tests/tray-client-check.py` and
`tests/dashboard-check.py`, and build the frontend locally
([dashboard.md](dashboard.md)). The assistant's bridge uses internal Hermes
helpers that come with no stability promise, and the tray icon uses the
gateway's runs API; both are the first to break on a bump. How Hermes itself
does something is in the code under `/usr/lib/hermes-agent` in the VM; reading
it is more reliable than guessing, and capturing traffic with a small server
on 127.0.0.1 shows what Hermes really sends to an endpoint.

## Pitfalls on the Windows workstation

- **Line endings:** the working tree is CRLF, the index LF. Before copying
  into the VM, run `sed 's/\r$//'`, and check scripts the same way
  (`| bash -n`).
- **Heredocs with apostrophes** get mangled by the tool's shell layer; write
  such files and commit messages as files and pass them with `git commit -F`.
- **Git Bash rewrites paths:** `gh api /user/…` turns into
  `C:/Program Files/Git/user/…`. Leave out the leading slash.
- **Python writes the code page into pipes**, not UTF-8; tests with umlauts
  need `PYTHONIOENCODING=utf-8` or `reconfigure`.
- **Sudo in the VM** asks for the password: `echo … | sudo -k -S -p ""`, with
  `-k` so that a cached login does not swallow the password line.

## Rules

What gets asked before acting, how secrets are handled and which provider
terms apply is in `CLAUDE.md` under “Working rules”. No session knowledge as
files in the repo; handovers and dated findings belong in the maintainer's notes.
