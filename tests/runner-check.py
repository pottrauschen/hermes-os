#!/usr/bin/python3
# =============================================================================
# hermes-os -- KRunner-Runner „Hermes fragen“ prüfen, ohne Plasma und ohne Hermes
# =============================================================================
# Prüft tray/runner.py und tray/dbus_peer.py:
#   - Präfix-Erkennung (`hermes <Frage>`, `h: <Frage>`), Umlaute, leere Eingabe
#   - Treffer im Format von org.kde.krunner1.Match, Relevanz, Aktionen
#   - Run: Enter schickt ins Fenster, „Nur nachschlagen“ fragt still nach
#   - Wartende Frage, bis das Fenster senden kann; Aufgeben nach der Frist
#   - Nachschlagen gegen einen nachgebauten Client (Antwort, Freigabe, Fehler)
#   - D-Bus-Drahtformat: Match-Antwort a(sssida{sv}) hin und zurück
#   - Desktop-Datei unter /usr/share/krunner/dbusplugins: Pflichtschlüssel,
#     Dienstname und Pfad passen zu runner.py, Filter-Regex passt zur Erkennung
#   - Wenn dbus-daemon und dbus-send da sind: echter privater Bus, Match und Run
#     per dbus-send. Fehlen sie, wird dieser Teil übersprungen.
#
# Ohne Qt, läuft mit jedem Python 3.9+:
#   tests/runner-check.py [--tray-dir DIR] [--desktop-file FILE]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7h) führt ihn
# im Image-Build aus.
# =============================================================================
import argparse
import configparser
import os
import re
import select
import shutil
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TRAY = REPO / "files/system/usr/share/hermes-os/tray"
DEFAULT_DESKTOP = REPO / "files/system/usr/share/krunner/dbusplugins/hermes-os.desktop"

failures = []


def check(cond, label):
    if cond:
        print(f"PASS  {label}")
    else:
        print(f"FAIL  {label}")
        failures.append(label)


# ---- Präfix und Treffer --------------------------------------------------------
def test_parse(runner):
    cases = {
        "hermes Wie spät ist es?": "Wie spät ist es?",
        "Hermes wie wird das Wetter in Köln?": "wie wird das Wetter in Köln?",
        "HERMES   Größe von /home?  ": "Größe von /home?",
        "hermes: Übersetze Straße": "Übersetze Straße",
        "hermes, zeig mir die Updates": "zeig mir die Updates",
        "h: Grüße an alle": "Grüße an alle",
        "H:äöü ß": "äöü ß",
        "  h : Leerzeichen vor dem Doppelpunkt": "Leerzeichen vor dem Doppelpunkt",
        "hermes mit geschütztem Leerzeichen": "mit geschütztem Leerzeichen",
    }
    for query, want in cases.items():
        got = runner.parse_query(query)
        check(got == want, f"parse_query({query!r}) -> {want!r} (bekam {got!r})")
    for query in ["", "   ", "hermes", "hermes ", "Hermes:", "h:", "h:   ", "hermesfoo bar", "hermes-os",
                  "hallo hermes wie geht's", "h Frage ohne Doppelpunkt", "firefox", None]:
        check(runner.parse_query(query) is None, f"parse_query({query!r}) -> None")


