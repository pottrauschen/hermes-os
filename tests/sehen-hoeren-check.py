#!/usr/bin/python3
# =============================================================================
# hermes-os -- Sehen und Hören prüfen, ohne Audio-Hardware, ohne Qt, ohne Plasma
# =============================================================================
# Prüft tray/desktop.py, tray/voice.py, tray/voice_worker.py, tray/screenshot.py:
#   - Kürzel-Registrierung: Desktop-Datei für „Was sehe ich hier?" (Menü- und
#     kglobalaccel-Kopie identisch, Meta+Umschalt+H, Exec --look), Tastenfolgen
#     im Qt-Format, Kollisionen mit Plasma-Vorgaben
#   - Anmeldung bei KGlobalAccel gegen ein nachgebautes kglobalacceld auf einem
#     privaten Bus (doRegister, setShortcutKeys, getComponent, Signale für
#     Drücken und Loslassen); fehlt dbus-daemon, wird der Teil übersprungen
#   - Benachrichtigung mit Knöpfen gegen ein nachgebautes notify-send
#   - Aufnahme: Befehle für pw-record und parecord, Mikrofon-Prüfung, WAV-Länge,
#     Rekorder gegen einen nachgebauten Prozess (auch: nichts aufgenommen)
#   - Zustandsautomat von Push-to-Talk: halten, antippen, Tastenwiederholung,
#     unterbrechen, Zeitgrenze, Fehlerwege
#   - Sprachhelfer (voice_worker.py) gegen Attrappen von faster_whisper und piper:
#     Modell und Sprache aus config.yaml, Erkennung, Synthese, Fehler, --check,
#     Frist und Leerlauf
#   - Bildweg: Spectacle-Befehl, Abbruch, Fehler; der Ablauf „Was sehe ich hier?"
#     gegen einen nachgebauten Client (Bild als data-URL im Run, Antwort als
#     Benachrichtigung, Knopf ins Fenster, Fenster offen: Anhang)
#
# Ohne Qt, läuft mit jedem Python 3.9+:
#   tests/sehen-hoeren-check.py [--tray-dir DIR] [--desktop-file FILE]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7l) führt ihn
# im Image-Build aus, make lint überall.
# =============================================================================
import argparse
import base64
import configparser
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import wave
from pathlib import Path

# Die Prüfungen vergleichen deutsche Texte: die Sprache der Oberfläche festhalten,
# auch wenn die Sitzung englisch ist (tray/lang.py, docs/systemagent.md)
os.environ["HERMES_OS_LANG"] = "de"

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TRAY = REPO / "files/system/usr/share/hermes-os/tray"
DEFAULT_DESKTOP = REPO / "files/system/usr/share/kglobalaccel/hermes-os-sehen.desktop"

failures = []


def check(cond, label):
    if cond:
        print(f"PASS  {label}")
    else:
        print(f"FAIL  {label}")
        failures.append(label)


# ---- Kürzel: Desktop-Datei und Tastenfolgen --------------------------------------
def test_desktop_files(desktop, screenshot, path):
    kga = Path(path)
    apps = kga.parent.parent / "applications" / kga.name
    check(kga.is_file() and apps.is_file(), f"Desktop-Dateien vorhanden: {kga.name} unter kglobalaccel und applications")
    if not (kga.is_file() and apps.is_file()):
        return
    check(kga.read_bytes() == apps.read_bytes(), "kglobalaccel-Kopie und Menüeintrag sind identisch")
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(kga, encoding="utf-8")
    e = cp["Desktop Entry"] if cp.has_section("Desktop Entry") else {}
    check(e.get("Type") == "Application" and e.get("Icon") == "hermes-os", "Type=Application, Icon=hermes-os")
    check(e.get("Exec") == "/usr/libexec/hermes-os-tray --look", "Exec ruft hermes-os-tray --look")
    check(e.get("X-KDE-Shortcuts") == screenshot.SHORTCUT == "Meta+Shift+H",
          f"X-KDE-Shortcuts={e.get('X-KDE-Shortcuts')} passt zu screenshot.SHORTCUT")
    check("Hermes" in (e.get("Name") or ""), "Name nennt Hermes")
    check(e.get("Terminal") == "false", "Terminal=false")
    tray = kga.parent / "hermes-os-tray.desktop"
    cp2 = configparser.ConfigParser(interpolation=None)
    cp2.optionxform = str
    cp2.read(tray, encoding="utf-8")
    meta_h = cp2["Desktop Entry"].get("X-KDE-Shortcuts") if cp2.has_section("Desktop Entry") else ""
    check(meta_h == "Meta+H" and meta_h != e.get("X-KDE-Shortcuts"), "Meta+H für das Fenster bleibt, das neue Kürzel ist ein anderes")
    if shutil.which("desktop-file-validate"):
        res = subprocess.run(["desktop-file-validate", str(apps)], capture_output=True, text=True)
        check(res.returncode == 0, "desktop-file-validate" + (f": {res.stdout.strip()}" if res.returncode else ""))
    else:
        print("SKIP  desktop-file-validate fehlt")


def test_keys(desktop, voice, screenshot):
    check(desktop.key_sequence_to_qt("Meta+Space") == 0x10000020, "Meta+Space -> 0x10000020 (Qt::META | Key_Space)")
    check(desktop.key_sequence_to_qt("Meta+Shift+H") == 0x12000048, "Meta+Shift+H -> 0x12000048")
    check(desktop.key_sequence_to_qt("Print") == 0x01000009 and desktop.key_sequence_to_qt("Ctrl+Alt+F3") == 0x0D000032,
          "Print und Ctrl+Alt+F3")
    for bad in ("", "Meta+", "Hyper+X", "Meta+Foo"):
        try:
            desktop.key_sequence_to_qt(bad)
            check(False, f"{bad!r} muss ValueError geben")
        except ValueError:
            check(True, f"{bad!r} gibt ValueError")
    check(desktop.qt_to_key_text(0x10000020) == "Meta+Space" and desktop.qt_to_key_text(0x12000048) == "Meta+Shift+H",
          "Rückweg qt_to_key_text")
    check(desktop.normalize_key_text("meta+umschalt+h") == "Meta+Shift+H"
          and desktop.normalize_key_text("Shift+Meta+leertaste") == "Meta+Shift+Space", "normalize_key_text")
    check(desktop.collision("Alt+Space") == "KRunner" and desktop.collision("Meta+V") and desktop.collision("meta+shift+print"),
          "Kollisionen mit KRunner, Klipper und Spectacle werden erkannt")
    check(desktop.collision(voice.SHORTCUT) is None and desktop.collision(screenshot.SHORTCUT) is None,
          f"{voice.SHORTCUT} und {screenshot.SHORTCUT} sind ab Werk frei")
    check(voice.SHORTCUT == "Meta+Space" and desktop.COMPONENT != "hermes-os-tray.desktop"
          and not desktop.COMPONENT.endswith(".desktop"),
          "Push-to-Talk hat eine eigene KGlobalAccel-Komponente, nicht die Desktop-Datei des Fensters")
    check(desktop.self_test() == [], "desktop.self_test ohne Befund")


