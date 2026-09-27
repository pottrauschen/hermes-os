"""hermes-os -- „Was sehe ich hier?": Bildschirmausschnitt wählen und Hermes fragen.

Meta+Umschalt+H (kglobalaccel-Datei hermes-os-sehen.desktop) ruft
`hermes-os-tray --look`, das über den lokalen Socket bei der laufenden Instanz
landet. Die öffnet Spectacles Auswahlrahmen im Hintergrund (kein Fenster, keine
eigene Benachrichtigung, Datei in den Cache des Leisten-Symbols) und dann:

- Fenster zu: Bild und Frage gehen still an Hermes, in einem eigenen Gespräch je
  Tag wie beim Nachschlagen aus KRunner (runner.lookup_answer mit Bild). Die
  Antwort kommt als Benachrichtigung mit dem Knopf „Im Chat besprechen", der
  Ausschnitt, Frage und Antwort ins Fenster holt und den Ausschnitt für die
  Nachfrage anhängt.
- Fenster offen (oder der Knopf im Fenster): der Ausschnitt landet als Anhang,
  die Frage steht im Eingabefeld und lässt sich ändern, bevor Enter sie schickt.

Die Logik (Befehl, Ablauf, Sitzung) kommt ohne Qt aus und ist in
tests/sehen-hoeren-check.py gegen einen nachgebauten Client geprüft; install()
hängt sie an das Leisten-Symbol und stellt `look` für Main.qml bereit. Aufnahme,
Kodieren und Warten auf Hermes laufen in einem Arbeitsthread.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

SHORTCUT = "Meta+Shift+H"
DEFAULT_QUESTION = ("Was sehe ich hier? Beschreibe kurz, was auf diesem Bildschirmausschnitt zu sehen ist, "
                    "und sag, was daran wichtig oder auffällig ist.")
LOOK_SESSION = "hermes-os-look"     # plus Datum: ein Gespräch je Tag, wie beim Nachschlagen
CAPTURE_TIMEOUT = 180               # Sekunden, bis die Auswahl als abgebrochen gilt
NOTIFY_TITLE = "Hermes: Was sehe ich hier?"
ACTION_DISCUSS = "chat"
DISCUSS_LABEL = "Im Chat besprechen"


def capture_command(path: str) -> List[str]:
    """Spectacle im Hintergrund mit Auswahlrahmen: eigene Instanz (-i, sonst reicht
    Spectacle den Aufruf an ein schon offenes Spectacle weiter und endet sofort),
    kein Hauptfenster (-b), Bereich wählen (-r), keine eigene Benachrichtigung (-n),
    Datei (-o). Enter oder Doppelklick nimmt die Auswahl an, Escape bricht ab:
    dann Exit 0 ohne Datei."""
    return ["spectacle", "--new-instance", "--background", "--region", "--nonotify", "--output", path]


def capture_region(path: str, run=subprocess.run, which=shutil.which, timeout: float = CAPTURE_TIMEOUT) -> Tuple[str, str]:
    """Ausschnitt aufnehmen. Liefert ("ok", Pfad), ("cancelled", "") wenn der Nutzer
    abgebrochen hat (Escape: Spectacle endet ohne Datei), oder ("error", Text)."""
    if which("spectacle") is None:
        return "error", "Spectacle ist nicht installiert."
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)
    except OSError as exc:
        return "error", f"Cache nicht beschreibbar: {exc}"
    try:
        proc = run(capture_command(path), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "cancelled", ""
    except OSError as exc:
        return "error", f"Spectacle startet nicht: {exc}"
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return "ok", path
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip() if isinstance(proc.stderr, bytes) else str(proc.stderr or "")
        tail = err.splitlines()[-1][:200] if err else f"Exit {proc.returncode}"
        return "error", f"Spectacle: {tail}"
    return "cancelled", ""


def look_session_id(day: Optional[str] = None) -> str:
    return f"{LOOK_SESSION}-{day or time.strftime('%Y%m%d')}"


def capture_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, "ausschnitt-" + time.strftime("%Y%m%d-%H%M%S") + ".png")


class LookFlow:
    """Der Ablauf ohne Qt. Alles, was Desktop oder Fenster berührt, kommt als Funktion:
    capture(path) -> (status, detail); encode(path) -> data-URL; make_client();
    lookup(client, question, session_id, images) -> (ok, text); window_visible() -> bool;
    attach(path, question) (Fenster offen); notify_actions(title, body, actions, on_choice, icon);
    notify(title, body); discuss(path, question, answer) (Knopf in der Benachrichtigung)."""

    def __init__(self, cache_dir: str, capture, encode, make_client, lookup, window_visible,
                 attach, notify_actions, notify, discuss, clock=time.strftime):
        self.cache_dir = cache_dir
        self._capture = capture
        self._encode = encode
        self._make_client = make_client
        self._lookup = lookup
        self._window_visible = window_visible
        self._attach = attach
        self._notify_actions = notify_actions
        self._notify = notify
        self._discuss = discuss
        self.busy = False
        self._lock = threading.Lock()

    def run(self, question: str = "", to_window: Optional[bool] = None) -> str:
        """Ein Durchlauf; liefert, wie er endete: attached, answered, cancelled, error, busy."""
        with self._lock:
            if self.busy:
                return "busy"
            self.busy = True
        try:
            return self._run(question, to_window)
        finally:
            self.busy = False

    def _run(self, question: str, to_window: Optional[bool]) -> str:
        question = " ".join((question or "").split()) or DEFAULT_QUESTION
        path = capture_path(self.cache_dir)
        status, detail = self._capture(path)
        if status == "cancelled":
            return "cancelled"
        if status != "ok":
            self._notify("Kein Bildschirmausschnitt", detail)
            return "error"
        if to_window is None:
            to_window = bool(self._window_visible())
        if to_window:
            self._attach(path, question)
            return "attached"
        try:
            data_url = self._encode(path)
        except (ValueError, OSError) as exc:
            self._notify("Kein Bildschirmausschnitt", str(exc))
            return "error"
        ok, answer = self._lookup(self._make_client(), question, look_session_id(), [data_url])
        if not ok:
            self._notify("Hermes: Nachschlagen fehlgeschlagen", answer)
            return "error"

        def on_choice(choice: str) -> None:
            if choice == ACTION_DISCUSS:
                self._discuss(path, question, answer)

        self._notify_actions(NOTIFY_TITLE, answer, [(ACTION_DISCUSS, DISCUSS_LABEL)], on_choice, path)
        return "answered"


# ---- Anschluss an das Leisten-Symbol --------------------------------------------------------------
def install(backend, get_window: Callable[[], Any], show_window: Callable[[], None], make_client: Callable[[], Any],
            encode_image: Callable[[str], str], cache_dir: str, split_media: Optional[Callable] = None):
    """`look` für Main.qml und den Socket-Befehl `look [Frage]`. Gibt das LookBackend zurück.
    get_window liefert das Fenster, das erst nach dem Laden von Main.qml existiert."""
    from PySide6.QtCore import QObject, Property, Signal, Slot, Qt
    import desktop
    import runner

    class LookBackend(QObject):
        busyChanged = Signal()
        _discussRequested = Signal(str, str, str)
        _attachRequested = Signal(str, str)
        _busy = Signal(bool)

        def __init__(self):
            super().__init__()
            self._is_busy = False
            queued = Qt.ConnectionType.QueuedConnection
            self._discussRequested.connect(self._discuss, queued)
            self._attachRequested.connect(self._attach, queued)
            self._busy.connect(self._set_busy, queued)
            self._flow = LookFlow(
                cache_dir, capture_region, encode_image, make_client,
                lambda client, q, sid, images: runner.lookup_answer(client, q, sid, split_media=split_media, images=images),
                lambda: False,      # ob das Fenster offen ist, entscheidet start() im GUI-Thread
                lambda path, q: self._attachRequested.emit(path, q),
                desktop.notify_actions, desktop.notify,
                lambda path, q, a: self._discussRequested.emit(path, q, a))

        @Property(bool, constant=True)
        def available(self):
            return shutil.which("spectacle") is not None

        @Property(bool, notify=busyChanged)
        def busy(self):
            return self._is_busy

        @Property(str, constant=True)
        def shortcutText(self):
            return SHORTCUT

        def _set_busy(self, value):
            if value != self._is_busy:
                self._is_busy = value
                self.busyChanged.emit()

        @Slot()
        def capture(self):
            """Knopf im Fenster: Ausschnitt wählen, als Anhang ins Fenster."""
            self.start("", to_window=True)

        def start(self, question: str = "", to_window: Optional[bool] = None):
            """Kürzel oder Menü: Fenster offen heißt anhängen, sonst still fragen.
            Läuft im GUI-Thread; nur hier wird das Fenster befragt."""
            if self._flow.busy:
                return
            if to_window is None:
                try:
                    to_window = bool(get_window().isVisible())
                except Exception:
                    to_window = False

            def work():
                self._busy.emit(True)
                try:
                    self._flow.run(question, to_window)
                finally:
                    self._busy.emit(False)

            threading.Thread(target=work, name="hermes-look", daemon=True).start()

        def _attach(self, path, question):
            backend.attachFiles([path])
            try:
                get_window().typeInput(question)
            except Exception:
                pass
            show_window()

        def _discuss(self, path, question, answer):
            backend.discussAnswer(question, answer, [path])

    return LookBackend()