def test_matches(runner):
    m = runner.build_matches("hermes Wie viel Speicher ist frei auf /dev/nvme0n1?")
    check(len(m) == 1, "genau ein Treffer")
    mid, text, icon, category, relevance, props = m[0]
    check(mid == runner.MATCH_ID_PREFIX + "Wie viel Speicher ist frei auf /dev/nvme0n1?", "Treffer-ID trägt die Frage")
    check(text == "Hermes fragen: Wie viel Speicher ist frei auf /dev/nvme0n1?", "Treffer-Text „Hermes fragen: …“")
    check(icon == "hermes-os", "Symbol hermes-os")
    check(category == 100 and isinstance(category, int), "Kategorie-Relevanz Highest (100)")
    check(relevance == 1.0 and isinstance(relevance, float), "Relevanz 1.0")
    check(props.get("actions") == [runner.ACTION_LOOKUP], "Treffer bietet „Nur nachschlagen“ an")
    check(isinstance(props.get("subtext"), str) and props["subtext"], "Untertext gesetzt")
    check(runner.build_matches("h: Grüß Gott, Österreich")[0][1] == "Hermes fragen: Grüß Gott, Österreich",
          "Umlaute bleiben im Treffer-Text")
    check(runner.build_matches("hermes") == [] and runner.build_matches("") == [], "leere Frage: kein Treffer")
    check(runner.build_matches("dolphin") == [], "fremde Eingabe: kein Treffer")
    long_q = "Erkläre mir " + "sehr " * 60 + "ausführlich"
    mid, text = runner.build_matches("hermes " + long_q)[0][:2]
    check(len(text) <= len("Hermes fragen: ") + runner.TITLE_MAX_CHARS and text.endswith("…"),
          "lange Frage wird im Text gekürzt")
    check(runner.question_from_match_id(mid) == long_q, "lange Frage bleibt in der ID vollständig")
    ids = [a[0] for a in runner.ACTIONS]
    check(ids == [runner.ACTION_LOOKUP] and all(len(a) == 3 for a in runner.ACTIONS), "Aktionen im Format (id, Text, Symbol)")


def test_run(runner):
    asked, looked = [], []
    tokens = []
    r = runner.Runner(asked.append, looked.append, tokens.append)
    mid = r.match("hermes Starte Kate")[0][0]
    check(r.run(mid, "") is True and asked == ["Starte Kate"] and looked == [], "Enter schickt die Frage ins Fenster")
    check(r.run(mid, runner.ACTION_LOOKUP) is True and looked == ["Starte Kate"], "„Nur nachschlagen“ fragt still")
    check(r.run("fremd", "") is False and r.run(runner.MATCH_ID_PREFIX + "  ", "") is False and len(asked) == 1,
          "unbekannte oder leere ID tut nichts")
    r.set_activation_token("tok-1")
    check(tokens == ["tok-1"], "Aktivierungs-Token wird weitergereicht")
    cfg = r.config()
    check(re.search(cfg["MatchRegex"], "hermes x") is not None, "Config liefert MatchRegex")


def test_pending(runner):
    now = [0.0]
    ready = [False]
    sent, given_up = [], []
    p = runner.PendingAsk(lambda: ready[0], sent.append, given_up.append, timeout=10, clock=lambda: now[0])
    check(p.submit("Frage 1") is False and p.waiting, "Frage wartet, solange Hermes nicht bereit ist")
    now[0] = 5
    check(p.submit("Frage 2") is False and p.question == "Frage 2", "neuere Frage ersetzt die wartende")
    ready[0] = True
    check(p.tick() is True and sent == ["Frage 2"] and not p.waiting, "Frage geht los, sobald Hermes bereit ist")
    check(p.submit("sofort") is True and sent[-1] == "sofort", "bereit: Frage geht sofort")
    ready[0] = False
    p.submit("zu spät")
    now[0] = 100
    p.tick()
    check(given_up == ["zu spät"] and not p.waiting, "nach der Frist aufgegeben, Frage an give_up")


# ---- Nachschlagen ---------------------------------------------------------------
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
        self.runs.append((sid, text))
        return "run-1"

    def events(self, run_id):
        yield from self._events

    def approve(self, run_id, choice, request_id=""):
        self.approvals.append((choice, request_id))
        return {}

    def stop(self, run_id):
        self.stopped.append(run_id)
        return {}