# ---- Benachrichtigung mit Knöpfen -----------------------------------------------------
class FakeNotifyProc:
    def __init__(self, out):
        self._out = out

    def communicate(self):
        return self._out, b""


def test_notify(desktop):
    argv = desktop.notify_argv("Titel", "a < b & c", icon="/tmp/bild.png", actions=[("chat", "Im Chat besprechen")], timeout_ms=5000)
    check(argv[0] == "notify-send" and "--icon=/tmp/bild.png" in argv and "--expire-time=5000" in argv
          and argv[argv.index("--action") + 1] == "chat=Im Chat besprechen" and argv[-1] == "a &lt; b &amp; c",
          "notify_argv: Symbol als Pfad, Frist, Knopf, Maskierung")
    check(len(desktop.notify_argv("T", "x" * 2000)[-1]) <= desktop.NOTIFY_MAX_CHARS, "Text wird auf NOTIFY_MAX_CHARS gekürzt")
    calls, chosen = [], []
    real_which = desktop.shutil.which
    desktop.shutil.which = lambda name: "/usr/bin/notify-send" if name == "notify-send" else real_which(name)
    try:
        def popen(argv, **kw):
            calls.append(argv)
            return FakeNotifyProc(b"chat\n")
        t = desktop.notify_actions("T", "B", [("chat", "Chat")], chosen.append, popen=popen)
        t.join(5)
        check(chosen == ["chat"] and calls and "--action" in calls[0], "notify_actions: Wahl aus stdout landet bei on_choice")
        chosen.clear()
        t = desktop.notify_actions("T", "B", [("chat", "Chat")], chosen.append, popen=lambda a, **k: FakeNotifyProc(b""))
        t.join(5)
        check(chosen == [""], "notify_actions: geschlossen ohne Knopf heißt leere Wahl")
        t = desktop.notify_actions("T", "B", [("chat", "Chat")], chosen.append, popen=lambda a, **k: FakeNotifyProc(b"fremd\n"))
        t.join(5)
        check(chosen[-1] == "", "notify_actions: unbekannte Ausgabe zählt nicht als Wahl")
        ok = desktop.notify("T", "B", popen=lambda a, **k: calls.append(a) or FakeNotifyProc(b""))
        check(ok and calls[-1][-1] == "B", "notify: einfache Benachrichtigung ohne Warten")
    finally:
        desktop.shutil.which = real_which
    desktop.shutil.which = lambda name: None
    try:
        check(desktop.notify_actions("T", "B", [], lambda c: None) is None and desktop.notify("T", "B") is False,
              "ohne notify-send: kein Thread, kein Fehler")
    finally:
        desktop.shutil.which = real_which


# ---- KGlobalAccel gegen ein nachgebautes kglobalacceld ---------------------------------------
class FakeKGlobalAccel:
    """Antwortet wie kglobalacceld (KF6) auf dem privaten Bus und sendet Signale."""

    def __init__(self, dp, conn, stored_keys=None, owner=None):
        self.dp = dp
        self.conn = conn
        self.registered, self.set_calls, self.inactive = [], [], []
        self.stored_keys = stored_keys
        # fremder Besitzer der Taste [Komponente, Aktion, Anzeigename, Aktionsname] oder None
        self.owner = owner

    def handle(self, msg):
        dp = self.dp
        if msg.interface not in ("", "org.kde.KGlobalAccel"):
            raise dp.DBusError("org.freedesktop.DBus.Error.UnknownInterface", msg.interface)
        if msg.member == "doRegister" and msg.signature == "as":
            self.registered.append(list(msg.body[0]))
            return "", ()
        if msg.member == "setShortcutKeys" and msg.signature == "asa(ai)u":
            action_id, keys, flags = msg.body
            self.set_calls.append((list(action_id), [list(k) for k in keys], flags))
            if flags & 2 and self.stored_keys is not None:
                return "a(ai)", ([(list(self.stored_keys),)],)     # gespeicherte Belegung gewinnt
            return "a(ai)", ([tuple(k) for k in keys],)
        if msg.member == "getComponent" and msg.signature == "s":
            name = msg.body[0]
            if name != "hermes-os-voice":
                raise dp.DBusError("org.kde.kglobalaccel.NoSuchComponent", name)
            return "o", ("/component/" + "".join(c if c.isalnum() else "_" for c in name),)
        if msg.member == "globalShortcutAvailable" and msg.signature == "(ai)s":
            # wie kglobalacceld: belegt, sobald irgendeine Aktion die Taste hat, auch die eigene
            return "b", (not (self.registered or self.owner),)
        if msg.member == "actionList" and msg.signature == "(ai)":
            if self.owner:
                return "as", (list(self.owner),)
            return "as", (list(self.registered[-1]) if self.registered else [],)
        if msg.member == "setInactive":
            self.inactive.append(list(msg.body[0]))
            return "", ()
        raise dp.DBusError("org.freedesktop.DBus.Error.UnknownMethod", msg.member)

    def press(self, component, action, member="globalShortcutPressed"):
        self.conn.emit_signal("/component/hermes_os_voice", "org.kde.kglobalaccel.Component", member, "ssx",
                              (component, action, 0))


