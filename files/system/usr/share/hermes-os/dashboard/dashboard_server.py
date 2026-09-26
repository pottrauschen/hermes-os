#!/usr/bin/python3
# =============================================================================
# hermes-os -- Dashboard-Server starten, prüfen, beenden (ohne Qt)
# =============================================================================
# Das Fenster /usr/libexec/hermes-os-dashboard zeigt Hermes' eigenes
# Web-Dashboard (`hermes dashboard`, FastAPI in der Venv, Frontend aus
# hermes_cli/web_dist). Dieses Modul kümmert sich um den Server dahinter und
# kommt ohne Qt aus, damit tests/dashboard-check.py es überall mit Python
# gegen Attrappen prüfen kann.
#
# Was Hermes 0.21.x (Tag v2026.9.24) dabei tut, aus dem Quelltext:
#   - `hermes dashboard --no-open --skip-build --port N` läuft im Vordergrund,
#     bindet 127.0.0.1:N und meldet auf stdout `HERMES_DASHBOARD_READY port=N`.
#     `--skip-build` und HERMES_WEB_DIST (setzt der Launcher /usr/bin/hermes)
#     verhindern jeden npm-Versuch auf dem read-only /usr.
#   - GET /api/health antwortet ohne Token mit {"ok": true, ...}; auf Loopback
#     braucht die Oberfläche keine Anmeldung, das Sitzungs-Token steckt in der
#     ausgelieferten index.html.
#   - Läuft schon ein Dashboard desselben Nutzers, hängt sich der zweite Start
#     daran, druckt „already running“ mit der Adresse und endet mit Exit 0.
#     Ist der Port von einem fremden Prozess belegt: Exit 75; passt ein
#     laufendes Dashboard nicht zu --port: Exit 78.
#   - SIGTERM beendet den Server sauber. HERMES_PARENT_PID lässt ihn zusätzlich
#     von selbst enden, wenn der Elternprozess (das Fenster) stirbt.
#   - Das Gateway (hermes-gateway.service, API-Server 8642) ist für den Start
#     nicht nötig; ohne Gateway zeigt das Dashboard es als aus, und Cron-Jobs
#     laufen nicht.
#
# Der Server läuft in einem eigenen transienten Scope (systemd-run --user
# --scope, wie app_launch im Plugin): er gehört dann nicht zur cgroup des
# Fensters, und `systemctl --user stop` beendet ihn samt Kindprozessen (der
# Chat-Tab startet PTYs). Ohne User-Manager (Build-Container) bleibt der
# direkte Aufruf. Beendet wird er nur, wenn dieses Modul ihn gestartet hat;
# ein Dashboard, das der Nutzer selbst im Terminal gestartet hat, bleibt.
# =============================================================================
import collections
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import uuid

DEFAULT_PORT = 9119
HERMES = os.environ.get("HERMES_OS_HERMES", "/usr/bin/hermes")
HEALTH_PATH = "/api/health"
GATEWAY_UNIT = "hermes-gateway.service"
READY_RE = re.compile(r"HERMES_DASHBOARD_READY\s+port=(\d+)")
URL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost|\[::1\]):(\d+)\S*")
LOG_LINES = 40


def base_url(port):
    return f"http://127.0.0.1:{int(port)}"


