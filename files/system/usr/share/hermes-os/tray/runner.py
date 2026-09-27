"""hermes-os -- KRunner-Runner „Hermes fragen“ im Leisten-Symbol.

Alt+Leertaste, dann `hermes <Frage>` oder kurz `h: <Frage>`: KRunner zeigt
„Hermes fragen: <Frage>“. Enter öffnet das Kontor und schickt die Frage
ab; die Aktion „Nur nachschlagen“ fragt Hermes in einem eigenen Gespräch und
liefert die Antwort als Benachrichtigung.

KRunner spricht D-Bus-Runner über org.kde.krunner1 an (Match, Actions, Run,
Teardown, SetActivationToken; Config nur bei X-Plasma-API=DBus2). Angemeldet
wird der Runner durch /usr/share/krunner/dbusplugins/hermes-os.desktop; der
Dienstname dort endet auf `*`, dann ruft KRunner nur, solange das Leisten-Symbol
den Namen hält, und versucht keine D-Bus-Aktivierung.

Aufbau: Die Logik (Präfix, Treffer, Run) kommt ohne Qt und ohne Bus aus und ist
in tests/runner-check.py geprüft. Den Draht zum Bus macht dbus_peer.py (warum
nicht QtDBus, steht dort). install() hängt beides an die Qt-Ereignisschleife des
Leisten-Symbols.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

SERVICE = "io.github.pottrauschen.hermesos.tray"
OBJECT_PATH = "/runner"
INTERFACE = "org.kde.krunner1"
MATCH_ID_PREFIX = "frage:"
ACTION_LOOKUP = "lookup"
LOOKUP_SESSION = "hermes-os-krunner"   # plus Datum: ein Nachschlage-Gespräch je Tag
LOOKUP_TIMEOUT = 180          # Sekunden bis „Nur nachschlagen“ aufgibt
PENDING_TIMEOUT = 90          # so lange wartet eine Frage aus KRunner, bis das Fenster senden kann
NOTIFY_MAX_CHARS = 900        # Benachrichtigungen werden sonst abgeschnitten oder unlesbar
TITLE_MAX_CHARS = 120

# Kategorie-Relevanz wie KRunner::QueryMatch::CategoryRelevance (KF6): Highest = 100
CATEGORY_HIGHEST = 100

# `hermes` mit Leerzeichen, Doppelpunkt oder Komma dahinter, oder `h:`; Groß- und
# Kleinschreibung egal. Die Frage bleibt, wie sie getippt wurde (Umlaute inklusive).
QUERY_RE = re.compile(r"^\s*(?:hermes(?:\s*[:,]\s*|\s+)|h\s*:\s*)(?P<question>.*)$", re.IGNORECASE | re.DOTALL)

ACTIONS: List[Tuple[str, str, str]] = [(ACTION_LOOKUP, "Nur nachschlagen", "system-search")]

INTROSPECTION = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.kde.krunner1">
    <method name="Teardown"/>
    <method name="Config"><arg name="config" type="a{sv}" direction="out"/></method>
    <method name="Actions"><arg name="matches" type="a(sss)" direction="out"/></method>
    <method name="SetActivationToken"><arg name="token" type="s" direction="in"/></method>
    <method name="Run"><arg name="matchId" type="s" direction="in"/><arg name="actionId" type="s" direction="in"/></method>
    <method name="Match"><arg name="query" type="s" direction="in"/><arg name="matches" type="a(sssida{sv})" direction="out"/></method>
  </interface>
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect"><arg name="xml_data" type="s" direction="out"/></method>
  </interface>
  <interface name="org.freedesktop.DBus.Peer">
    <method name="Ping"/>
  </interface>
</node>
"""