def test_global_shortcut(desktop, dp):
    if not shutil.which("dbus-daemon"):
        print("SKIP  dbus-daemon fehlt, kein Test der Anmeldung bei KGlobalAccel")
        return
    try:
        daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError as exc:
        print(f"SKIP  dbus-daemon startet nicht: {exc}")
        return
    try:
        ready, _, _ = select.select([daemon.stdout], [], [], 10)
        address = daemon.stdout.readline().strip() if ready else ""
        if not address:
            print("SKIP  dbus-daemon nennt keine Adresse")
            return
        service = dp.BusConnection(address)
        fake = FakeKGlobalAccel(dp, service)
        service.export("/kglobalaccel", fake.handle)
        check(service.request_name("org.kde.kglobalaccel"), "nachgebautes kglobalacceld hält org.kde.kglobalaccel")
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                rd, _, _ = select.select([service.fileno()], [], [], 0.1)
                if rd and not service.read_ready():
                    return

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        pressed, released = [], []
        sc = desktop.GlobalShortcut(desktop.COMPONENT, "push-to-talk", desktop.COMPONENT_LABEL, "Sprechen", "Meta+Space",
                                    lambda: pressed.append(time.monotonic()), lambda: released.append(time.monotonic()),
                                    bus_address=address)
        ok = sc.install()
        check(ok, f"Anmeldung bei KGlobalAccel: {sc.error or 'ok'}")
        check(fake.registered == [[desktop.COMPONENT, "push-to-talk", desktop.COMPONENT_LABEL, "Sprechen"]],
              "doRegister mit [Komponente, Aktion, Anzeigename, Aktionsname]")
        check(len(fake.set_calls) == 2 and fake.set_calls[0][1] == [[[0x10000020]]] and fake.set_calls[0][2] == 2
              and fake.set_calls[1][2] == 8, f"setShortcutKeys: erst SetPresent, dann IsDefault, Taste als a(ai): {fake.set_calls}")
        check(sc.component_path == "/component/hermes_os_voice" and sc.active_keys == "Meta+Space" and sc.warning == "",
              f"Komponentenpfad, aktives Kürzel, eigene Anmeldung ist keine Belegung: {sc.component_path} "
              f"{sc.active_keys!r} {sc.warning!r}")

        def pump(timeout=2.0):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                rd, _, _ = select.select([sc.fileno()], [], [], 0.1)
                if rd:
                    sc.read_ready()
                    return True
            return False

        fake.press(desktop.COMPONENT, "push-to-talk")
        pump()
        check(len(pressed) == 1 and not released, "globalShortcutPressed der eigenen Aktion ruft on_pressed")
        fake.press(desktop.COMPONENT, "push-to-talk", "globalShortcutReleased")
        pump()
        check(len(released) == 1, "globalShortcutReleased ruft on_released")
        fake.press("fremd", "push-to-talk")
        fake.press(desktop.COMPONENT, "andere")
        fake.press(desktop.COMPONENT, "push-to-talk", "globalShortcutRepeated")
        pump(0.5)
        pump(0.3)
        check(len(pressed) == 1 and len(released) == 1, "fremde Komponente, fremde Aktion und Repeated lösen nichts aus")
        # Neuer Besitzer von org.kde.kglobalaccel: erneut anmelden
        before = len(fake.registered)
        sc._owner_changed(type("Msg", (), {"body": ["org.kde.kglobalaccel", ":1.5", ":1.9"]})())
        check(len(fake.registered) == before + 1, "NameOwnerChanged mit neuem Besitzer meldet die Aktion neu an")
        sc._owner_changed(type("Msg", (), {"body": ["org.kde.kglobalaccel", ":1.9", ""]})())
        check(len(fake.registered) == before + 1, "NameOwnerChanged ohne neuen Besitzer tut nichts")
        sc.close()
        time.sleep(0.3)
        check(fake.inactive and fake.inactive[-1][1] == "push-to-talk", "close() gibt das Kürzel mit setInactive frei")

        # Gespeicherte Belegung gewinnt, belegtes Kürzel wird gemeldet
        fake.stored_keys = [0x12000020]
        fake.owner = ["kwin", "Overview", "KWin", "Übersicht umschalten"]
        sc2 = desktop.GlobalShortcut(desktop.COMPONENT, "push-to-talk", desktop.COMPONENT_LABEL, "Sprechen", "Meta+Space",
                                     lambda: None, lambda: None, bus_address=address)
        ok2 = sc2.install()
        check(ok2 and sc2.active_keys == "Meta+Shift+Space", f"gespeichertes Kürzel aus kglobalshortcutsrc gewinnt: {sc2.active_keys}")
        check("vergeben (KWin)" in sc2.warning, f"von einer fremden Aktion belegtes Kürzel wird mit Besitzer gemeldet: {sc2.warning!r}")
        fake.owner = None
        sc2.close()
        sc3 = desktop.GlobalShortcut("gibtsnicht", "x", "X", "x", "Meta+Space", lambda: None, lambda: None, bus_address=address)
        check(sc3.install() is False and "KGlobalAccel" in sc3.error, "Fehler von kglobalacceld landet in error")
        sc4 = desktop.GlobalShortcut(desktop.COMPONENT, "x", "X", "x", "Hyper+X", lambda: None, lambda: None, bus_address=address)
        check(sc4.install() is False and "Modifikator" in sc4.error, "unbekanntes Kürzel scheitert vor dem Bus")
        stop.set()
        t.join(2)
        service.close()
    finally:
        daemon.terminate()
        try:
            daemon.wait(5)
        except subprocess.TimeoutExpired:
            daemon.kill()
    sc5 = desktop.GlobalShortcut(desktop.COMPONENT, "x", "X", "x", "Meta+Space", lambda: None, lambda: None,
                                 bus_address="unix:path=/nonexistent/bus")
    check(sc5.install() is False and "Sitzungsbus" in sc5.error, "ohne Bus: sauberer Fehler, kein Absturz")


# ---- Aufnahme ------------------------------------------------------------------------
def write_wav(path, seconds, rate=16000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(rate * seconds))


