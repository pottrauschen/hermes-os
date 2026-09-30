# Dashboard: Hermes' web interface in a window

As of 2026-09-27. With `hermes dashboard`, Hermes ships its own web
interface: models and keys, sessions, cron, plugins, skills, environment
variables, system status. In hermes-os it is built into the image and opens
as a window, because the image contains no browser. Built, passed
`make lint` and the test against stubs; the frontend was built locally with
Node 22; the window was driven offscreen with real QtWebEngine against the
real `hermes dashboard`; the gate repeats both in the image build. On
2026-09-27 the window ran in a one-off check in the Plasma session of
VM 112, not yet in daily use (see [Testing](#testing)).

## What it does

- **The menu entry “Hermes Dashboard”** (German default: „Hermes-Dashboard“),
  “Open dashboard” in the tray icon's menu (German default:
  „Dashboard öffnen“), the “Open dashboard” button on the final page of the
  setup assistant (German label: „Dashboard öffnen“), `ujust hermes-dashboard`:
  all of them start `/usr/libexec/hermes-os-dashboard`.
- The window checks whether a dashboard already answers on `127.0.0.1:9119`.
  If so, it shows that one. If not, it starts `hermes dashboard --no-open
  --skip-build --port 9119` from the venv in its own user scope, shows
  “Dashboard starting…” (German label: „Dashboard startet…“) and loads the
  page as soon as `/api/health` answers.
- On close it stops the server, but only if it started the server itself. A
  dashboard that someone started in a terminal keeps running. If the window
  dies hard, Hermes' own parent watchdog (`HERMES_PARENT_PID`) stops the
  server on its own.
- If the server does not come up, or the page drops out, an error page
  appears with the cause, the last lines of server output, the gateway's state
  and a “Retry” button (German label: „Erneut versuchen“). The toolbar has
  “Back” and “Reload” (German labels: „Zurück“, „Neu laden“).

On loopback the dashboard needs no login: on every start Hermes puts a
session token into the `index.html` it serves, and the auth gate with its
login page only applies when the server binds to a different address.

## Files

| What | Where |
|---|---|
| Node stage `webbuild`, builds the frontend | `Dockerfile`, `Dockerfile.nvidia` (identical except for the Aurora line) |
| Put the frontend into the Hermes installation, make sure PySide6 is present | `files/scripts/15-dashboard.sh` |
| Window (PySide6, QtWebEngine) | `files/system/usr/libexec/hermes-os-dashboard` |
| Start, check and stop the server (without Qt) | `files/system/usr/share/hermes-os/dashboard/dashboard_server.py` |
| Menu entry | `files/system/usr/share/applications/hermes-os-dashboard.desktop` |
| ujust recipe `hermes-dashboard` | `files/system/usr/share/hermes-os/hermes-os.just` |
| `HERMES_WEB_DIST` for the launcher and the units | `files/scripts/10-hermes.sh`, `files/system/usr/lib/environment.d/60-hermes-os.conf` |
| Test against stubs | `tests/dashboard-check.py` |
| Window offscreen against the real server | `tests/dashboard-gui-check.py` |
| Gate | `files/scripts/80-validate.sh`, section 7l |

In the image: `/usr/lib/hermes-agent/hermes_cli/web_dist` (frontend with the
stamp `.hermes-os-web`), `/usr/libexec/hermes-os-dashboard`,
`/usr/share/hermes-os/dashboard/dashboard_server.py`.

## How Hermes builds and starts the dashboard

From the source of Hermes 0.21.5 (tag v2026.9.24), as of 2026-09-26:

- **Frontend**: `web/` in the Hermes repo, React with Vite, workspace `web` of
  the root `package.json` (plus `apps/shared` as a `file:` dependency). Hermes
  pins Node 26 (`.nvmrc`); `engines` allows `^22.22.0 || ^24.11.0 ||
  >=26`. Build: `npm ci --workspace web`, then `npm run build --workspace
  web` (`tsc -b && vite build`), output to `hermes_cli/web_dist`
  (`web/vite.config.ts`, `outDir`). Only the npm registry is needed.
- **Server**: `hermes_cli/web_server.py` (FastAPI and uvicorn, both core
  dependencies of the venv). Default `127.0.0.1:9119`, flags `--port`,
  `--host`, `--no-open`, `--skip-build`, `--isolated`, `--status`, `--stop`.
  It runs in the foreground, prints `HERMES_DASHBOARD_READY port=N` to stdout
  after binding, and SIGTERM stops it cleanly.
- **Build at runtime**: Without `--skip-build` and without `HERMES_WEB_DIST`,
  `hermes dashboard` tries to build the frontend itself with npm whenever the
  stamp `~/.hermes/web-ui-build-stamp.json` is missing, which means on every
  fresh home. With `HERMES_WEB_DIST` (set by the launcher and environment.d) it
  never builds and reports a missing `index.html` as an error. The window
  passes `--skip-build` on top of that. So the server writes nothing under
  `/usr`.
- **Second instance**: If a dashboard of the same user is already running
  (rendezvous file under `~/.local/state/hermes/gateway-locks/`), a second
  start attaches to it, prints “already running” with the address and exits
  with 0. Another process on the port: exit 75. A running dashboard on a
  different port or without a web UI (`hermes serve`): exit 78.
  `dashboard_server.py` handles all three cases.
- **Readiness**: `GET /api/health` answers without a token with
  `{"ok": true, "version": …}`. `--status` always exits with 0 and is
  therefore useless as a check.
- **Gateway**: Not needed for the start. Without a running
  `hermes-gateway.service` the dashboard shows the gateway as off, and cron
  jobs do not run (the gateway ticks them). The chat tab does not depend on
  the gateway; it starts Hermes' TUI as a child process, see Limits.
- **State files**: under `~/.hermes` (logs, skills seed, spawn ledger) and
  `~/.local/state/hermes/`. No PID file.

## Decisions

- **A separate Node stage instead of Node in the build script.** Node and npm
  do not belong in the image. Installing Fedora's `nodejs` in the Aurora stage
  and removing it again would leave dnf traces and dependencies behind, and
  the version would depend on the base image. The `webbuild` stage from
  `docker.io/library/node:26-bookworm-slim` uses Hermes' pinned Node line,
  clones the same release (`HERMES_REF`, now a global ARG before the first
  stage) and passes only `hermes_cli/web_dist` on through the ctx stage. CI
  reads the Aurora line with `grep '^FROM ghcr.io/ublue-os/' | tail -1`; the
  Node line does not get in its way. `make lint` checks that the last FROM
  line is the Aurora base and that both Dockerfiles otherwise stay identical.
- **A window with QWebEngineView and QApplication instead of Kirigami.** A
  browser window needs no Kirigami frame; the widgets variant is the simplest,
  and the tray icon uses QApplication anyway. QtWebEngine has to be imported
  before the QApplication (to share the OpenGL context). A named profile
  (`hermes-os-dashboard`) keeps cookies and localStorage under
  `~/.local/share/hermes-os-dashboard`; a profile without a name would not
  persist.
- **Server in a user scope.** `systemd-run --user --scope --collect --quiet
  --unit=hermes-os-dashboard-<id>.scope`, like `app_launch` in the plugin: the
  server does not belong to the window's cgroup, and `systemctl --user stop`
  stops it together with its child processes. Without a user manager (build
  container) the direct call with SIGTERM remains.
- **Error page when the gateway is off**: The dashboard also runs without the
  gateway. The error page appears when the server itself does not answer, and
  it names the gateway's state as a hint. This is an assumption from the
  brief, because the dashboard does not depend on the gateway.
- **PySide6 with QtWebEngine.** `python3-pyside6` and `qt6-qtwebengine` are
  in the Aurora DX image (a layer of the Kinoite base, as of 44.20260921.0),
  not chosen by Aurora itself. `15-dashboard.sh` makes sure of both with `dnf
  install`, normally a no-op; the import of `PySide6.QtWebEngineWidgets` is
  part of `hermes-os-dashboard --check` and therefore of the gate.

## Testing

Without Qt, without network, against stubs for `hermes`, `systemd-run` and
`systemctl` (runs anywhere with Python 3.9+, also in `make lint`):

```sh
tests/dashboard-check.py --dashboard-dir files/system/usr/share/hermes-os/dashboard \
  --launcher files/system/usr/libexec/hermes-os-dashboard \
  --desktop-file files/system/usr/share/applications/hermes-os-dashboard.desktop \
  --just-file files/system/usr/share/hermes-os/hermes-os.just
```

It checks: start on a free port and stop via the scope, taking over a running
dashboard without stopping it, a crash at start with a log excerpt, a port in
use (exit 75), “already running” with a different address, operation without
a user manager, a timeout without a double start; plus the desktop file, the
launcher and the recipe.

The window itself, offscreen with QtWebEngine against the real
`hermes dashboard` (Chromium's sandbox off for the test only):

```sh
tests/dashboard-gui-check.py --launcher files/system/usr/libexec/hermes-os-dashboard \
  --dashboard-dir files/system/usr/share/hermes-os/dashboard --out /tmp/shots
```

It plays through: waiting page, loaded page with Hermes' title, server
stopped from outside and “Reload” leads to the error page, “Retry” starts it
again, quitting stops it; optionally it saves one PNG per state. Exit 3 means
QtWebEngine does not run in this environment (bindings missing, render
process dies). Ran on 2026-09-26 in the cloud with PySide6 6.11.2 from PyPI
and Hermes 0.21.5 from a locally built venv: all ten steps green, the page
shows Hermes' sidebar (Chat, Sessions, Files, Models, Logs, Cron, Skills,
Plugins, MCP, Channels, Webhooks, Pairing, Profiles, Config, Keys).

In the image build the gate (`80-validate.sh`, 7l) also checks `web_dist`
with a stamp from the same release as the venv, `hermes-os-dashboard
--check` (PySide6 WebEngine, module, frontend), `desktop-file-validate` and
`ujust --list`. It starts the real `hermes dashboard` from the venv
(`/api/health`, `index.html` with the session token, an asset bundle, stop),
checks that nothing new lies under `/usr/lib/hermes-agent` afterwards, and
drives the window offscreen (exit 3 only as a WARN, because Chromium can fail
in a build container).

Build the frontend locally (without Podman, with Node 22.22 or newer):

```sh
git clone --depth 1 --branch v2026.9.24 https://github.com/NousResearch/hermes-agent.git /tmp/hermes
cd /tmp/hermes && npm ci --workspace web && npm run build --workspace web
ls hermes_cli/web_dist/index.html hermes_cli/web_dist/assets
```

Measured on 2026-09-26 with Node 22.22.2 and npm 10.9.7: `npm ci` 12 s
(454 packages), build 21 s, `web_dist` 3.2 MB.

Start it in the test VM from the home, without a new image:

```sh
systemd-run --user --unit hos-dash --collect -p ExitType=cgroup \
  -E HERMES_OS_DASHBOARD_DIR=/tmp/hos/share/hermes-os/dashboard -E HERMES_HOME=/tmp/hos/home \
  /usr/bin/python3 /tmp/hos/libexec/hermes-os-dashboard
```

Ran on 2026-09-27 in VM 112: the window under Wayland with its own scope on
port 9119; closing it ends the scope
(`systemctl --user list-units 'hermes-os-dashboard-*'`); after
`hermes dashboard --stop` from outside, the error page only appears on
reload; “Retry” restarts the server. Still open for VM 112: confirm
Chromium's sandbox under Wayland without special flags, the menu item on the
icon and the button in the setup assistant.

## Limits

- **Chat tab empty.** It starts `hermes --tui` as a child process, which
  needs Node and the TUI bundle; neither is in the image. Without Node, Hermes
  tries to fetch it into `~/.hermes`. Chat works through the tray icon or
  `hermes` in the terminal. Building the TUI would be a second output of the
  same Node stage (`ui-tui`); not decided.
- **One server, several windows.** If someone opens the window twice, the
  second one shows the first one's server. When the first one closes, it
  takes the server with it, and the second lands on the error page at the
  next click; “Retry” starts the server again.
- **Port 9119 is fixed**, it can be overridden with `HERMES_OS_DASHBOARD_PORT`.
- **No icon of its own for the dashboard**, it uses `hermes-os`.

## Pitfalls

- `hermes dashboard --status` always exits with 0; only `/api/health` (or
  `hermes-os-dashboard --status`) tells you whether it is running.
- Without `HERMES_WEB_DIST` and without `--skip-build`, Hermes attempts an npm
  build on every fresh home and aborts with exit 1 when npm is missing.
- Import `QtWebEngineWidgets` before `QApplication`, otherwise you get
  “AA_ShareOpenGLContexts must be set”.
- Chromium's sandbox needs user namespaces; set
  `QTWEBENGINE_DISABLE_SANDBOX=1` in a container test, not in normal use.
- Release the page before the profile (`view.setPage(None)`, `deleteLater`),
  otherwise Qt warns on exit.
- A timeout at start leaves the server running; “Retry” then keeps waiting
  instead of starting a second one (`Server.ensure` checks `alive()`).