def test_lookup(runner, hc):
    c = FakeClient([{"event": "message.delta", "delta": "Es ist "}, {"event": "message.delta", "delta": "12 Uhr."},
                    {"event": "run.completed", "output": "Es ist 12 Uhr. MEDIA:/tmp/nicht-da.png"}])
    split = hc.split_media_tags if hc is not None else None
    ok, text = runner.lookup_answer(c, "Wie spät?", split_media=split)
    check(ok and text.startswith("Es ist 12 Uhr."), "Nachschlagen liefert die Antwort")
    if split is not None:
        check("MEDIA:" not in text, "MEDIA-Tags verschwinden aus der Benachrichtigung")
    check(c.sessions and c.sessions[0].startswith(runner.LOOKUP_SESSION + "-"), "eigenes Nachschlage-Gespräch je Tag")
    check(c.runs == [(c.sessions[0], "Wie spät?")], "Frage geht unverändert an Hermes")

    c = FakeClient([{"event": "approval.request", "request_id": "r1", "command": "rm -rf ~/x"},
                    {"event": "run.completed", "output": ""}])
    ok, text = runner.lookup_answer(c, "Räum auf")
    check(ok and c.approvals == [("deny", "r1")] and "Freigabe" in text, "Freigabe beim Nachschlagen: abgelehnt, Hinweis im Text")

    c = FakeClient([{"event": "run.failed", "error": "kein Modell"}])
    ok, text = runner.lookup_answer(c, "x")
    check(not ok and "kein Modell" in text, "abgebrochener Run meldet den Grund")

    ok, text = runner.lookup_answer(FakeClient([], fail_start=True), "x")
    check(not ok and "nicht erreichbar" in text, "Gateway aus: verständlicher Fehler")

    now = [0.0]

    def slow_events():
        for i in range(5):
            now[0] += 100
            yield {"event": "message.delta", "delta": "."}

    c = FakeClient(slow_events())
    ok, text = runner.lookup_answer(c, "x", timeout=150, clock=lambda: now[0])
    check(not ok and c.stopped == ["run-1"], "Frist überschritten: Run wird gestoppt")


# ---- Drahtformat ----------------------------------------------------------------
def test_wire(runner, dp):
    r = runner.Runner(lambda q: None, lambda q: None)
    call = dp.encode_message(dp.METHOD_CALL, 7, {dp.F_PATH: "/runner", dp.F_INTERFACE: "org.kde.krunner1",
                                                 dp.F_MEMBER: "Match", dp.F_SENDER: ":1.42"},
                             "s", ("h: Öffne die Systemeinstellungen",))
    msg, used = dp.decode_message(call + b"rest")
    check(msg is not None and used == len(call) and msg.body == ["h: Öffne die Systemeinstellungen"],
          "Methodenaufruf hin und zurück, Rest bleibt im Puffer")
    check(dp.decode_message(call[:-3]) == (None, 0), "unvollständige Nachricht wartet auf mehr Daten")
    sig, body = r.handle(msg)
    check(sig == "a(sssida{sv})", "Match antwortet mit a(sssida{sv})")
    raw = dp.encode_message(dp.METHOD_RETURN, 8, {dp.F_REPLY_SERIAL: 7, dp.F_DESTINATION: ":1.42"}, sig, body)
    back, _ = dp.decode_message(raw)
    got = back.body[0][0]
    check(back.signature == "a(sssida{sv})" and back.reply_serial == 7, "Antwort trägt Signatur und Bezug")
    check(got[1] == "Hermes fragen: Öffne die Systemeinstellungen" and got[3] == 100 and got[4] == 1.0,
          "Treffer übersteht das Drahtformat (Text, Relevanz)")
    props = got[5]
    check(props["actions"] == dp.Variant("as", ["lookup"]) and props["category"] == dp.Variant("s", "Hermes"),
          "Eigenschaften als a{sv} mit richtigen Typen")
    for member, sig_in, args, want in [("Actions", "", (), "a(sss)"), ("Config", "", (), "a{sv}"),
                                       ("Teardown", "", (), ""), ("Run", "ss", ("x", ""), "")]:
        m = dp.Message(dp.METHOD_CALL, 1, {dp.F_PATH: "/runner", dp.F_INTERFACE: runner.INTERFACE,
                                           dp.F_MEMBER: member, dp.F_SIGNATURE: sig_in}, list(args))
        check(r.handle(m)[0] == want, f"{member} antwortet mit {want or 'leer'}")
    bad = dp.Message(dp.METHOD_CALL, 1, {dp.F_PATH: "/runner", dp.F_INTERFACE: runner.INTERFACE,
                                         dp.F_MEMBER: "Gibtsnicht"}, [])
    try:
        r.handle(bad)
        check(False, "unbekannte Methode wird abgelehnt")
    except dp.DBusError as exc:
        check(exc.name.endswith("UnknownMethod"), "unbekannte Methode wird abgelehnt")
    # Ausrichtung: Struktur mit d nach i verlangt Auffüllung auf 8
    data = dp.marshal("a(sssida{sv})", ([("a", "b", "c", 1, 0.5, {})],))
    check(dp.unmarshal("a(sssida{sv})", data) == [[("a", "b", "c", 1, 0.5, {})]], "Ausrichtung von d und a{sv}")
    check(dp.socket_path_from_address("unix:path=/run/user/1000/bus,guid=abc") == "/run/user/1000/bus",
          "Bus-Adresse unix:path")
    check(dp.socket_path_from_address("unix:abstract=/tmp/dbus-X%2dY,guid=1") == "\0/tmp/dbus-X-Y",
          "Bus-Adresse unix:abstract mit Maskierung")