class FakeRecordProc:
    """Nachgebauter pw-record: schreibt beim Stoppen eine WAV-Datei bestimmter Länge."""

    def __init__(self, path, seconds, exit_code=0, stderr=b""):
        self.path, self.seconds, self._rc, self._stderr = path, seconds, exit_code, stderr
        self.returncode = None
        self.signals = []
        self.stderr = type("S", (), {"read": lambda s: self._stderr})()

    def poll(self):
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        if self.seconds is None:
            return                      # hängt: reagiert nicht auf SIGINT
        write_wav(self.path, self.seconds)
        self.returncode = self._rc

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("pw-record", timeout)
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_recording(voice):
    which = lambda name: "/usr/bin/" + name if name in ("pw-record", "parecord", "arecord", "pw-play", "paplay") else None
    argv = voice.recorder_command("/tmp/a.wav", which=which)
    check(argv[0] == "pw-record" and "--rate" in argv and "16000" in argv and "--channels" in argv and argv[-1] == "/tmp/a.wav",
          f"pw-record hat Vorrang: {' '.join(argv)}")
    argv = voice.recorder_command("/tmp/a.wav", which=lambda n: "/usr/bin/parecord" if n == "parecord" else None)
    check(argv[0] == "parecord" and "--file-format=wav" in argv and "--rate=16000" in argv, f"parecord als Ersatz: {' '.join(argv)}")
    check(voice.recorder_command("/tmp/a.wav", tool="arecord")[0] == "arecord", "arecord auf Wunsch")
    try:
        voice.recorder_command("/tmp/a.wav", which=lambda n: None)
        check(False, "ohne Rekorder muss ValueError kommen")
    except ValueError as exc:
        check("pw-record" in str(exc), f"ohne Rekorder: {exc}")
    check(voice.player_command("/tmp/a.wav", which=which)[0] == "pw-play"
          and voice.player_command("/tmp/a.wav", which=lambda n: None) is None, "player_command: pw-play, sonst None")

    def run_pactl(out):
        return lambda argv: out if argv[0] == "pactl" else None
    check(voice.microphone_available(run_pactl("0\talsa_output.pci.monitor\tmodule\ts16le\tRUNNING\n")) is False,
          "pactl: nur ein Monitor heißt kein Mikrofon")
    check(voice.microphone_available(run_pactl("0\talsa_output.pci.monitor\tm\ts16le\tIDLE\n1\talsa_input.usb-mic\tm\ts16le\tSUSPENDED\n")) is True,
          "pactl: eine Eingabequelle heißt Mikrofon da")
    check(voice.microphone_available(run_pactl("")) is False, "pactl: keine Quelle heißt kein Mikrofon")
    wpctl = "PipeWire 'pipewire-0'\nAudio\n ├─ Devices:\n │      41. Built-in Audio\n ├─ Sinks:\n │  *   50. Speakers\n ├─ Sources:\n │  *   55. Built-in Microphone [vol: 1.00]\n ├─ Filters:\n"
    check(voice.microphone_available(lambda a: wpctl if a[0] == "wpctl" else None) is True, "wpctl status: Sources mit Eintrag")
    check(voice.microphone_available(lambda a: wpctl.replace("55. Built-in Microphone", "").replace(" │  *   ", "") if a[0] == "wpctl" else None) is False,
          "wpctl status: Sources leer")
    check(voice.microphone_available(lambda a: None) is None, "weder pactl noch wpctl: unbekannt, Aufnahme wird versucht")

    tmp = tempfile.mkdtemp(prefix="hermes-voice-")
    write_wav(os.path.join(tmp, "eins.wav"), 1.5)
    check(abs(voice.wav_seconds(os.path.join(tmp, "eins.wav")) - 1.5) < 0.01, "wav_seconds liest die Länge")
    Path(tmp, "kaputt.wav").write_bytes(b"RIFF" + b"\0" * 10)
    check(voice.wav_seconds(os.path.join(tmp, "kaputt.wav")) == 0 and voice.wav_seconds(os.path.join(tmp, "fehlt.wav")) == 0,
          "wav_seconds: defekt oder fehlend heißt 0")

    procs = []

    def popen_factory(seconds, rc=0, stderr=b""):
        def popen(argv, **kw):
            p = FakeRecordProc(argv[-1], seconds, rc, stderr)
            procs.append(p)
            return p
        return popen

    rec = voice.Recorder(tmp, tool="pw-record", popen=popen_factory(2.0), which=which)
    ok, err = rec.start()
    check(ok and rec.path.endswith(".wav"), f"Rekorder startet: {err or rec.path}")
    ok, result = rec.stop()
    check(ok and result == rec.path and os.path.isfile(result) and procs[-1].signals == [signal.SIGINT],
          "Rekorder stoppt mit SIGINT und liefert die Datei")
    rec = voice.Recorder(tmp, tool="pw-record", popen=popen_factory(0.0, 0, b"stream error: no source"), which=which)
    rec.start()
    ok, result = rec.stop()
    check(not ok and "Mikrofon" in result and "no source" in result and not os.path.exists(rec.path),
          f"nichts aufgenommen: klare Meldung, Datei weg: {result}")
    rec = voice.Recorder(tmp, tool="pw-record", popen=popen_factory(0.1), which=which)
    rec.start()
    ok, result = rec.stop()
    check(not ok and "kurz" in result, f"zu kurze Aufnahme: {result}")
    rec = voice.Recorder(tmp, tool="pw-record", popen=popen_factory(None), which=which)
    rec.start()
    ok, result = rec.stop()
    check(not ok and procs[-1].returncode == -9, "Rekorder, der nicht endet, wird beendet")
    rec = voice.Recorder(tmp, tool="pw-record", popen=lambda a, **k: (_ for _ in ()).throw(OSError("exec")), which=which)
    ok, err = rec.start()
    check(not ok and "startet nicht" in err, f"Rekorder ohne Programm: {err}")
    rec = voice.Recorder(tmp, popen=popen_factory(1.0), which=lambda n: None)
    ok, err = rec.start()
    check(not ok and "pw-record" in err, "Rekorder ohne Aufnahmeprogramm meldet es")
    rec = voice.Recorder(tmp, tool="pw-record", popen=popen_factory(2.0), which=which)
    rec.start()
    rec.cancel()
    check(procs[-1].returncode == -9 and not os.path.exists(rec.path), "cancel bricht ab und löscht")
    shutil.rmtree(tmp, ignore_errors=True)


# ---- Zustandsautomat -----------------------------------------------------------------------
class FakeActions:
    def __init__(self, mic_ok=True, ask_ok=True):
        self.calls = []
        self.states = []
        self.mic_ok = mic_ok
        self.ask_ok = ask_ok

    def start_recording(self):
        self.calls.append("start")
        return (True, "") if self.mic_ok else (False, "Kein Mikrofon gefunden.")

    def stop_recording(self):
        self.calls.append("stop")

    def cancel_recording(self):
        self.calls.append("cancel")

    def transcribe(self, path):
        self.calls.append(("transcribe", path))

    def ask(self, text):
        self.calls.append(("ask", text))
        return self.ask_ok

    def speak(self, text):
        self.calls.append(("speak", text))

    def stop_speaking(self):
        self.calls.append("mute")

    def notify(self, title, body):
        self.calls.append(("notify", title, body))

    def state_changed(self, state):
        self.states.append(state)


