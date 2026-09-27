"""hermes-os -- Sprechen mit Hermes aus dem Leisten-Symbol (Push-to-Talk).

Meta+Leertaste gedrückt halten nimmt auf, loslassen stoppt; kurz antippen
schaltet die Aufnahme ein, der nächste Druck aus. Die Aufnahme geht als WAV an
den Sprachhelfer in der Hermes-Venv (tray/voice_worker.py: faster-whisper mit
Modell und Sprache aus ~/.hermes/config.yaml), der erkannte Text geht wie eine
getippte Frage ins Chat-Fenster (backend.send), und die Antwort wird mit Piper
vorgelesen (Stimme aus tts.piper). Während Aufnahme und Sprechen zeigt das
Leisten-Symbol einen eigenen Zustand; drückt man das Kürzel, während Hermes
spricht, verstummt er und hört zu.

Aufbau: Die Logik (Zustandsautomat PushToTalk, Aufnahmebefehl, Config, Text
fürs Vorlesen, Sprechen mit dem Helfer) kommt ohne Qt aus und ist in
tests/sehen-hoeren-check.py geprüft. install() hängt sie an die
Qt-Ereignisschleife des Leisten-Symbols, meldet das Kürzel bei KGlobalAccel
an (tray/desktop.py, mit Drücken und Loslassen) und stellt `voice` für Main.qml
bereit. Schwere Arbeit (Aufnahme beenden, Erkennung, Synthese, Abspielen) läuft
in Arbeitsthreads oder im Helferprozess, nie im GUI-Thread.

Aufnahme: pw-record (PipeWire) oder parecord, 16 kHz, mono, 16 Bit; ohne
Mikrofon eine klare Meldung, kein Absturz. Abspielen: pw-play, paplay oder
aplay, was da ist.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SHORTCUT = "Meta+Space"
ACTION_ID = "push-to-talk"
ACTION_LABEL = "Mit Hermes sprechen (halten oder antippen)"
MIN_HOLD_SECONDS = 0.35        # kürzer gedrückt heißt Antippen: Aufnahme bis zum nächsten Druck
MAX_RECORD_SECONDS = 90
MIN_RECORD_SECONDS = 0.3       # darunter gilt die Aufnahme als versehentlich
SAMPLE_RATE = 16000
STOP_GRACE_SECONDS = 3.0       # so lange darf der Rekorder die Datei noch abschließen
TRANSCRIBE_TIMEOUT = 180       # beim ersten Mal lädt der Helfer das Modell herunter
SPEAK_TIMEOUT = 180
MAX_SPEAK_CHARS = 1500         # längere Antworten werden nur bis hierhin vorgelesen
WORKER_START_TIMEOUT = 20

VENV_PYTHON = os.environ.get("HERMES_OS_VOICE_PYTHON", "/usr/lib/hermes-agent/.venv/bin/python")
WORKER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_worker.py")

STATES = ("idle", "recording", "transcribing", "asking", "speaking")
STATE_TEXT = {
    "idle": "",
    "recording": "Hermes hört zu …",
    "transcribing": "Hermes versteht …",
    "asking": "Hermes denkt nach …",
    "speaking": "Hermes spricht …",
}
STATE_ICON = {"recording": "hermes-os-tray-listening", "speaking": "hermes-os-tray-speaking"}

RECORDERS: List[Tuple[str, Callable[[str], List[str]]]] = [
    ("pw-record", lambda path: ["pw-record", "--rate", str(SAMPLE_RATE), "--channels", "1", "--format", "s16", path]),
    ("parecord", lambda path: ["parecord", f"--rate={SAMPLE_RATE}", "--channels=1", "--format=s16le",
                               "--file-format=wav", path]),
    ("arecord", lambda path: ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", path]),
]
PLAYERS: List[Tuple[str, Callable[[str], List[str]]]] = [
    ("pw-play", lambda path: ["pw-play", path]),
    ("paplay", lambda path: ["paplay", path]),
    ("aplay", lambda path: ["aplay", "-q", path]),
    ("ffplay", lambda path: ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]),
]


# ---- Werkzeuge -------------------------------------------------------------------------
def find_tool(candidates, which=shutil.which) -> Optional[Tuple[str, Callable[[str], List[str]]]]:
    for name, build in candidates:
        if which(name):
            return name, build
    return None


def recorder_command(path: str, tool: Optional[str] = None, which=shutil.which) -> List[str]:
    """Befehl für die Aufnahme als 16-kHz-Mono-WAV; ValueError ohne Rekorder."""
    if tool:
        for name, build in RECORDERS:
            if name == tool:
                return build(path)
        raise ValueError(f"unbekannter Rekorder: {tool}")
    found = find_tool(RECORDERS, which)
    if found is None:
        raise ValueError("kein Aufnahmeprogramm (pw-record, parecord, arecord) gefunden")
    return found[1](path)


def player_command(path: str, which=shutil.which) -> Optional[List[str]]:
    found = find_tool(PLAYERS, which)
    return found[1](path) if found else None


def microphone_available(run=None) -> Optional[bool]:
    """True/False nach pactl oder wpctl, None wenn beides fehlt. Monitore (Aufnahme
    der Wiedergabe) zählen nicht als Mikrofon."""
    run = run or _run_output
    out = run(["pactl", "list", "short", "sources"])
    if out is not None:
        return any(line.strip() and ".monitor" not in line.split("\t")[1] if "\t" in line else False
                   for line in out.splitlines())
    out = run(["wpctl", "status"])
    if out is not None:
        section = ""
        for line in out.splitlines():
            stripped = line.strip(" │├└─")
            if stripped.endswith(":") and stripped[:-1] in ("Sinks", "Sources", "Filters", "Streams", "Devices", "Clients"):
                section = stripped[:-1]
                continue
            if section == "Sources" and re.search(r"\d+\.\s+\S", stripped) and "Monitor" not in stripped:
                return True
        return False
    return None


def _run_output(argv: List[str], timeout: float = 5.0) -> Optional[str]:
    if shutil.which(argv[0]) is None:
        return None
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def wav_seconds(path: str) -> float:
    """Länge einer WAV-Datei in Sekunden, 0 bei unlesbarer Datei."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate() or SAMPLE_RATE
            return w.getnframes() / float(rate)
    except (OSError, wave.Error, EOFError):
        return 0.0