# ---- Desktop-Datei ---------------------------------------------------------------
REQUIRED = ["Type", "Name", "Comment", "Icon", "X-KDE-PluginInfo-Name", "X-KDE-PluginInfo-EnabledByDefault",
            "X-Plasma-API", "X-Plasma-DBusRunner-Service", "X-Plasma-DBusRunner-Path"]


def test_desktop(runner, path):
    check(path.is_file(), f"{path} vorhanden")
    if not path.is_file():
        return
    cp = configparser.ConfigParser(interpolation=None, strict=True)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    check(cp.has_section("Desktop Entry"), "Abschnitt [Desktop Entry]")
    if not cp.has_section("Desktop Entry"):
        return
    d = cp["Desktop Entry"]
    for key in REQUIRED:
        check(bool(d.get(key, "").strip()), f"Pflichtschlüssel {key}")
    check(d.get("Type") == "Service", "Type=Service")
    check(d.get("X-Plasma-API") == "DBus", "X-Plasma-API=DBus (Config nicht nötig, Filter steht in der Datei)")
    service = d.get("X-Plasma-DBusRunner-Service", "")
    check(service.endswith("*") and service[:-1] == runner.SERVICE,
          "Dienstname mit * passt zu runner.SERVICE (kein D-Bus-Aufruf, solange das Symbol nicht läuft)")
    check(d.get("X-Plasma-DBusRunner-Path") == runner.OBJECT_PATH, "Objektpfad passt zu runner.OBJECT_PATH")
    check(d.get("X-KDE-PluginInfo-EnabledByDefault") == "true", "standardmäßig eingeschaltet")
    check(d.get("X-Plasma-Request-Actions-Once") == "true", "Aktionen nur einmal abfragen")
    regex = d.get("X-Plasma-Runner-Match-Regex", "")
    # KConfig liest \s als Leerzeichen; ein Backslash würde den Filter still verändern
    check(regex and "\\" not in regex, "Match-Regex ohne Backslash (KConfig-Maskierung)")
    try:
        rx = re.compile(regex)
    except re.error as exc:
        check(False, f"Match-Regex kompiliert ({exc})")
        return
    samples = ["hermes Frage", "Hermes: Frage", "hermes, Frage", "h: Frage", "H:Frage", "h : Frage",
               "hermes", "h:", "hermesfoo", "firefox", "hallo h: x"]
    for q in samples:
        # Was die Erkennung annimmt, muss KRunner durchlassen
        if runner.parse_query(q) is not None:
            check(rx.search(q) is not None, f"Filter lässt {q!r} durch")
    for q in ["hermesfoo", "firefox", "hallo h: x"]:
        check(rx.search(q) is None, f"Filter hält {q!r} von Hermes fern")
    min_letters = int(d.get("X-Plasma-Runner-Min-Letter-Count", "0"))
    check(0 < min_letters <= len("h:x"), "Mindestlänge lässt die kürzeste Frage durch")
    raw = path.read_text(encoding="utf-8")
    check("\r" not in raw, "Zeilenenden LF")
    if shutil.which("desktop-file-validate"):
        res = subprocess.run(["desktop-file-validate", str(path)], capture_output=True, text=True)
        check(res.returncode == 0, f"desktop-file-validate {res.stdout.strip()} {res.stderr.strip()}".strip())
    else:
        print("SKIP  desktop-file-validate fehlt")