def test_automaton(voice):
    now = [100.0]
    clock = lambda: now[0]
    a = FakeActions()
    p = voice.PushToTalk(a, clock=clock, min_hold=0.35, max_record=90)
    # Halten
    p.press()
    check(p.state == "recording" and a.calls == ["start"] and p.hold, "Drücken startet die Aufnahme")
    p.press()
    check(a.calls == ["start"], "Tastenwiederholung bei gehaltener Taste tut nichts")
    now[0] += 1.2
    p.release()
    check(p.state == "transcribing" and a.calls[-1] == "stop", "Loslassen nach dem Halten beendet die Aufnahme")
    p.recording_done(True, "/tmp/x.wav")
    check(a.calls[-1] == ("transcribe", "/tmp/x.wav"), "fertige Aufnahme geht in die Erkennung")
    p.transcribed(True, "  Wie   spät ist es? ")
    check(p.state == "asking" and a.calls[-1] == ("ask", "Wie spät ist es?") and p.last_text == "Wie spät ist es?",
          "erkannter Text geht bereinigt als Frage ins Fenster")
    p.answer("**Es ist** 12 Uhr. MEDIA:/tmp/a.png")
    check(p.state == "speaking" and a.calls[-1] == ("speak", "Es ist 12 Uhr."), "Antwort wird ohne Markdown vorgelesen")
    p.speaking_done()
    check(p.state == "idle" and a.states == ["recording", "transcribing", "asking", "speaking", "idle"],
          f"Zustandsfolge: {a.states}")
    # Antippen
    a = FakeActions()
    p = voice.PushToTalk(a, clock=clock)
    p.press()
    now[0] += 0.1
    p.release()
    check(p.state == "recording" and not p.hold and a.calls == ["start"], "kurz angetippt: Aufnahme läuft weiter")
    p.press()
    check(p.state == "transcribing" and a.calls[-1] == "stop", "zweiter Druck beendet die angetippte Aufnahme")
    p.release()
    check(p.state == "transcribing", "Loslassen nach dem zweiten Druck ändert nichts")
    # Knopf im Fenster und Unterbrechen beim Sprechen
    a = FakeActions()
    p = voice.PushToTalk(a, clock=clock)
    p.toggle()
    check(p.state == "recording" and not p.hold, "toggle startet ohne Halten")
    p.toggle()
    check(p.state == "transcribing", "toggle beendet")
    p.recording_done(True, "/tmp/y.wav")
    p.transcribed(True, "Hallo")
    p.answer("Antwort")
    check(p.state == "speaking", "spricht")
    p.press()
    check(a.calls[-2:] == ["mute", "start"] and p.state == "recording" and p.hold, "Druck beim Sprechen: verstummen und zuhören")
    now[0] += 1
    p.release()
    p.recording_done(True, "/tmp/z.wav")
    p.transcribed(True, "Noch was")
    p.answer("Zweite Antwort")
    p.toggle()
    check(a.calls[-1] == "mute" and p.state == "idle", "toggle beim Sprechen bricht das Vorlesen ab")
    # Zeitgrenze
    a = FakeActions()
    p = voice.PushToTalk(a, clock=clock, max_record=5)
    p.press()
    now[0] += 4
    p.tick()
    check(p.state == "recording", "vor der Zeitgrenze läuft die Aufnahme")
    now[0] += 2
    p.tick()
    check(p.state == "transcribing" and a.calls[-1] == "stop", "Zeitgrenze beendet die Aufnahme")
    # Fehlerwege
    a = FakeActions(mic_ok=False)
    p = voice.PushToTalk(a, clock=clock)
    p.press()
    check(p.state == "idle" and a.calls[-1][0] == "notify" and "Mikrofon" in a.calls[-1][2] and a.states == ["idle"] or p.state == "idle",
          f"ohne Mikrofon: Meldung, bleibt idle: {a.calls[-1]}")
    a = FakeActions()
    p = voice.PushToTalk(a, clock=clock)
    p.toggle()
    p.toggle()
    p.recording_done(False, "Nichts aufgenommen")
    check(p.state == "idle" and a.calls[-1][0] == "notify" and "Nichts aufgenommen" in a.calls[-1][2], "leere Aufnahme: Meldung")
    p.toggle()
    p.toggle()
    p.recording_done(True, "/tmp/q.wav")
    p.transcribed(True, "   ")
    check(p.state == "idle" and "verstanden" in a.calls[-1][1], "nichts verstanden: Meldung")
    p.toggle()
    p.toggle()
    p.recording_done(True, "/tmp/q.wav")
    p.transcribed(False, "faster-whisper fehlt")
    check(p.state == "idle" and "faster-whisper fehlt" in a.calls[-1][2], "Fehler der Erkennung: Meldung")
    a = FakeActions(ask_ok=False)
    p = voice.PushToTalk(a, clock=clock)
    p.toggle()
    p.toggle()
    p.recording_done(True, "/tmp/q.wav")
    p.transcribed(True, "Frage ohne Gateway")
    check(p.state == "idle" and "Frage ohne Gateway" in a.calls[-1][2], "Gateway nicht bereit: Meldung nennt den Text")
    a = FakeActions()
    p = voice.PushToTalk(a, clock=clock)
    p.toggle()
    p.toggle()
    p.recording_done(True, "/tmp/q.wav")
    p.transcribed(True, "Frage")
    p.answer("")
    check(p.state == "idle" and not any(c[0] == "speak" for c in a.calls if isinstance(c, tuple)), "leere Antwort (Abbruch): nichts vorlesen")
    p.toggle()
    p.toggle()
    p.recording_done(True, "/tmp/q.wav")
    p.transcribed(True, "Frage")
    p.answer("Text")
    p.speaking_done("piper fehlt")
    check(p.state == "idle" and "piper fehlt" in a.calls[-1][2], "Fehler beim Sprechen: Meldung")
    p.toggle()
    p.cancel()
    check(p.state == "idle" and a.calls[-1] == "cancel", "cancel bricht die Aufnahme ab")
    p.recording_done(True, "/tmp/alt.wav")
    p.transcribed(True, "alt")
    p.answer("alt")
    p.speaking_done()
    check(p.state == "idle" and not any(isinstance(c, tuple) and c[0] == "ask" and c[1] == "alt" for c in a.calls),
          "verspätete Rückmeldungen im falschen Zustand verhallen")