# ---- Aufnahme -------------------------------------------------------------------------
class Recorder:
    """Ein Aufnahmeprozess je Aufnahme. start() liefert (ok, Fehlertext), stop() die
    Datei oder den Fehler; stop() wartet bis STOP_GRACE_SECONDS auf den Prozess und
    gehört deshalb in einen Arbeitsthread."""

    def __init__(self, directory: str, tool: Optional[str] = None, popen=subprocess.Popen, which=shutil.which):
        self.directory = directory
        self.tool = tool
        self._popen = popen
        self._which = which
        self._proc = None
        self.path = ""

    def start(self) -> Tuple[bool, str]:
        try:
            os.makedirs(self.directory, exist_ok=True)
            self.path = os.path.join(self.directory, "aufnahme-" + time.strftime("%Y%m%d-%H%M%S") + ".wav")
            argv = recorder_command(self.path, self.tool, self._which)
        except (OSError, ValueError) as exc:
            return False, str(exc)
        try:
            self._proc = self._popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            return False, f"{argv[0]} startet nicht: {exc}"
        return True, ""

    def stop(self) -> Tuple[bool, str]:
        proc, self._proc = self._proc, None
        if proc is None:
            return False, "keine Aufnahme"
        rc = proc.poll()
        if rc is None:
            try:
                proc.send_signal(signal.SIGINT)      # der Rekorder schließt den WAV-Kopf sauber
                rc = proc.wait(STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait(2)
            except OSError:
                rc = -1
        err = ""
        try:
            if proc.stderr is not None:
                err = proc.stderr.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            pass
        seconds = wav_seconds(self.path)
        if seconds <= 0:
            self.discard()
            hint = err.splitlines()[-1][:200] if err else f"Exit {rc}"
            return False, f"Nichts aufgenommen ({hint}). Ist ein Mikrofon angeschlossen und in den Systemeinstellungen gewählt?"
        if seconds < MIN_RECORD_SECONDS:
            self.discard()
            return False, "Zu kurz gedrückt: Kürzel halten und sprechen, oder antippen und beim nächsten Druck beenden."
        return True, self.path

    def cancel(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(2)
            except (OSError, subprocess.SubprocessError):
                pass
        self.discard()

    def discard(self) -> None:
        try:
            if self.path and os.path.isfile(self.path):
                os.unlink(self.path)
        except OSError:
            pass


# ---- Helfer in der Hermes-Venv ----------------------------------------------------------
class Worker:
    """Der Sprachhelfer als langlebiger Prozess mit JSON-Zeilen. Startet beim ersten
    Auftrag, überlebt zwischen Aufträgen (Modelle bleiben geladen) und wird nach
    einem Fehler neu gestartet. request() blockiert und gehört in einen Thread;
    Ereigniszeilen (loading) gehen an on_event."""

    def __init__(self, python: str = VENV_PYTHON, script: str = WORKER_PY,
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None, popen=subprocess.Popen,
                 env: Optional[Dict[str, str]] = None):
        self.python = python
        self.script = script
        self.on_event = on_event or (lambda e: None)
        self._popen = popen
        self._env = env
        self._proc = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return os.access(self.python, os.X_OK) and os.path.isfile(self.script)

    def _ensure(self):
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        env = dict(os.environ if self._env is None else self._env)
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        env.setdefault("HERMES_LAZY_INSTALL_TARGET",
                       os.path.join(env.get("HERMES_HOME") or os.path.expanduser("~/.hermes"), "lazy-packages"))
        self._proc = self._popen([self.python, self.script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        return self._proc

    def request(self, op: str, timeout: float, **args) -> Dict[str, Any]:
        with self._lock:
            try:
                proc = self._ensure()
            except OSError as exc:
                return {"ok": False, "error": f"Sprachhelfer startet nicht: {exc}"}
            payload = json.dumps({"op": op, **args}, ensure_ascii=False) + "\n"
            result: Dict[str, Any] = {}

            def read():
                try:
                    proc.stdin.write(payload.encode("utf-8"))
                    proc.stdin.flush()
                    for raw in iter(proc.stdout.readline, b""):
                        try:
                            msg = json.loads(raw.decode("utf-8", "replace"))
                        except ValueError:
                            continue
                        if not isinstance(msg, dict):
                            continue
                        if "event" in msg:
                            self.on_event(msg)
                            continue
                        result.update(msg)
                        return
                    result.update({"ok": False, "error": "Sprachhelfer hat sich beendet"})
                except (OSError, ValueError) as exc:
                    result.update({"ok": False, "error": f"Sprachhelfer nicht erreichbar: {exc}"})

            reader = threading.Thread(target=read, name="voice-worker-io", daemon=True)
            reader.start()
            reader.join(timeout)
            timed_out = reader.is_alive()
            if timed_out or not result:
                self._kill()          # der Lese-Thread endet mit dem Prozess
                if timed_out:
                    return {"ok": False, "error": f"Sprachhelfer antwortet nicht ({op}, {int(timeout)} s)"}
                return result or {"ok": False, "error": "Sprachhelfer hat sich beendet"}
            if not result.get("ok") and result.get("error", "").startswith("Sprachhelfer"):
                self._kill()
            return result

    def _kill(self):
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(2)
            except (OSError, subprocess.SubprocessError):
                pass

    def stop(self):
        """Helfer beenden; wartet höchstens kurz auf einen laufenden Auftrag."""
        got = self._lock.acquire(timeout=1.0)
        try:
            proc = self._proc
            if proc is not None and proc.poll() is None and got:
                try:
                    proc.stdin.write(b'{"op": "quit"}\n')
                    proc.stdin.flush()
                    proc.wait(2)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            self._kill()
        finally:
            if got:
                self._lock.release()


# ---- Text fürs Vorlesen -------------------------------------------------------------------
_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.DOTALL), " Codeblock ausgelassen. "),
    (re.compile(r"`([^`\n]*)`"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.MULTILINE), ""),
    (re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE), ""),
    (re.compile(r"^[ \t]*\d+\.[ \t]+", re.MULTILINE), ""),
    (re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE), ""),
    (re.compile(r"(\*\*|__)(.*?)\1", re.DOTALL), r"\2"),
    (re.compile(r"(?<!\w)[*_](.*?)[*_](?!\w)", re.DOTALL), r"\1"),
    (re.compile(r"^[ \t]*\|?[-:| ]+\|?[ \t]*$", re.MULTILINE), ""),
    (re.compile(r"^[ \t]*\|(.*?)\|?[ \t]*$", re.MULTILINE), lambda m: ", ".join(c.strip() for c in m.group(1).split("|") if c.strip())),
    (re.compile(r"https?://\S+"), "Link"),
    (re.compile(r"[ \t]+"), " "),
    (re.compile(r"\n{2,}"), "\n"),
]