# ---- Echter Bus -------------------------------------------------------------------
def test_live_bus(runner, dp):
    if not (shutil.which("dbus-daemon") and shutil.which("dbus-send")):
        print("SKIP  dbus-daemon oder dbus-send fehlt, kein Test gegen einen echten Bus")
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
        asked, looked = [], []
        r = runner.Runner(asked.append, looked.append)
        conn = dp.BusConnection(address)
        conn.export(runner.OBJECT_PATH, r.handle)
        check(conn.unique_name.startswith(":"), f"Hello: eindeutiger Name {conn.unique_name}")
        check(conn.request_name(runner.SERVICE), f"Name {runner.SERVICE} angemeldet")
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                rd, _, _ = select.select([conn.fileno()], [], [], 0.1)
                if rd and not conn.read_ready():
                    return

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address)

        def send(*args):
            return subprocess.run(["dbus-send", "--session", "--print-reply", f"--dest={runner.SERVICE}",
                                   runner.OBJECT_PATH, *args], capture_output=True, text=True, env=env, timeout=10)

        res = send("org.kde.krunner1.Match", "string:hermes Wie spät ist es in Köln?")
        out = res.stdout
        check(res.returncode == 0, "Match über den Bus" + (f" ({res.stderr.strip()})" if res.returncode else ""))
        check('string "Hermes fragen: Wie spät ist es in Köln?"' in out and "int32 100" in out and "double 1" in out,
              "Match-Antwort über den Bus: Text, Kategorie-Relevanz, Relevanz")
        res = send("org.kde.krunner1.Match", "string:thunderbird")
        check(res.returncode == 0 and "struct" not in res.stdout, "fremde Eingabe über den Bus: leere Liste")
        res = send("org.kde.krunner1.Actions")
        check(res.returncode == 0 and 'string "Nur nachschlagen"' in res.stdout, "Actions über den Bus")
        res = send("org.kde.krunner1.Run", "string:" + runner.MATCH_ID_PREFIX + "Grüße", "string:")
        check(res.returncode == 0 and asked == ["Grüße"], "Run über den Bus schickt die Frage ins Fenster")
        res = send("org.kde.krunner1.Run", "string:" + runner.MATCH_ID_PREFIX + "Nachschlagen", "string:lookup")
        check(res.returncode == 0 and looked == ["Nachschlagen"], "Run mit lookup über den Bus")
        res = send("org.freedesktop.DBus.Introspectable.Introspect")
        check(res.returncode == 0 and "a(sssida{sv})" in res.stdout, "Introspect beschreibt org.kde.krunner1")
        res = send("org.kde.krunner1.Gibtsnicht")
        check(res.returncode != 0 and "UnknownMethod" in res.stderr, "unbekannte Methode: Fehlerantwort, Dienst läuft weiter")
        res = send("org.kde.krunner1.Match", "string:h: noch da?")
        check(res.returncode == 0 and "noch da?" in res.stdout, "Dienst antwortet nach einem Fehler weiter")
        stop.set()
        t.join(2)
        conn.close()
    finally:
        daemon.terminate()
        try:
            daemon.wait(5)
        except subprocess.TimeoutExpired:
            daemon.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tray-dir", default=str(DEFAULT_TRAY))
    ap.add_argument("--desktop-file", default=str(DEFAULT_DESKTOP))
    args = ap.parse_args()
    sys.path.insert(0, args.tray_dir)
    import dbus_peer as dp
    import runner
    try:
        import hermes_client as hc
    except Exception:
        hc = None
    test_parse(runner)
    test_matches(runner)
    test_run(runner)
    test_pending(runner)
    test_lookup(runner, hc)
    test_wire(runner, dp)
    test_desktop(runner, Path(args.desktop_file))
    test_live_bus(runner, dp)
    if failures:
        print(f"\n{len(failures)} Prüfung(en) fehlgeschlagen")
        return 1
    print("\nrunner-check: alles sauber")
    return 0


if __name__ == "__main__":
    sys.exit(main())