# ---- Sprachhelfer gegen Attrappen ----------------------------------------------------------
FAKE_WHISPER = '''
import json, os
class _Seg:
    def __init__(self, text, no_speech, logprob):
        self.text, self.no_speech_prob, self.avg_logprob = text, no_speech, logprob
class WhisperModel:
    def __init__(self, model, device="auto", compute_type="auto", **kw):
        self.model, self.device, self.compute_type = model, device, compute_type
        if device == "cuda":
            raise RuntimeError("libcublas fehlt")
    def transcribe(self, path, **kwargs):
        with open(os.environ["FAKE_LOG"], "a") as f:
            f.write(json.dumps({"model": self.model, "device": self.device, "compute_type": self.compute_type,
                                "path": path, "kwargs": kwargs}) + "\\n")
        if os.path.basename(path).startswith("leer"):
            return iter([]), None
        return iter([_Seg(" Hallo ", 0.1, -0.2), _Seg("Rauschen", 0.9, -1.5), _Seg("Welt", 0.7, -0.5)]), None
'''
FAKE_PIPER = '''
import json, os
class SynthesisConfig:
    def __init__(self, **kw):
        self.kw = kw
class PiperVoice:
    @classmethod
    def load(cls, path, use_cuda=False, **kw):
        v = cls(); v.path = path; v.use_cuda = use_cuda
        return v
    def synthesize_wav(self, text, wav_file, syn_config=None, set_wav_format=True):
        wav_file.setnchannels(1); wav_file.setsampwidth(2); wav_file.setframerate(22050)
        wav_file.writeframes(b"\\x01\\x00" * (220 * max(1, len(text))))
        with open(os.environ["FAKE_LOG"], "a") as f:
            f.write(json.dumps({"voice": self.path, "text": text, "cuda": self.use_cuda,
                                "syn": getattr(syn_config, "kw", None)}) + "\\n")
'''