def health(port, timeout=1.0):
    """Antwort von /api/health als dict, None wenn nichts (Passendes) antwortet."""
    try:
        with urllib.request.urlopen(base_url(port) + HEALTH_PATH, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("ok") is True else None


def is_up(port, timeout=1.0):
    return health(port, timeout) is not None


def port_in_use(port):
    """TCP-Port auf 127.0.0.1 belegt (von wem auch immer)?"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def gateway_active():
    """True/False nach systemctl --user, None wenn systemctl nicht antwortet."""
    if shutil.which("systemctl") is None:
        return None
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", GATEWAY_UNIT],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    state = r.stdout.strip()
    if state == "active":
        return True
    if state in ("inactive", "failed", "activating", "deactivating"):
        return False
    return None


def user_manager_available():
    """Ein systemd-User-Manager ist erreichbar (Sitzung), nicht nur das Binary da."""
    if shutil.which("systemd-run") is None:
        return False
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    return bool(runtime) and os.path.exists(os.path.join(runtime, "systemd", "private"))


class Result:
    """Ergebnis von Server.ensure(): ok, Adresse, ob wir gestartet haben, Meldung."""

    def __init__(self, ok, url="", started=False, message="", log=()):
        self.ok = ok
        self.url = url
        self.started = started
        self.message = message
        self.log = list(log)

    def __repr__(self):
        return f"Result(ok={self.ok}, url={self.url!r}, started={self.started}, message={self.message!r})"


class Server:
    """Ein Dashboard-Server: vorhandenen finden oder einen starten, später beenden."""

    def __init__(self, port=DEFAULT_PORT, hermes=None, use_systemd=None, env=None):
        self.port = int(port)
        self.hermes = hermes or HERMES
        self.use_systemd = user_manager_available() if use_systemd is None else bool(use_systemd)
        self.extra_env = dict(env or {})
        self.proc = None
        self.unit = ""
        self.url = ""
        self.started = False
        self.log = collections.deque(maxlen=LOG_LINES)
        self._ready_port = None
        self._ready = threading.Event()
        self._reader = None

    # ---- Start ---------------------------------------------------------------
    def argv(self):
        cmd = [self.hermes, "dashboard", "--no-open", "--skip-build", "--port", str(self.port)]
        if not self.use_systemd:
            return cmd
        self.unit = f"hermes-os-dashboard-{uuid.uuid4().hex[:8]}.scope"
        return ["systemd-run", "--user", "--scope", "--collect", "--quiet",
                f"--unit={self.unit}", "--", *cmd]

    def _env(self):
        env = dict(os.environ)
        env.update(self.extra_env)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # Server endet von selbst, wenn das Fenster stirbt (Hermes' Eltern-Watchdog).
        env["HERMES_PARENT_PID"] = str(os.getpid())
        return env

    def _read(self, stream):
        for raw in stream:
            line = raw.rstrip("\n")
            self.log.append(line)
            m = READY_RE.search(line)
            if m:
                self._ready_port = int(m.group(1))
                self._ready.set()
        stream.close()

    def start(self):
        argv = self.argv()
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, env=self._env(), start_new_session=True)
        self._reader = threading.Thread(target=self._read, args=(self.proc.stdout,), daemon=True)
        self._reader.start()
        self.started = True
        return self.proc

    def ensure(self, timeout=30.0):
        """Läuft ein Dashboard, nimm es; sonst eins starten und auf /api/health warten."""
        if is_up(self.port):
            self.url = base_url(self.port)
            return Result(True, self.url, started=self.started, message="Dashboard läuft bereits")
        if self.alive():
            # Unser Server läuft noch, hat aber beim letzten Mal nicht rechtzeitig
            # geantwortet: nicht doppelt starten, nur weiter warten.
            return self.wait_ready(timeout)
        try:
            self.start()
        except OSError as exc:
            self.started = False
            return Result(False, message=f"Dashboard-Server nicht startbar: {exc}")
        return self.wait_ready(timeout)

    def _existing_url(self):
        """Adresse aus „already running …“ eines Starts, der sich angehängt hat."""
        for line in reversed(self.log):
            if "already running" in line.lower():
                m = URL_RE.search(line)
                if m:
                    return m.group(0).rstrip(".,)"), int(m.group(1))
        # Zeile ohne die Adresse: Vorgabeport prüfen
        return None, None

    def wait_ready(self, timeout=30.0):
        deadline = time.monotonic() + timeout
        while True:
            if self._ready.is_set() and self._ready_port:
                if is_up(self._ready_port):
                    self.port = self._ready_port
                    self.url = base_url(self.port)
                    return Result(True, self.url, started=True, message="Dashboard gestartet", log=self.log)
            rc = self.proc.poll()
            if rc is not None:
                # Der Prozess ist weg: Reader auslaufen lassen, dann Ursache lesen
                if self._reader:
                    self._reader.join(2)
                self.proc = None
                self.started = False
                self.unit = ""
                text = "\n".join(self.log)
                if rc == 0 and "already running" in text.lower():
                    url, port = self._existing_url()
                    port = port or self.port
                    if is_up(port):
                        self.port = port
                        self.url = url or base_url(port)
                        return Result(True, self.url, started=False, message="Dashboard läuft bereits", log=self.log)
                    return Result(False, message="Hermes meldet ein laufendes Dashboard, aber es antwortet nicht.", log=self.log)
                if rc == 75:
                    msg = f"Port {self.port} ist von einem anderen Programm belegt."
                elif rc == 78:
                    msg = "Es läuft schon ein Dashboard mit anderer Adresse oder ohne Oberfläche (hermes serve)."
                else:
                    msg = f"Der Dashboard-Server hat sich beendet (Exit {rc})."
                return Result(False, message=msg, log=self.log)
            if time.monotonic() >= deadline:
                return Result(False, message=f"Der Dashboard-Server antwortet nicht innerhalb von {int(timeout)} s.",
                              log=self.log)
            if is_up(self.port, timeout=0.5):
                self.url = base_url(self.port)
                return Result(True, self.url, started=True, message="Dashboard gestartet", log=self.log)
            self._ready.wait(0.25)

    # ---- Stopp ---------------------------------------------------------------
    def stop(self, timeout=15.0):
        """Nur den Server beenden, den wir gestartet haben; erst sanft, dann hart."""
        proc = self.proc
        if not self.started or proc is None:
            return False
        if proc.poll() is None:
            if self.unit:
                try:
                    subprocess.run(["systemctl", "--user", "stop", self.unit], capture_output=True, timeout=timeout)
                except (OSError, subprocess.SubprocessError):
                    pass
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
            try:
                proc.wait(timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self.proc = None
        self.started = False
        self.unit = ""
        return True

    def alive(self):
        return self.proc is not None and self.proc.poll() is None


def main():
    """Kleiner Selbsttest: Läuft ein Dashboard auf dem Vorgabeport?"""
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    h = health(port)
    if h:
        print(f"Dashboard antwortet auf {base_url(port)}: Hermes {h.get('version', '?')}")
        return 0
    print(f"Kein Dashboard auf {base_url(port)}" + (" (Port belegt)" if port_in_use(port) else ""))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
