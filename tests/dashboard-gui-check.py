#!/usr/bin/python3
# =============================================================================
# hermes-os -- Dashboard-Fenster offscreen fahren (ohne Display)
# =============================================================================
# Lädt /usr/libexec/hermes-os-dashboard als Modul, baut das Fenster mit
# QtWebEngine offscreen und spielt den Ablauf durch: Server starten (echtes
# `hermes dashboard`, oder eine Attrappe über HERMES_OS_HERMES), Seite lädt
# und trägt Hermes' Titel; Server von außen beenden, Neu laden führt zur
# Fehlerseite; „Erneut versuchen" startet ihn wieder; Beenden stoppt ihn.
# Optional ein PNG je Zustand.
#
# Aufruf:
#   tests/dashboard-gui-check.py [--launcher DATEI] [--dashboard-dir DIR]
#                                [--port N] [--timeout S] [--out DIR]
# Exit 0 = alles sauber, 1 = Fehler, 3 = QtWebEngine hier nicht lauffähig
# (Bindings fehlen oder der Render-Prozess stirbt): das Gate meldet 3 nur
# als WARN, weil Chromium in einem Build-Container ohne /dev/shm oder
# Namespaces scheitern kann, ohne dass am Fenster etwas falsch wäre.
# Chromiums Sandbox wird für den Test abgeschaltet, im Betrieb nicht.
# =============================================================================
import argparse
import importlib.util
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox --disable-dev-shm-usage")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

FAILS = []


def ok(msg):
    print(f"  PASS: {msg}")


def fail(msg):
    print(f"  FAIL: {msg}")
    FAILS.append(msg)


def check(cond, msg):
    (ok if cond else fail)(msg)
    return cond


def load_launcher(path):
    # Das Startprogramm hat keine .py-Endung, deshalb der Loader ausdrücklich.
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_file_location("hermes_os_dashboard", path,
                                                  loader=SourceFileLoader("hermes_os_dashboard", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--launcher", default="/usr/libexec/hermes-os-dashboard")
    ap.add_argument("--dashboard-dir", default=os.environ.get("HERMES_OS_DASHBOARD_DIR", "/usr/share/hermes-os/dashboard"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("HERMES_OS_DASHBOARD_PORT", "9119")))
    ap.add_argument("--timeout", type=float, default=90.0, help="Sekunden bis die Seite geladen sein muss")
    ap.add_argument("--out", default="", help="PNG je Zustand hierhin (optional)")
    args = ap.parse_args()
    os.environ["HERMES_OS_DASHBOARD_DIR"] = args.dashboard_dir

    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401  (vor der QApplication)
        from PySide6.QtCore import QTimer, QEventLoop
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"WARN  QtWebEngine nicht ladbar: {exc}")
        return 3

    launcher = load_launcher(args.launcher)
    if launcher.ds is None:
        print(f"FEHL  {launcher._SERVER_IMPORT_ERROR}")
        return 1
    ds = launcher.ds

    QApplication.setApplicationName("hermes-os-dashboard-check")
    app = QApplication(sys.argv)
    server = ds.Server(port=args.port)
    win = launcher.Window(app, server, start_timeout=args.timeout)
    crashed = []
    win.page.renderProcessTerminated.connect(lambda status, code: crashed.append((status, code)))
    win.window.show()

    def pump(seconds):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()

    def wait_until(pred, timeout, step=0.25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return True
            pump(step)
        return pred()

    def shot(name):
        if not args.out:
            return
        os.makedirs(args.out, exist_ok=True)
        img = win.view.grab().toImage()
        img.save(os.path.join(args.out, f"dashboard-{name}.png"))

    def page_state():
        return win.view.url().toString(), win.view.title()

    # 1. Start: Warteseite, dann die echte Seite mit Hermes' Titel
    win.start_server()
    pump(0.5)
    check(page_state()[0].startswith("hermes-os://waiting"), f"waiting page shown first: {page_state()}")
    loaded = wait_until(lambda: page_state()[0].startswith("http://127.0.0.1") and "Hermes" in page_state()[1]
                        and not win.starting, args.timeout)
    if crashed:
        print(f"WARN  Chromium-Render-Prozess beendet: {crashed[0]}; QtWebEngine hier nicht lauffähig")
        server.stop()
        return 3
    if not check(loaded, f"dashboard page loaded with title: {page_state()}"):
        print("  server log:"); print("\n".join("    " + ln for ln in server.log))
        server.stop()
        return 1
    check(server.started and server.alive(), "server was started by the window and is alive")
    pump(1.0)
    shot("loaded")

    # 2. Server von außen weg, Neu laden: Fehlerseite
    server.stop()
    check(not ds.is_up(args.port), "server stopped from outside")
    win.reload_or_retry()
    errored = wait_until(lambda: page_state()[0].startswith("hermes-os://error"), 15)
    check(errored, f"error page after the server vanished: {page_state()}")
    pump(0.5)
    check("Fehler" in page_state()[1], f"error page title: {page_state()[1]}")
    shot("error")

    # 3. Erneut versuchen (Link der Fehlerseite): Server kommt wieder, Seite lädt
    win.bridge.retryRequested.emit()
    reloaded = wait_until(lambda: page_state()[0].startswith("http://127.0.0.1") and "Hermes" in page_state()[1]
                          and not win.starting, args.timeout)
    check(reloaded, f"retry restarts the server and reloads: {page_state()}")
    check(server.alive() and ds.is_up(args.port), "server alive again after retry")

    # 4. Beenden: aboutToQuit stoppt den Server
    win.window.close()
    app.aboutToQuit.emit()
    pump(0.5)
    check(not server.alive(), "server stopped on quit")
    check(wait_until(lambda: not ds.port_in_use(args.port), 10), "port free after quit")

    if FAILS:
        print(f"=== {len(FAILS)} check(s) FAILED ===")
        return 1
    print("=== dashboard window OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