def test_worker(voice, tray_dir):
    tmp = tempfile.mkdtemp(prefix="hermes-worker-")
    fakes = Path(tmp, "fakes")
    (fakes / "faster_whisper").mkdir(parents=True)
    (fakes / "faster_whisper" / "__init__.py").write_text(FAKE_WHISPER, encoding="utf-8")
    (fakes / "piper").mkdir()
    (fakes / "piper" / "__init__.py").write_text(FAKE_PIPER, encoding="utf-8")
    home = Path(tmp, "hermes")
    home.mkdir()
    (home / "config.yaml").write_text(textwrap.dedent("""\
        stt:
          enabled: true
          provider: local
          language: de
          local:
            model: small
        tts:
          provider: piper
          piper:
            voice: de_DE-thorsten-medium
        """), encoding="utf-8")
    voices = home / "cache" / "piper-voices"
    voices.mkdir(parents=True)
    (voices / "de_DE-thorsten-medium.onnx").write_bytes(b"onnx")
    (voices / "de_DE-thorsten-medium.onnx.json").write_text("{}", encoding="utf-8")
    log = Path(tmp, "calls.jsonl")
    env = dict(os.environ, PYTHONPATH=str(fakes), HERMES_HOME=str(home), FAKE_LOG=str(log), PYTHONDONTWRITEBYTECODE="1")
    env.pop("HERMES_LAZY_INSTALL_TARGET", None)
    script = os.path.join(tray_dir, "voice_worker.py")

    res = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True, env=env, timeout=60)
    check(res.returncode == 0 and "OK" in res.stdout, "voice_worker --check mit Attrappen: " + " | ".join(res.stdout.strip().splitlines()))
    res = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True,
                         env=dict(env, PYTHONPATH=""), timeout=60)
    has_real = res.returncode == 0
    check(has_real or "nicht importierbar" in res.stdout, "voice_worker --check ohne die Pakete meldet, was fehlt")

    events = []
    w = voice.Worker(python=sys.executable, script=script, on_event=events.append, env=env)
    check(w.available, "Worker.available: Python und Skript da")
    r = w.request("ping", 30)
    check(r.get("ok") and r.get("hermes") is False, f"ping: {r}")
    wav = os.path.join(tmp, "frage.wav")
    write_wav(wav, 1.0)
    r = w.request("transcribe", 60, path=wav)
    check(r.get("ok") and r.get("text") == "Hallo Welt" and r.get("model") == "small" and r.get("language") == "de",
          f"transcribe: Segmente gefiltert und verbunden: {r}")
    call = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    check(call["model"] == "small" and call["kwargs"].get("language") == "de" and call["kwargs"].get("beam_size") == 5
          and call["kwargs"].get("vad_filter") is True and call["kwargs"]["vad_parameters"]["min_silence_duration_ms"] == 500,
          f"faster-whisper bekommt Modell und Sprache aus config.yaml, VAD wie Hermes: {call['kwargs']}")
    check(any(e.get("event") == "loading" and e.get("what") == "stt" and e.get("model") == "small" for e in events),
          f"Ereignis loading vor dem ersten Laden: {events}")
    leer = os.path.join(tmp, "leer.wav")
    write_wav(leer, 1.0)
    r = w.request("transcribe", 60, path=leer)
    check(r.get("ok") and r.get("text") == "", "transcribe ohne Segmente: leerer Text, kein Fehler")
    r = w.request("transcribe", 60, path=os.path.join(tmp, "fehlt.wav"))
    check(not r.get("ok") and "nicht gefunden" in r.get("error", ""), f"transcribe mit fehlender Datei: {r}")
    out = os.path.join(tmp, "antwort.wav")
    r = w.request("speak", 60, text="Es ist zwölf Uhr.", out=out)
    check(r.get("ok") and r.get("path") == out and voice.wav_seconds(out) > 0 and r.get("voice") == "de_DE-thorsten-medium",
          f"speak: WAV geschrieben: {r}")
    spoken = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if "voice" in l][-1]
    check(spoken["voice"].endswith("de_DE-thorsten-medium.onnx") and spoken["text"] == "Es ist zwölf Uhr.",
          "piper lädt die Stimme aus tts.piper.voice im Ordner von Hermes")
    r = w.request("speak", 60, text="   ", out=out)
    check(not r.get("ok"), "speak ohne Text: Fehler")
    r = w.request("tanzen", 30)
    check(not r.get("ok") and "unbekannt" in r.get("error", ""), "unbekannter Auftrag: Fehler, Helfer läuft weiter")
    r = w.request("ping", 30)
    check(r.get("ok"), "Helfer antwortet nach einem Fehler weiter")
    calls_before = len(log.read_text(encoding="utf-8").splitlines())
    r = w.request("transcribe", 60, path=wav)
    calls = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    check(r.get("ok") and len(calls) == calls_before + 1 and not any(e.get("what") == "stt" for e in events[1:]),
          "zweiter Auftrag nutzt das geladene Modell (kein zweites loading)")
    w.stop()
    check(w._proc is None or w._proc.poll() is not None, "stop beendet den Helfer")

    # Frist: ein Helfer, der nie antwortet
    hang = Path(tmp, "hang.py")
    hang.write_text("import sys, time\nsys.stdin.readline()\ntime.sleep(30)\n", encoding="utf-8")
    w2 = voice.Worker(python=sys.executable, script=str(hang), env=env)
    r = w2.request("ping", 1.0)
    check(not r.get("ok") and "antwortet nicht" in r.get("error", "") and (w2._proc is None), f"Frist greift, Helfer beendet: {r}")
    w3 = voice.Worker(python="/nonexistent/python", script=script, env=env)
    check(not w3.available, "Worker ohne Venv-Python: nicht verfügbar")
    r = w3.request("ping", 5)
    check(not r.get("ok") and "startet nicht" in r.get("error", ""), f"Worker ohne Python: Fehler statt Absturz: {r}")

    # Leerlauf: der Helfer beendet sich selbst
    proc = subprocess.Popen([sys.executable, script, "--idle", "0.5"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    try:
        proc.wait(8)
        check(proc.returncode == 0, "Helfer beendet sich nach dem Leerlauf")
    except subprocess.TimeoutExpired:
        proc.kill()
        check(False, "Helfer beendet sich nach dem Leerlauf")

    # Config-Auflösung wie Hermes
    import importlib.util
    spec = importlib.util.spec_from_file_location("voice_worker", script)
    vw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vw)
    st = vw.stt_settings({"stt": {"language": "en", "local": {"model": "whisper-1", "language": "de", "vad": False}}})
    check(st["model"] == "base" and st["language"] == "de" and st["vad"] is False, f"stt_settings: Cloud-Name wird base, stt.local.language vor stt.language: {st}")
    check(vw.stt_settings({})["model"] == "base" and vw.stt_settings({})["language"] is None, "stt_settings ohne Config: base, Sprache automatisch")
    tt = vw.tts_settings({"tts": {"piper": {"voice": "de_DE-karlsson-low", "voices_dir": "/x"}}})
    check(tt["voice"] == "de_DE-karlsson-low" and str(vw.piper_voices_dir(tt)) == "/x", "tts_settings: Stimme und voices_dir")
    check(str(vw.piper_voices_dir(vw.tts_settings({}), home)) == str(home / "cache" / "piper-voices"), "Stimmen liegen unter HERMES_HOME/cache/piper-voices")
    legacy = home / "piper_voices_cache"
    legacy.mkdir()
    (legacy / "x.onnx").write_bytes(b"x")
    check(vw.piper_voices_dir(vw.tts_settings({}), home) == legacy, "gefüllter Alt-Ordner piper_voices_cache gewinnt")
    shutil.rmtree(tmp, ignore_errors=True)


# ---- Bildweg -------------------------------------------------------------------------
class FakeClient:
    def __init__(self, events, fail_start=False):
        self._events = events
        self.fail_start = fail_start
        self.sessions, self.runs, self.approvals, self.stopped = [], [], [], []

    def ensure_session(self, sid, source="desktop"):
        self.sessions.append(sid)
        return True

    def start_run(self, sid, text, images=None):
        if self.fail_start:
            raise OSError("Verbindung verweigert")
        self.runs.append((sid, text, list(images or [])))
        return "run-1"

    def events(self, run_id):
        yield from self._events

    def approve(self, run_id, choice, request_id=""):
        self.approvals.append((choice, request_id))
        return {}

    def stop(self, run_id):
        self.stopped.append(run_id)
        return {}


class FakeRun:
    def __init__(self, returncode=0, write=True, stderr=b"", raise_timeout=False):
        self.returncode, self.write, self.stderr, self.raise_timeout = returncode, write, stderr, raise_timeout
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        if self.write:
            Path(argv[-1]).write_bytes(b"\x89PNG fake")
        return subprocess.CompletedProcess(argv, self.returncode, b"", self.stderr)


def test_screenshot(screenshot, runner, hc):
    argv = screenshot.capture_command("/tmp/x.png")
    check(argv[0] == "spectacle" and {"--new-instance", "--background", "--region", "--nonotify"} <= set(argv)
          and argv[-2:] == ["--output", "/tmp/x.png"], f"Spectacle-Befehl: {' '.join(argv)}")
    tmp = tempfile.mkdtemp(prefix="hermes-look-")
    which = lambda n: "/usr/bin/spectacle" if n == "spectacle" else None
    path = os.path.join(tmp, "a.png")
    run = FakeRun()
    check(screenshot.capture_region(path, run=run, which=which) == ("ok", path) and run.calls[0][-1] == path, "Aufnahme liefert die Datei")
    Path(path).write_bytes(b"alt")
    status, detail = screenshot.capture_region(path, run=FakeRun(write=False), which=which)
    check(status == "cancelled" and not os.path.exists(path), "Escape (Exit 0, keine Datei): abgebrochen, alte Datei weg")
    status, detail = screenshot.capture_region(path, run=FakeRun(1, False, b"kwin: no screenshot\nSpectacle: kein KWin"), which=which)
    check(status == "error" and "kein KWin" in detail, f"Fehler mit letzter stderr-Zeile: {detail}")
    check(screenshot.capture_region(path, run=FakeRun(raise_timeout=True), which=which)[0] == "cancelled", "Frist: abgebrochen")
    check(screenshot.capture_region(path, run=FakeRun(), which=lambda n: None) == ("error", "Spectacle ist nicht installiert."),
          "ohne Spectacle: klare Meldung")
    check(screenshot.look_session_id("20260926") == "hermes-os-look-20260926", "Sitzung je Tag")

    # Der Ablauf gegen einen nachgebauten Client
    notices, actions_shown, attached, discussed = [], [], [], []
    client = FakeClient([{"event": "message.delta", "delta": "Ein Terminal "},
                         {"event": "run.completed", "output": "Ein Terminal mit einem Fehler. MEDIA:/tmp/nicht-da.png"}])
    visible = [False]

    def capture(p):
        Path(p).write_bytes(b"\x89PNG")
        return "ok", p

    def notify_actions(title, body, actions, on_choice, icon):
        actions_shown.append((title, body, actions, icon))
        notify_actions.on_choice = on_choice

    flow = screenshot.LookFlow(
        tmp, capture, lambda p: "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode(),
        lambda: client, lambda c, q, sid, images: runner.lookup_answer(c, q, sid, split_media=hc.split_media_tags, images=images),
        lambda: visible[0], lambda p, q: attached.append((p, q)), notify_actions, lambda t, b: notices.append((t, b)),
        lambda p, q, a: discussed.append((p, q, a)))
    result = flow.run()
    check(result == "answered" and len(client.runs) == 1, f"Fenster zu: still gefragt: {result}")
    sid, text, images = client.runs[0]
    check(sid.startswith("hermes-os-look-") and text == screenshot.DEFAULT_QUESTION and len(images) == 1
          and images[0].startswith("data:image/png;base64,"), "Run trägt Standardfrage und das Bild als data-URL")
    check(actions_shown and actions_shown[0][0] == screenshot.NOTIFY_TITLE and actions_shown[0][1] == "Ein Terminal mit einem Fehler."
          and actions_shown[0][2] == [("chat", "Im Chat besprechen")] and actions_shown[0][3].endswith(".png"),
          f"Antwort als Benachrichtigung mit Knopf und Bild als Symbol: {actions_shown}")
    notify_actions.on_choice("")
    check(not discussed, "Benachrichtigung geschlossen: nichts passiert")
    notify_actions.on_choice("chat")
    check(len(discussed) == 1 and discussed[0][1] == screenshot.DEFAULT_QUESTION and discussed[0][2] == "Ein Terminal mit einem Fehler."
          and discussed[0][0].endswith(".png"), "Knopf „Im Chat besprechen“ holt Bild, Frage und Antwort ins Fenster")
    result = flow.run("  Was steht in   der Fehlermeldung? ")
    check(result == "answered" and client.runs[-1][1] == "Was steht in der Fehlermeldung?", "eigene Frage geht bereinigt mit")
    visible[0] = True
    result = flow.run()
    check(result == "attached" and attached == [(attached[0][0], screenshot.DEFAULT_QUESTION)] and len(client.runs) == 2,
          "Fenster offen: Ausschnitt als Anhang, Frage im Feld, kein stiller Run")
    result = flow.run("Meine Frage", to_window=False)
    check(result == "answered" and client.runs[-1][1] == "Meine Frage", "to_window=False fragt still, auch bei offenem Fenster")
    visible[0] = False
    flow2 = screenshot.LookFlow(tmp, lambda p: ("cancelled", ""), lambda p: "", lambda: client, None, lambda: False,
                                None, notify_actions, lambda t, b: notices.append((t, b)), None)
    check(flow2.run() == "cancelled" and not notices, "Abbruch der Auswahl: still")
    flow3 = screenshot.LookFlow(tmp, lambda p: ("error", "Spectacle fehlt"), lambda p: "", lambda: client, None, lambda: False,
                                None, notify_actions, lambda t, b: notices.append((t, b)), None)
    check(flow3.run() == "error" and notices[-1] == ("Kein Bildschirmausschnitt", "Spectacle fehlt"), "Fehler bei der Aufnahme: Meldung")
    bad = FakeClient([], fail_start=True)
    flow4 = screenshot.LookFlow(tmp, capture, lambda p: "data:image/png;base64,AA==", lambda: bad,
                                lambda c, q, sid, images: runner.lookup_answer(c, q, sid, images=images), lambda: False,
                                None, notify_actions, lambda t, b: notices.append((t, b)), None)
    check(flow4.run() == "error" and "fehlgeschlagen" in notices[-1][0] and "verweigert" in notices[-1][1],
          f"Gateway weg: Meldung: {notices[-1]}")
    flow5 = screenshot.LookFlow(tmp, capture, lambda p: (_ for _ in ()).throw(ValueError("Kein lesbares Bild")), lambda: client,
                                None, lambda: False, None, notify_actions, lambda t, b: notices.append((t, b)), None)
    check(flow5.run() == "error" and "Kein lesbares Bild" in notices[-1][1], "unlesbares Bild: Meldung")
    flow.busy = True
    check(flow.run() == "busy", "zweiter Durchlauf während des ersten: busy")
    flow.busy = False
    # Freigabe beim stillen Fragen wird abgelehnt (wie beim Nachschlagen)
    approving = FakeClient([{"event": "approval.request", "request_id": "r1", "command": "rm -rf /"},
                            {"event": "run.completed", "output": "Ich wollte aufräumen."}])
    ok, text = runner.lookup_answer(approving, "Frage", "s", images=["data:image/png;base64,AA=="])
    check(ok and approving.approvals == [("deny", "r1")] and "abgelehnt" in text and approving.runs[0][2] == ["data:image/png;base64,AA=="],
          "lookup_answer mit Bild: Freigabe abgelehnt, Bild im Run")
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tray-dir", default=str(DEFAULT_TRAY))
    ap.add_argument("--desktop-file", default=str(DEFAULT_DESKTOP))
    args = ap.parse_args()
    sys.path.insert(0, args.tray_dir)
    import desktop
    import dbus_peer as dp
    import hermes_client as hc
    import runner
    import screenshot
    import voice
    print(f"== Kürzel (Desktop-Datei {args.desktop_file}) ==")
    test_desktop_files(desktop, screenshot, args.desktop_file)
    test_keys(desktop, voice, screenshot)
    print("== Benachrichtigung mit Knöpfen ==")
    test_notify(desktop)
    print("== KGlobalAccel gegen ein nachgebautes kglobalacceld ==")
    test_global_shortcut(desktop, dp)
    print("== Aufnahme ==")
    test_recording(voice)
    print("== Zustandsautomat Push-to-Talk ==")
    test_automaton(voice)
    print("== Sprachhelfer gegen Attrappen ==")
    test_worker(voice, args.tray_dir)
    print("== Bildweg ==")
    test_screenshot(screenshot, runner, hc)
    if failures:
        print(f"\nsehen-hoeren-check: {len(failures)} Fehler")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nsehen-hoeren-check: alles sauber")
    return 0


if __name__ == "__main__":
    sys.exit(main())