def speech_text(text: str, limit: int = MAX_SPEAK_CHARS) -> str:
    """Markdown und MEDIA-Tags aus einer Antwort nehmen, auf `limit` Zeichen kürzen
    (am Satzende), damit Piper nicht minutenlang liest."""
    text = re.sub(r"MEDIA:\S+", "", text or "")
    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)
    text = text.strip()
    if len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
        text = (cut[:end + 1] if end > limit // 2 else cut).rstrip() + " … Den Rest zeige ich im Fenster."
    return text


# ---- Zustandsautomat -------------------------------------------------------------------------
class PushToTalk:
    """Drücken, Loslassen, Antippen, Antwort und Fehler in Zustände übersetzen.

    actions ist ein Objekt mit: start_recording() -> (ok, err); stop_recording() (asynchron,
    meldet später recording_done); transcribe(path) (asynchron, meldet transcribed);
    ask(text) -> bool (Frage ins Fenster); speak(text) (asynchron, meldet speaking_done);
    stop_speaking(); notify(title, body); state_changed(state).
    Alle Rückrufe kommen im selben Thread wie die Ereignisse (Qt-Hauptthread)."""

    def __init__(self, actions, clock: Callable[[], float] = time.monotonic,
                 min_hold: float = MIN_HOLD_SECONDS, max_record: float = MAX_RECORD_SECONDS):
        self._a = actions
        self._clock = clock
        self._min_hold = min_hold
        self._max_record = max_record
        self.state = "idle"
        self.hold = False           # Taste noch gedrückt (Aufnahme endet beim Loslassen)
        self.pressed_at = 0.0
        self.recording_since = 0.0
        self.last_text = ""

    # -- Übergänge
    def _set(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._a.state_changed(state)

    def press(self) -> None:
        if self.state == "idle":
            self._start(hold=True)
        elif self.state == "recording":
            if self.hold:
                return              # Tastenwiederholung, solange die Taste unten ist
            self._stop()            # angetippt, jetzt der zweite Druck: Aufnahme beenden
        elif self.state == "speaking":
            self._a.stop_speaking()  # unterbrechen und zuhören
            self._set("idle")
            self._start(hold=True)
        # transcribing und asking: Druck verhallt, gleich kommt eine Antwort

    def release(self) -> None:
        if self.state != "recording" or not self.hold:
            return
        if self._clock() - self.pressed_at >= self._min_hold:
            self._stop()
        else:
            self.hold = False       # Antippen: die Aufnahme läuft bis zum nächsten Druck

    def toggle(self) -> None:
        """Knopf im Fenster oder `hermes-os-tray --talk`: ein Druck ohne Loslassen."""
        if self.state == "idle":
            self._start(hold=False)
        elif self.state == "recording":
            self._stop()
        elif self.state == "speaking":
            self._a.stop_speaking()
            self._set("idle")

    def tick(self) -> None:
        """Vom Timer: die Aufnahme endet spätestens nach max_record Sekunden."""
        if self.state == "recording" and self._clock() - self.recording_since >= self._max_record:
            self._stop()

    def cancel(self) -> None:
        if self.state == "recording":
            self._a.cancel_recording()
        elif self.state == "speaking":
            self._a.stop_speaking()
        self.hold = False
        self._set("idle")

    def _start(self, hold: bool) -> None:
        ok, err = self._a.start_recording()
        if not ok:
            self._a.notify("Hermes kann nicht zuhören", err or "Aufnahme nicht möglich.")
            self._set("idle")
            return
        self.hold = hold
        self.pressed_at = self.recording_since = self._clock()
        self._set("recording")

    def _stop(self) -> None:
        self.hold = False
        self._set("transcribing")
        self._a.stop_recording()

    # -- Rückmeldungen aus den Arbeitsthreads
    def recording_done(self, ok: bool, path_or_error: str) -> None:
        if self.state != "transcribing":
            return
        if not ok:
            self._a.notify("Hermes hat nichts gehört", path_or_error)
            self._set("idle")
            return
        self._a.transcribe(path_or_error)

    def transcribed(self, ok: bool, text_or_error: str) -> None:
        if self.state != "transcribing":
            return
        if not ok:
            self._a.notify("Hermes hat dich nicht verstanden", text_or_error)
            self._set("idle")
            return
        text = " ".join(text_or_error.split())
        if not text:
            self._a.notify("Hermes hat nichts verstanden", "Bitte noch einmal, etwas näher am Mikrofon.")
            self._set("idle")
            return
        self.last_text = text
        if not self._a.ask(text):
            self._a.notify("Hermes ist nicht bereit", f"Verstanden: „{text}“. Das Gateway antwortet gerade nicht.")
            self._set("idle")
            return
        self._set("asking")

    def answer(self, text: str) -> None:
        """Vom Fenster, wenn Hermes' Antwort fertig ist; leer heißt abgebrochen."""
        if self.state != "asking":
            return
        spoken = speech_text(text)
        if not spoken:
            self._set("idle")
            return
        self._set("speaking")
        self._a.speak(spoken)

    def speaking_done(self, error: str = "") -> None:
        if self.state != "speaking":
            return
        if error:
            self._a.notify("Hermes kann nicht sprechen", error)
        self._set("idle")


# ---- Anschluss an das Leisten-Symbol --------------------------------------------------------------
def install(backend, show_window: Callable[[], None], cache_dir: str):
    """`voice` für Main.qml und das Leisten-Symbol: Zustand, Kürzel, Knopf. Gibt das
    VoiceBackend zurück; ohne Rekorder oder Helfer bleibt es da und sagt, was fehlt."""
    from PySide6.QtCore import QObject, QTimer, Property, Signal, Slot, Qt
    import desktop

    class VoiceBackend(QObject):
        stateChanged = Signal()
        _event = Signal(str, bool, str)   # aus Arbeitsthreads, immer über die Ereignisschleife

        def __init__(self):
            super().__init__()
            self._recorder = Recorder(cache_dir)
            self._worker = Worker(on_event=self._worker_event)
            self._player = None
            self._speaking_cancelled = False
            self._loading = ""
            self._shortcut_text = ""
            self._ptt = PushToTalk(self)
            self._event.connect(self._on_event, Qt.ConnectionType.QueuedConnection)
            self._timer = QTimer(self)
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._ptt.tick)
            backend.answerFinished.connect(self._ptt.answer)
            self._recorder_tool = find_tool(RECORDERS)
            self._player_tool = find_tool(PLAYERS)

        # -- Eigenschaften für QML und das Symbol
        @Property(str, notify=stateChanged)
        def state(self):
            return self._ptt.state

        @Property(str, notify=stateChanged)
        def stateText(self):
            if self._ptt.state == "transcribing" and self._loading:
                return self._loading
            return STATE_TEXT.get(self._ptt.state, "")

        @Property(str, notify=stateChanged)
        def iconName(self):
            return STATE_ICON.get(self._ptt.state, "")

        @Property(bool, constant=True)
        def available(self):
            return self._recorder_tool is not None and self._worker.available

        @Property(str, constant=True)
        def unavailableReason(self):
            if self._recorder_tool is None:
                return "Kein Aufnahmeprogramm (pw-record oder parecord) gefunden."
            if not self._worker.available:
                return "Der Sprachhelfer der Hermes-Venv fehlt."
            return ""

        @Property(str, notify=stateChanged)
        def shortcutText(self):
            return self._shortcut_text

        @Slot()
        def toggle(self):
            self._ptt.toggle()

        @Slot()
        def cancel(self):
            self._ptt.cancel()

        def press(self):
            self._ptt.press()

        def release(self):
            self._ptt.release()

        def set_shortcut_text(self, text):
            self._shortcut_text = text
            self.stateChanged.emit()

        # -- actions für PushToTalk (laufen im Hauptthread)
        def state_changed(self, state):
            if state == "recording":
                self._timer.start()
            else:
                self._timer.stop()
            if state != "transcribing":
                self._loading = ""
            self.stateChanged.emit()

        def notify(self, title, body):
            desktop.notify(title, body, icon="audio-input-microphone")

        def start_recording(self):
            if self._recorder_tool is None or not self._worker.available:
                return False, self.unavailableReason
            if microphone_available() is False:
                return False, "Kein Mikrofon gefunden. Anschließen und in den Systemeinstellungen unter Audio wählen."
            return self._recorder.start()

        def stop_recording(self):
            def work():
                ok, result = self._recorder.stop()
                self._event.emit("recording_done", ok, result)
            threading.Thread(target=work, name="voice-stop", daemon=True).start()

        def cancel_recording(self):
            self._cancel_thread = threading.Thread(target=self._recorder.cancel, name="voice-cancel", daemon=True)
            self._cancel_thread.start()

        def transcribe(self, path):
            def work():
                result = self._worker.request("transcribe", TRANSCRIBE_TIMEOUT, path=path)
                try:
                    os.unlink(path)          # die Aufnahme bleibt nicht liegen
                except OSError:
                    pass
                if result.get("ok"):
                    self._event.emit("transcribed", True, str(result.get("text") or ""))
                else:
                    self._event.emit("transcribed", False, str(result.get("error") or "Erkennung fehlgeschlagen"))
            threading.Thread(target=work, name="voice-transcribe", daemon=True).start()

        def ask(self, text):
            if backend.state != "ready" or backend.busy or not getattr(backend, "_session_ready", True):
                return False
            show_window()
            backend.send(text)
            return True

        def speak(self, text):
            self._speaking_cancelled = False
            out = os.path.join(cache_dir, "antwort-" + time.strftime("%Y%m%d-%H%M%S") + ".wav")

            def work():
                result = self._worker.request("speak", SPEAK_TIMEOUT, text=text, out=out)
                if self._speaking_cancelled:
                    self._cleanup(out)
                    return
                if not result.get("ok"):
                    self._event.emit("speaking_done", False, str(result.get("error") or "Sprachausgabe fehlgeschlagen"))
                    return
                argv = player_command(out)
                if argv is None:
                    self._cleanup(out)
                    self._event.emit("speaking_done", False, "Kein Abspielprogramm (pw-play, paplay, aplay) gefunden.")
                    return
                try:
                    self._player = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL, start_new_session=True)
                    self._player.wait()
                    self._player = None
                except OSError as exc:
                    self._cleanup(out)
                    self._event.emit("speaking_done", False, f"{argv[0]}: {exc}")
                    return
                self._cleanup(out)
                self._event.emit("speaking_done", True, "")
            threading.Thread(target=work, name="voice-speak", daemon=True).start()

        def stop_speaking(self):
            self._speaking_cancelled = True
            player, self._player = self._player, None
            if player is not None and player.poll() is None:
                try:
                    player.kill()
                except OSError:
                    pass

        @staticmethod
        def _cleanup(path):
            try:
                os.unlink(path)
            except OSError:
                pass

        # -- Rückmeldungen
        def _on_event(self, name, ok, payload):
            if name == "recording_done":
                self._ptt.recording_done(ok, payload)
            elif name == "transcribed":
                self._ptt.transcribed(ok, payload)
            elif name == "speaking_done":
                self._ptt.speaking_done("" if ok else payload)
            elif name == "loading":
                self._loading = payload
                self.stateChanged.emit()

        def _worker_event(self, event):
            # aus dem Lese-Thread des Helfers
            if event.get("event") == "loading":
                what = "Sprachmodell" if event.get("what") == "stt" else "Stimme"
                name = event.get("model") or event.get("voice") or ""
                self._event.emit("loading", True, f"Lade {what} {name} …")

        def shutdown(self):
            """Beim Beenden: Aufnahme abbrechen, Helfer beenden, Kürzel bei KGlobalAccel
            freigeben (kglobalacceld beobachtet seine Anmelder nicht)."""
            self._ptt.cancel()
            # Den Rekorder synchron beenden: der Abbruch-Thread ist ein Daemon, der
            # Prozess läuft in einer eigenen Sitzung und würde das Symbol sonst
            # überleben und weiter aufnehmen.
            thread = getattr(self, "_cancel_thread", None)
            if thread is not None:
                thread.join(3)
            self._recorder.cancel()
            self._worker.stop()
            if self.shortcut is not None:
                self.shortcut.close()

    voice = VoiceBackend()
    voice.shortcut = None
    # Kürzel mit Drücken und Loslassen: KGlobalAccel über D-Bus (tray/desktop.py).
    # Ohne Plasma bleibt der Knopf im Fenster und `hermes-os-tray --talk`.
    shortcut = desktop.GlobalShortcut(desktop.COMPONENT, ACTION_ID, desktop.COMPONENT_LABEL, ACTION_LABEL,
                                      SHORTCUT, on_pressed=voice.press, on_released=voice.release)
    if shortcut.install():
        shortcut.attach_qt()            # sonst liest niemand die Signale vom Bus
        voice.shortcut = shortcut
        voice.set_shortcut_text(shortcut.active_keys or SHORTCUT)
        if shortcut.warning:
            print(f"hermes-os-tray: {shortcut.warning}", file=sys.stderr)
    else:
        print(f"hermes-os-tray: Kürzel {SHORTCUT} nicht angemeldet: {shortcut.error}", file=sys.stderr)
    return voice
