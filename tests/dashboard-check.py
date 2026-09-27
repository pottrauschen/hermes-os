#!/usr/bin/python3
# =============================================================================
# hermes-os -- Dashboard-Fenster: Start- und Stopp-Logik gegen Attrappen prüfen
# =============================================================================
# dashboard/dashboard_server.py startet und beendet den Server hinter dem
# Fenster /usr/libexec/hermes-os-dashboard. Hier läuft es gegen Attrappen:
# ein nachgebautes `hermes`, das sich wie `hermes dashboard` von 0.21.x
# verhält (READY-Zeile auf stdout, /api/health, Exit 75 bei belegtem Port,
# „already running“ mit Exit 0, Exit 1 ohne Frontend), dazu ein nachgebautes
# `systemd-run --scope` und `systemctl --user stop`, die den Scope über eine
# PID-Datei nachstellen. Geprüft wird:
#   1. freier Port: Server wird gestartet, antwortet, Stop beendet ihn
#   2. Dashboard läuft schon: wird genommen, Stop lässt es in Ruhe
#   3. Server stirbt beim Start: Fehler mit Logauszug, nichts zu stoppen
#   4. Port von einem Fremdprozess belegt: Fehler „Port belegt“ (Exit 75)
#   5. „already running“ mit anderer Adresse: die wird übernommen
#   6. ohne User-Manager: direkter Aufruf, Stop per SIGTERM
#   7. Timeout: Server, der nie antwortet, wird als Fehler gemeldet und beendet
# Dazu: Desktop-Datei, Startprogramm (Syntax, --check-Zweig), ujust-Rezept.
#
# Ohne Qt, ohne Netz nach draußen. Läuft mit jedem Python 3.9+:
#   tests/dashboard-check.py [--dashboard-dir DIR] [--launcher DATEI]
#                            [--desktop-file DATEI] [--just-file DATEI]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7h) führt ihn
# im Image-Build aus; Erreichbarkeit gegen das echte `hermes dashboard`
# prüft das Gate dort zusätzlich mit dem Modul selbst.
# =============================================================================
import argparse
import configparser
import ast
import importlib.util
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FAKE_HERMES = r'''#!/usr/bin/python3
"""Attrappe für `hermes dashboard` (Verhalten von Hermes 0.21.x nachgestellt)."""
import json, os, signal, socket, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

mode = os.environ.get("FAKE_HERMES_MODE", "ok")
args = sys.argv[1:]
assert args[0] == "dashboard", args
assert "--no-open" in args and "--skip-build" in args, args
port = int(args[args.index("--port") + 1])
log = open(os.environ["FAKE_HERMES_LOG"], "a")
log.write("argv=%s parent=%s\n" % (json.dumps(args), os.environ.get("HERMES_PARENT_PID", "")))
log.flush()

if mode == "crash":
    print("Frontend not built: hermes_cli/web_dist/index.html missing")
    sys.exit(1)
if mode == "attach":
    print("Hermes dashboard already running at %s" % os.environ["FAKE_ATTACH_URL"])
    sys.exit(0)
if mode == "silent":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    time.sleep(120)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        if self.path == "/api/health":
            body = json.dumps({"ok": True, "version": "0.21.5 (Attrappe)", "auth_required": False}).encode()
            ctype = "application/json"
        else:
            body = b"<!doctype html><title>Hermes Agent - Dashboard</title><script>window.__HERMES_SESSION_TOKEN__=\"x\"</script>"
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

try:
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
except OSError:
    print("BACKEND_PORT_IN_USE port=%d" % port)
    sys.exit(75)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
print("HERMES_DASHBOARD_READY port=%d" % port, flush=True)
print("  Hermes Web UI -> http://127.0.0.1:%d" % port, flush=True)
try:
    srv.serve_forever()
finally:
    srv.server_close()
'''

FAKE_SYSTEMD_RUN = r'''#!/usr/bin/python3
"""Attrappe für systemd-run --user --scope: merkt sich die PID je Unit, dann exec."""
import os, sys
args = sys.argv[1:]
assert args[:4] == ["--user", "--scope", "--collect", "--quiet"], args
unit = next(a for a in args if a.startswith("--unit=")).split("=", 1)[1]
cmd = args[args.index("--") + 1:]
with open(os.path.join(os.environ["FAKE_UNITS"], unit), "w") as f:
    f.write(str(os.getpid()))
os.execvp(cmd[0], cmd)
'''

FAKE_SYSTEMCTL = r'''#!/usr/bin/python3
"""Attrappe für systemctl --user: stop <unit> (SIGTERM an die PID), is-active."""
import os, signal, sys
args = sys.argv[1:]
assert args[0] == "--user", args
if args[1] == "stop":
    p = os.path.join(os.environ["FAKE_UNITS"], args[2])
    with open(p) as f:
        pid = int(f.read())
    with open(os.path.join(os.environ["FAKE_UNITS"], "stopped"), "a") as f:
        f.write(args[2] + "\n")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    sys.exit(0)
if args[1] == "is-active":
    state = os.environ.get("FAKE_GATEWAY", "inactive")
    print(state)
    sys.exit(0 if state == "active" else 3)
sys.exit(1)
'''