# ---- Logik ohne Qt und ohne Bus ------------------------------------------------
def parse_query(query: str) -> Optional[str]:
    """Frage aus der KRunner-Eingabe, oder None, wenn sie nicht an Hermes geht oder leer ist."""
    m = QUERY_RE.match(query or "")
    if not m:
        return None
    question = m.group("question").strip()
    return question or None


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def build_matches(query: str) -> List[Tuple[str, str, str, int, float, Dict[str, Any]]]:
    """Treffer im Format von org.kde.krunner1.Match: (id, text, icon, Kategorie-Relevanz,
    Relevanz 0..1, Eigenschaften)."""
    question = parse_query(query)
    if question is None:
        return []
    props: Dict[str, Any] = {
        "subtext": "Enter: im Kontor fragen",
        "category": "Hermes",
        "actions": [ACTION_LOOKUP],
    }
    return [(MATCH_ID_PREFIX + question, "Hermes fragen: " + shorten(question, TITLE_MAX_CHARS),
             "hermes-os", CATEGORY_HIGHEST, 1.0, props)]


def question_from_match_id(match_id: str) -> Optional[str]:
    if not match_id.startswith(MATCH_ID_PREFIX):
        return None
    question = match_id[len(MATCH_ID_PREFIX):].strip()
    return question or None


class Runner:
    """Antwortet auf org.kde.krunner1. `ask(question)` schickt ins Kontor,
    `lookup(question)` fragt still nach, `activation(token)` nimmt das
    XDG-Aktivierungs-Token entgegen, bevor Run kommt."""

    def __init__(self, ask: Callable[[str], None], lookup: Callable[[str], None],
                 activation: Callable[[str], None] = lambda token: None):
        self._ask = ask
        self._lookup = lookup
        self._activation = activation

    def match(self, query: str):
        return build_matches(query)

    def actions(self):
        return list(ACTIONS)

    def config(self) -> Dict[str, Any]:
        # Nur bei X-Plasma-API=DBus2 abgefragt; die Desktop-Datei setzt denselben Filter.
        return {"MatchRegex": "(?i)^ *(hermes[ :,]|h *:)", "MinLetterCount": 3}

    def run(self, match_id: str, action_id: str) -> bool:
        question = question_from_match_id(match_id)
        if question is None:
            return False
        if action_id == ACTION_LOOKUP:
            self._lookup(question)
        else:
            self._ask(question)
        return True

    def set_activation_token(self, token: str) -> None:
        self._activation(token)

    def teardown(self) -> None:
        pass  # nichts zwischengespeichert

    def handle(self, msg) -> Tuple[str, tuple]:
        """Eine Nachricht von dbus_peer beantworten: (Signatur, Werte)."""
        import dbus_peer as dp
        iface, member, args = msg.interface, msg.member, msg.body
        if iface == "org.freedesktop.DBus.Introspectable" and member == "Introspect":
            return "s", (INTROSPECTION,)
        if iface not in ("", INTERFACE):
            raise dp.DBusError("org.freedesktop.DBus.Error.UnknownInterface", f"unbekannt: {iface}")
        if member == "Match" and msg.signature == "s":
            return "a(sssida{sv})", (self.match(args[0]),)
        if member == "Actions":
            return "a(sss)", (self.actions(),)
        if member == "Run" and msg.signature == "ss":
            self.run(args[0], args[1])
            return "", ()
        if member == "SetActivationToken" and msg.signature == "s":
            self.set_activation_token(args[0])
            return "", ()
        if member == "Teardown":
            self.teardown()
            return "", ()
        if member == "Config":
            return "a{sv}", (self.config(),)
        raise dp.DBusError("org.freedesktop.DBus.Error.UnknownMethod", f"{member}({msg.signature}) unbekannt")


# ---- Wartende Frage ------------------------------------------------------------------
class PendingAsk:
    """Hält eine Frage aus KRunner, bis das Fenster senden kann (Gateway bereit,
    Verlauf geladen, kein Run offen). `can_send`, `send`, `give_up` kommen vom
    Leisten-Symbol; `tick()` ruft ein Timer."""

    def __init__(self, can_send: Callable[[], bool], send: Callable[[str], None],
                 give_up: Callable[[str], None], timeout: float = PENDING_TIMEOUT,
                 clock: Callable[[], float] = time.monotonic):
        self._can_send = can_send
        self._send = send
        self._give_up = give_up
        self._timeout = timeout
        self._clock = clock
        self.question: Optional[str] = None
        self._since = 0.0

    def submit(self, question: str) -> bool:
        """True, wenn gleich gesendet; sonst wartet sie (eine neuere ersetzt eine ältere)."""
        self.question, self._since = question, self._clock()
        return self.tick()

    def tick(self) -> bool:
        if self.question is None:
            return False
        if self._can_send():
            q, self.question = self.question, None
            self._send(q)
            return True
        if self._clock() - self._since > self._timeout:
            q, self.question = self.question, None
            self._give_up(q)
        return False

    @property
    def waiting(self) -> bool:
        return self.question is not None


# ---- Nur nachschlagen ---------------------------------------------------------------
def lookup_session_id(day: Optional[str] = None) -> str:
    return f"{LOOKUP_SESSION}-{day or time.strftime('%Y%m%d')}"