FAILS = []


def ok(msg):
    print(f"  PASS: {msg}")


def fail(msg):
    print(f"  FAIL: {msg}")
    FAILS.append(msg)


def check(cond, msg):
    (ok if cond else fail)(msg)
    return cond


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port_free(port, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.1)
    return False


def load_module(path):
    spec = importlib.util.spec_from_file_location("dashboard_server", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_exec(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def run_logic_checks(ds, tmp):
    bindir = tmp / "bin"
    units = tmp / "units"
    bindir.mkdir()
    units.mkdir()
    hermes = bindir / "hermes"
    write_exec(hermes, FAKE_HERMES)
    write_exec(bindir / "systemd-run", FAKE_SYSTEMD_RUN)
    write_exec(bindir / "systemctl", FAKE_SYSTEMCTL)
    runtime = tmp / "runtime"
    (runtime / "systemd").mkdir(parents=True)
    (runtime / "systemd" / "private").write_text("")
    log = tmp / "hermes.log"
    os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
    os.environ["XDG_RUNTIME_DIR"] = str(runtime)
    os.environ["FAKE_UNITS"] = str(units)
    os.environ["FAKE_HERMES_LOG"] = str(log)
    os.environ["FAKE_HERMES_MODE"] = "ok"

    check(ds.user_manager_available(), "user manager detected via XDG_RUNTIME_DIR/systemd/private")
    os.environ["FAKE_GATEWAY"] = "active"
    check(ds.gateway_active() is True, "gateway_active reads systemctl --user is-active")
    os.environ["FAKE_GATEWAY"] = "inactive"
    check(ds.gateway_active() is False, "gateway_active false when inactive")

    # 1. freier Port: starten, antworten, stoppen
    port = free_port()
    check(not ds.is_up(port), "free port reports no dashboard")
    s = ds.Server(port=port, hermes=str(hermes))
    r = s.ensure(timeout=15)
    check(r.ok and r.started and r.url == f"http://127.0.0.1:{port}", f"started on free port: {r}")
    check(ds.is_up(port), "health answers after start")
    check(bool(s.unit) and (units / s.unit).is_file(), f"server runs in its own scope ({s.unit})")
    check(s.unit.startswith("hermes-os-dashboard-") and s.unit.endswith(".scope"), "scope name pattern")
    check(f"parent={os.getpid()}" in log.read_text(), "HERMES_PARENT_PID points at us")
    unit = s.unit
    check(s.stop(timeout=5), "stop returns True for a server we started")
    check(unit in (units / "stopped").read_text(), "stop goes through systemctl --user stop <scope>")
    check(wait_port_free(port), "port free after stop")
    check(not s.alive() and s.proc is None, "process gone after stop")
    check(s.stop() is False, "second stop is a no-op")

    # 2. Dashboard läuft schon (vom Nutzer gestartet): nehmen, nicht anfassen
    port = free_port()
    foreign = subprocess.Popen([str(hermes), "dashboard", "--no-open", "--skip-build", "--port", str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not ds.is_up(port) and time.monotonic() < deadline:
            time.sleep(0.1)
        check(ds.is_up(port), "foreign dashboard is up")
        s = ds.Server(port=port, hermes=str(hermes))
        r = s.ensure(timeout=5)
        check(r.ok and not r.started and r.url == f"http://127.0.0.1:{port}", f"existing dashboard reused: {r}")
        check(s.stop() is False and foreign.poll() is None and ds.is_up(port), "stop leaves a foreign dashboard alone")
    finally:
        foreign.terminate()
        foreign.wait(5)

    # 3. Server stirbt beim Start
    os.environ["FAKE_HERMES_MODE"] = "crash"
    port = free_port()
    s = ds.Server(port=port, hermes=str(hermes))
    r = s.ensure(timeout=10)
    check(not r.ok and not r.started and "Exit 1" in r.message, f"crash reported: {r}")
    check(any("Frontend not built" in line for line in r.log), "log excerpt carries the cause")
    check(s.stop() is False, "nothing to stop after a crash")

    # 4. Port belegt durch Fremdprozess (antwortet nicht auf /api/health)
    os.environ["FAKE_HERMES_MODE"] = "ok"
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    try:
        check(ds.port_in_use(port) and not ds.is_up(port), "blocked port: in use, but no dashboard")
        s = ds.Server(port=port, hermes=str(hermes))
        r = s.ensure(timeout=10)
        check(not r.ok and "belegt" in r.message and str(port) in r.message, f"port in use reported: {r}")
    finally:
        blocker.close()

    # 5. „already running“ mit anderer Adresse
    port_other = free_port()
    other = subprocess.Popen([str(hermes), "dashboard", "--no-open", "--skip-build", "--port", str(port_other)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not ds.is_up(port_other) and time.monotonic() < deadline:
            time.sleep(0.1)
        os.environ["FAKE_HERMES_MODE"] = "attach"
        os.environ["FAKE_ATTACH_URL"] = f"http://127.0.0.1:{port_other}/"
        port = free_port()
        s = ds.Server(port=port, hermes=str(hermes))
        r = s.ensure(timeout=10)
        check(r.ok and not r.started and r.url.startswith(f"http://127.0.0.1:{port_other}"),
              f"attached to the running instance on its port: {r}")
        check(s.stop() is False and other.poll() is None, "attached instance is not stopped")
    finally:
        other.terminate()
        other.wait(5)
    os.environ.pop("FAKE_ATTACH_URL", None)

    # 6. ohne User-Manager: direkter Aufruf, SIGTERM
    os.environ["FAKE_HERMES_MODE"] = "ok"
    port = free_port()
    s = ds.Server(port=port, hermes=str(hermes), use_systemd=False)
    check(s.argv()[0] == str(hermes), "without user manager: plain hermes call")
    r = s.ensure(timeout=15)
    check(r.ok and r.started and not s.unit, f"started without scope: {r}")
    check(s.stop(timeout=5) and wait_port_free(port), "stopped via SIGTERM")

    # 7. Server, der nie antwortet
    os.environ["FAKE_HERMES_MODE"] = "silent"
    port = free_port()
    s = ds.Server(port=port, hermes=str(hermes), use_systemd=False)
    t0 = time.monotonic()
    r = s.ensure(timeout=2)
    check(not r.ok and "antwortet nicht" in r.message and time.monotonic() - t0 < 6, f"timeout reported: {r}")
    check(s.alive(), "silent server still alive after timeout (caller decides)")
    r = s.ensure(timeout=1)
    check(not r.ok and s.alive() and len([ln for ln in log.read_text().splitlines() if str(port) in ln]) == 1,
          "retry while our server is still up does not start a second one")
    check(s.stop(timeout=5) and not s.alive(), "silent server stopped")


def check_desktop_file(path, launcher):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    if not check(cp.has_section("Desktop Entry"), f"{path}: [Desktop Entry]"):
        return
    d = cp["Desktop Entry"]
    check(d.get("Type") == "Application", "desktop: Type=Application")
    check(d.get("Exec") == launcher, f"desktop: Exec={launcher}")
    check(bool(d.get("Name")), "desktop: Name")
    check(bool(d.get("Icon")), "desktop: Icon")
    check(d.get("Terminal", "false") == "false", "desktop: Terminal=false")
    check(d.get("Categories", "").endswith(";"), "desktop: Categories ends with ;")


def check_launcher(path):
    src = Path(path).read_text(encoding="utf-8")
    try:
        ast.parse(src, path)
        ok("launcher parses")
    except SyntaxError as e:
        fail(f"launcher syntax: {e}")
        return
    check('"--check"' in src and '"--status"' in src, "launcher handles --check and --status")
    check("QtWebEngineWidgets" in src and "dashboard_server" in src, "launcher uses QtWebEngine and the server module")
    check("server.stop()" in src and "aboutToQuit" in src, "launcher stops the server on quit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-dir", default=os.environ.get("HERMES_OS_DASHBOARD_DIR", "/usr/share/hermes-os/dashboard"))
    ap.add_argument("--launcher", default="/usr/libexec/hermes-os-dashboard")
    ap.add_argument("--desktop-file", default="/usr/share/applications/hermes-os-dashboard.desktop")
    ap.add_argument("--just-file", default="")
    args = ap.parse_args()

    module = os.path.join(args.dashboard_dir, "dashboard_server.py")
    if not os.path.isfile(module):
        print(f"FEHL  {module} fehlt")
        return 1
    ds = load_module(module)

    print("=== dashboard server logic against fakes ===")
    saved_env = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="hermes-dash-") as tmp:
        try:
            run_logic_checks(ds, Path(tmp))
        finally:
            os.environ.clear()
            os.environ.update(saved_env)

    print("=== files ===")
    if os.path.isfile(args.launcher):
        check_launcher(args.launcher)
    else:
        fail(f"{args.launcher} fehlt")
    if os.path.isfile(args.desktop_file):
        check_desktop_file(args.desktop_file, "/usr/libexec/hermes-os-dashboard")
    else:
        fail(f"{args.desktop_file} fehlt")
    if args.just_file:
        text = Path(args.just_file).read_text(encoding="utf-8") if os.path.isfile(args.just_file) else ""
        check("\nhermes-dashboard:\n" in text, "ujust recipe hermes-dashboard present")

    if FAILS:
        print(f"=== {len(FAILS)} check(s) FAILED ===")
        return 1
    print("=== dashboard check OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