def lookup_answer(client, question: str, session_id: Optional[str] = None,
                  timeout: float = LOOKUP_TIMEOUT, split_media: Optional[Callable] = None,
                  images: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Frage in einem eigenen Gespräch stellen und die Antwort als Text holen.
    Braucht Hermes eine Freigabe, lehnt der Nachschlag ab: ohne Fenster gibt es
    niemanden, der sie bewusst erteilt. Liefert (ok, Text oder Fehler). `images`
    sind data-URLs, die mitgehen („Was sehe ich hier?", tray/screenshot.py).

    Der Strom wird in einem eigenen Thread gelesen, damit die Frist auch greift,
    wenn der Server nur `: keepalive` schickt (parse_sse liefert die nicht aus).
    Endet der Strom ohne run.completed, gilt das als Abbruch, nicht als Antwort."""
    session_id = session_id or lookup_session_id()
    try:
        client.ensure_session(session_id)
        run_id = client.start_run(session_id, question, images) if images else client.start_run(session_id, question)
    except Exception as exc:
        return False, f"Hermes nicht erreichbar: {exc}"
    state: Dict[str, Any] = {"text": "", "denied": False, "error": None, "done": False}

    def consume():
        try:
            for event in client.events(run_id):
                name = str(event.get("event") or "")
                if name == "message.delta":
                    state["text"] += str(event.get("delta") or "")
                elif name == "approval.request":
                    state["denied"] = True
                    try:
                        client.approve(run_id, "deny", str(event.get("request_id") or ""))
                    except Exception:
                        pass
                elif name == "run.completed":
                    output = event.get("output")
                    if isinstance(output, str) and output.strip():
                        state["text"] = output
                    state["done"] = True
                    return
                elif name in ("run.failed", "run.cancelled", "run.interrupted"):
                    reason = str(event.get("turn_exit_reason") or event.get("error") or name)
                    state["error"] = f"Hermes hat abgebrochen: {reason}"
                    return
            state["error"] = "Verbindung abgebrochen, bevor Hermes fertig war."
        except Exception as exc:
            state["error"] = f"Verbindung abgebrochen: {exc}"

    reader = threading.Thread(target=consume, name="hermes-lookup-events", daemon=True)
    reader.start()
    reader.join(timeout)
    if reader.is_alive():
        # Der Lese-Thread endet, sobald der Server den gestoppten Run schließt
        try:
            client.stop(run_id)
        except Exception:
            pass
        return False, "Keine Antwort in der Zeit. Im Kontor weiterfragen."
    if not state["done"]:
        return False, state["error"] or "Verbindung abgebrochen, bevor Hermes fertig war."
    text = state["text"]
    if split_media is not None:
        text, _paths = split_media(text)
    text = text.strip()
    if state["denied"]:
        note = "Hermes wollte einen Befehl mit Freigabe ausführen; beim Nachschlagen wird das abgelehnt."
        text = (text + "\n\n" + note) if text else note
    return True, text or "(keine Antwort)"


def notify(title: str, body: str, icon: str = "hermes-os") -> None:
    """Benachrichtigung über notify-send, ohne Shell. KDE deutet im Text einfaches
    HTML, deshalb werden &, < und > maskiert."""
    if shutil.which("notify-send") is None:
        return
    body = shorten_lines(body, NOTIFY_MAX_CHARS)
    body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    try:
        subprocess.Popen(["notify-send", "--app-name=Hermes", f"--icon={icon}", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def shorten_lines(text: str, limit: int) -> str:
    """Wie shorten, aber Zeilenumbrüche bleiben."""
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def start_lookup(make_client: Callable[[], Any], question: str, split_media: Optional[Callable] = None) -> None:
    """Nachschlagen im Hintergrund, Antwort als Benachrichtigung."""
    title = "Hermes: " + shorten(question, 60)

    def work():
        ok, text = lookup_answer(make_client(), question, split_media=split_media)
        notify(title if ok else "Hermes: Nachschlagen fehlgeschlagen", text,
               "hermes-os" if ok else "dialog-warning")

    threading.Thread(target=work, name="hermes-lookup", daemon=True).start()


# ---- Anschluss an das Leisten-Symbol ------------------------------------------------
def install(backend, show_window: Callable[[], None], window, make_client: Callable[[], Any],
            split_media: Optional[Callable] = None):
    """Runner auf dem Sitzungsbus anmelden und an die Qt-Ereignisschleife hängen.
    Gibt das Verbindungsobjekt zurück (am Leben halten) oder None, wenn es nicht ging;
    das Leisten-Symbol läuft dann ohne KRunner weiter."""
    import sys
    from PySide6.QtCore import QMetaObject, QSocketNotifier, QTimer, Q_ARG
    import dbus_peer as dp

    def can_send():
        return backend.state == "ready" and not backend.busy and getattr(backend, "_session_ready", True)

    def give_up(question):
        # Nichts geht verloren: die Frage steht im Eingabefeld, sobald Hermes wieder bereit ist
        try:
            QMetaObject.invokeMethod(window, "typeInput", Q_ARG("QVariant", question))
        except Exception:
            pass
        notify("Hermes ist nicht bereit", "Die Frage aus KRunner steht im Eingabefeld des Kontors.",
               "dialog-information")

    pending = PendingAsk(can_send, backend.send, give_up)
    timer = QTimer()
    timer.setInterval(500)

    def tick():
        pending.tick()
        if not pending.waiting:
            timer.stop()

    timer.timeout.connect(tick)

    def ask(question):
        show_window()
        if not pending.submit(question):
            if pending.waiting:
                timer.start()

    def activation(token):
        # Qt (Wayland) nimmt das Token aus der Umgebung, wenn das Fenster sich aktiviert
        if token:
            os.environ["XDG_ACTIVATION_TOKEN"] = token

    runner = Runner(ask, lambda q: start_lookup(make_client, q, split_media), activation)
    try:
        conn = dp.BusConnection()
        conn.export(OBJECT_PATH, runner.handle)
        if not conn.request_name(SERVICE):
            print(f"hermes-os-tray: D-Bus-Name {SERVICE} ist vergeben, KRunner erreicht diese Instanz nicht",
                  file=sys.stderr)
            conn.close()
            return None
    except (OSError, dp.DBusError, ValueError) as exc:
        print(f"hermes-os-tray: KRunner-Runner nicht angemeldet: {exc}", file=sys.stderr)
        return None

    notifier = QSocketNotifier(conn.fileno(), QSocketNotifier.Type.Read)

    def readable():
        try:
            alive = conn.read_ready()
        except (OSError, ValueError) as exc:
            print(f"hermes-os-tray: D-Bus-Verbindung gestört: {exc}", file=sys.stderr)
            alive = False
        if not alive:
            notifier.setEnabled(False)
            conn.close()

    notifier.activated.connect(readable)
    # Referenzen am Verbindungsobjekt halten, sonst räumt Python Timer und Notifier ab
    conn.qt_refs = (notifier, timer, pending, runner)
    return conn
