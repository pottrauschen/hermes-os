"""hermes-os -- Sprachhelfer in der Hermes-Venv: Erkennung (faster-whisper) und
Ausgabe (Piper) für das Leisten-Symbol.

Das Leisten-Symbol läuft mit Fedoras Python und PySide6, faster-whisper und
Piper liegen in der Hermes-Venv unter /usr/lib/hermes-agent/.venv (Python 3.13).
Deshalb startet tray/voice.py dieses Skript mit der Venv-Python als eigenen
Prozess und spricht mit ihm über JSON-Zeilen auf stdin und stdout; die Modelle
bleiben zwischen zwei Aufträgen geladen, nach WORKER_IDLE_SECONDS ohne Auftrag
beendet sich der Prozess. Nichts davon berührt den GUI-Thread.

Aufträge (eine Zeile JSON je Auftrag, eine Zeile Antwort):
  {"op": "transcribe", "path": "/tmp/x.wav"}
      -> {"ok": true, "text": "…", "language": "de", "seconds": 1.2}
  {"op": "speak", "text": "…", "out": "/tmp/y.wav"}
      -> {"ok": true, "path": "/tmp/y.wav", "seconds": 0.4}
  {"op": "ping"}   -> {"ok": true, "hermes": true|false}
  {"op": "quit"}   -> {"ok": true}
Vor einem langen Schritt kommt eine Ereigniszeile, etwa
  {"event": "loading", "what": "stt", "model": "small"}
Fehler: {"ok": false, "error": "…"}.

Erkennung und Ausgabe gehen zuerst über Hermes' eigene Helfer
(tools.transcription_tools.transcribe_audio_local_fallback, tools.tts_tool_local),
die stt.* und tts.piper.* aus ~/.hermes/config.yaml vollständig auswerten
(VAD, Schwellen, voices_dir); sind die nicht importierbar, ruft das Skript
faster-whisper und Piper direkt mit Modell, Sprache und Stimme aus der Config.
Beide Wege sind in tests/sehen-hoeren-check.py gegen Attrappen geprüft (der
direkte) beziehungsweise im Validierungs-Gate mit --check in der Venv (die
Importe der Helfer).

Aufruf:  voice_worker.py               Schleife auf stdin/stdout
         voice_worker.py --check       Importe prüfen, nichts laden, Exit 0/1
Umgebung: HERMES_HOME wie bei Hermes (Vorgabe ~/.hermes)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

WORKER_IDLE_SECONDS = 600
DEFAULT_STT_MODEL = "base"          # wie Hermes' config_defaults; unsere Vorlage setzt small
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
PIPER_VOICES_SUBDIR = "cache/piper-voices"
PIPER_LEGACY_SUBDIR = "piper_voices_cache"
MAX_SPEAK_CHARS = 4000


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


# ---- Config ------------------------------------------------------------------------
def load_config(home: Optional[Path] = None) -> Dict[str, Any]:
    """stt und tts aus config.yaml; ohne PyYAML oder Datei leer."""
    path = (home or hermes_home()) / "config.yaml"
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def stt_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Modell, Sprache, Gerät und Rechenart wie Hermes sie auflöst: stt.local.language
    vor stt.language, leer heißt automatisch."""
    stt = cfg.get("stt") if isinstance(cfg.get("stt"), dict) else {}
    local = stt.get("local") if isinstance(stt.get("local"), dict) else {}
    language = str(local.get("language") or stt.get("language") or os.environ.get("HERMES_LOCAL_STT_LANGUAGE") or "").strip()
    model = str(local.get("model") or DEFAULT_STT_MODEL).strip()
    if model in ("whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"):
        model = DEFAULT_STT_MODEL          # Cloud-Namen, wie Hermes' _normalize_local_model
    vad = local.get("vad", True)
    return {
        "model": model,
        "language": language or None,
        "device": str(local.get("device") or "auto"),
        "compute_type": str(local.get("compute_type") or "auto"),
        "vad": vad is None or bool(vad),
        "vad_min_silence_ms": int(local.get("vad_min_silence_ms") or 500),
        "initial_prompt": str(local.get("initial_prompt") or stt.get("prompt") or "").strip(),
        "no_speech_threshold": float(local.get("no_speech_prob_threshold", 0.6)),
        "log_prob_threshold": float(local.get("logprob_threshold", -1.0)),
    }


def tts_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    tts = cfg.get("tts") if isinstance(cfg.get("tts"), dict) else {}
    piper = tts.get("piper") if isinstance(tts.get("piper"), dict) else {}
    return {
        "provider": str(tts.get("provider") or "").strip(),
        "voice": str(piper.get("voice") or DEFAULT_PIPER_VOICE).strip(),
        "voices_dir": str(piper.get("voices_dir") or "").strip(),
        "use_cuda": bool(piper.get("use_cuda", False)),
        "length_scale": piper.get("length_scale"),
    }


def piper_voices_dir(settings: Dict[str, Any], home: Optional[Path] = None) -> Path:
    """Wo Hermes die Stimmen ablegt: tts.piper.voices_dir, sonst ein gefüllter
    Alt-Ordner piper_voices_cache, sonst cache/piper-voices unter HERMES_HOME."""
    home = home or hermes_home()
    if settings.get("voices_dir"):
        return Path(settings["voices_dir"]).expanduser()
    legacy = home / PIPER_LEGACY_SUBDIR
    if legacy.is_dir() and any(legacy.glob("*.onnx")):
        return legacy
    return home / PIPER_VOICES_SUBDIR


# ---- Erkennung ---------------------------------------------------------------------
class Transcriber:
    def __init__(self, emit):
        self._emit = emit
        self._model = None
        self._model_key = ""
        self._hermes = None      # True, False oder None (noch nicht probiert)

    def _hermes_transcribe(self, path: str) -> Optional[Tuple[bool, str]]:
        """Über Hermes' Helfer, der stt.* vollständig auswertet; None, wenn der Import fehlt."""
        if self._hermes is False:
            return None
        try:
            from tools.transcription_tools import transcribe_audio_local_fallback  # type: ignore
        except Exception:
            self._hermes = False
            return None
        self._hermes = True
        result = transcribe_audio_local_fallback(path)
        if not isinstance(result, dict):
            return False, "Hermes-Helfer lieferte keine Antwort"
        if not result.get("success"):
            return False, str(result.get("error") or "Erkennung fehlgeschlagen")
        text = str(result.get("transcript") or "").strip()
        try:
            from tools.voice_mode import is_whisper_hallucination  # type: ignore
            if text and is_whisper_hallucination(text):
                text = ""
        except Exception:
            pass
        return True, text

    def _direct_transcribe(self, path: str, settings: Dict[str, Any]) -> Tuple[bool, str]:
        from faster_whisper import WhisperModel  # type: ignore
        key = f"{settings['model']}|{settings['device']}|{settings['compute_type']}"
        if self._model is None or self._model_key != key:
            self._emit({"event": "loading", "what": "stt", "model": settings["model"]})
            try:
                self._model = WhisperModel(settings["model"], device=settings["device"],
                                           compute_type=settings["compute_type"])
            except Exception as exc:
                if settings["device"] == "cpu" and settings["compute_type"] == "int8":
                    raise
                # Ohne CUDA-Bibliotheken auf die CPU zurückfallen, wie Hermes
                self._emit({"event": "loading", "what": "stt", "model": settings["model"], "fallback": str(exc)[:200]})
                self._model = WhisperModel(settings["model"], device="cpu", compute_type="int8")
            self._model_key = key
        kwargs: Dict[str, Any] = {"beam_size": 5, "condition_on_previous_text": False,
                                  "vad_filter": settings["vad"],
                                  "no_speech_threshold": settings["no_speech_threshold"],
                                  "log_prob_threshold": settings["log_prob_threshold"]}
        if settings["vad"]:
            kwargs["vad_parameters"] = {"min_silence_duration_ms": settings["vad_min_silence_ms"]}
        if settings["language"]:
            kwargs["language"] = settings["language"]
        if settings["initial_prompt"]:
            kwargs["initial_prompt"] = settings["initial_prompt"]
        segments, _info = self._model.transcribe(path, **kwargs)
        kept = []
        for seg in segments:
            no_speech = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
            logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
            if no_speech > settings["no_speech_threshold"] and logprob < settings["log_prob_threshold"]:
                continue
            kept.append(str(getattr(seg, "text", "") or "").strip())
        return True, " ".join(t for t in kept if t).strip()

    def transcribe(self, path: str) -> Dict[str, Any]:
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": f"Aufnahme nicht gefunden: {path}"}
        started = time.monotonic()
        cfg = load_config()
        settings = stt_settings(cfg)
        try:
            result = self._hermes_transcribe(path)
            if result is None:
                result = self._direct_transcribe(path, settings)
        except ImportError as exc:
            return {"ok": False, "error": f"faster-whisper fehlt in der Venv: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"Erkennung fehlgeschlagen: {type(exc).__name__}: {exc}"}
        ok, text = result
        if not ok:
            return {"ok": False, "error": text}
        return {"ok": True, "text": text, "language": settings["language"] or "", "model": settings["model"],
                "hermes": bool(self._hermes), "seconds": round(time.monotonic() - started, 2)}


# ---- Ausgabe ---------------------------------------------------------------------
class Speaker:
    def __init__(self, emit):
        self._emit = emit
        self._voice = None
        self._voice_path = ""

    def _voice_files(self, settings: Dict[str, Any]) -> Tuple[Path, Path]:
        """Modell und Beschreibung der Stimme; fehlt sie, lädt piper.download_voices sie
        in denselben Ordner, den Hermes benutzt."""
        name = settings["voice"]
        candidate = Path(name).expanduser()
        if candidate.suffix.lower() == ".onnx" and candidate.is_file():
            return candidate, Path(str(candidate) + ".json")
        directory = piper_voices_dir(settings)
        onnx, meta = directory / f"{name}.onnx", directory / f"{name}.onnx.json"
        if onnx.is_file() and meta.is_file():
            return onnx, meta
        self._emit({"event": "loading", "what": "tts", "voice": name})
        directory.mkdir(parents=True, exist_ok=True)
        import subprocess
        proc = subprocess.run([sys.executable, "-m", "piper.download_voices", name, "--download-dir", str(directory)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        if proc.returncode != 0 or not onnx.is_file():
            tail = proc.stdout.decode("utf-8", "replace").strip().splitlines()[-3:]
            raise RuntimeError(f"Stimme {name} nicht ladbar: " + " | ".join(tail))
        return onnx, meta

    def speak(self, text: str, out: str) -> Dict[str, Any]:
        text = (text or "").strip()[:MAX_SPEAK_CHARS]
        if not text:
            return {"ok": False, "error": "Nichts zu sagen"}
        if not out:
            return {"ok": False, "error": "Kein Zielpfad (out)"}
        started = time.monotonic()
        settings = tts_settings(load_config())
        try:
            from piper import PiperVoice  # type: ignore
        except ImportError as exc:
            return {"ok": False, "error": f"piper fehlt in der Venv: {exc}"}
        try:
            onnx, _meta = self._voice_files(settings)
            if self._voice is None or self._voice_path != str(onnx):
                self._emit({"event": "loading", "what": "tts", "voice": settings["voice"]})
                self._voice = PiperVoice.load(str(onnx), use_cuda=settings["use_cuda"])
                self._voice_path = str(onnx)
            syn_config = None
            if settings.get("length_scale") not in (None, ""):
                try:
                    from piper import SynthesisConfig  # type: ignore
                    syn_config = SynthesisConfig(length_scale=float(settings["length_scale"]))
                except Exception:
                    syn_config = None
            part = out + ".part"
            with wave.open(part, "wb") as wav_file:
                if syn_config is not None:
                    self._voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                else:
                    self._voice.synthesize_wav(text, wav_file)
            os.replace(part, out)
        except Exception as exc:
            return {"ok": False, "error": f"Sprachausgabe fehlgeschlagen: {type(exc).__name__}: {exc}"}
        return {"ok": True, "path": out, "voice": settings["voice"], "seconds": round(time.monotonic() - started, 2)}


# ---- Schleife ----------------------------------------------------------------------
def check_imports() -> int:
    problems = []
    for name in ("faster_whisper", "piper"):
        try:
            __import__(name)
        except Exception as exc:
            problems.append(f"{name} nicht importierbar: {exc}")
    hermes = True
    try:
        import tools.transcription_tools  # type: ignore # noqa: F401
        import tools.tts_tool_local  # type: ignore # noqa: F401
    except Exception as exc:
        hermes = False
        print(f"WARN  Hermes-Helfer nicht importierbar, direkter Weg: {exc}")
    for p in problems:
        print(f"FEHL  {p}")
    if problems:
        return 1
    print(f"OK    voice_worker: faster_whisper und piper vorhanden, Hermes-Helfer {'ja' if hermes else 'nein'}")
    return 0


def serve(stdin, stdout, idle_seconds: float = WORKER_IDLE_SECONDS) -> int:
    lock = threading.Lock()

    def emit(obj: Dict[str, Any]) -> None:
        with lock:
            stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            stdout.flush()

    transcriber, speaker = Transcriber(emit), Speaker(emit)
    last = time.monotonic()
    stop = threading.Event()

    def watchdog():
        while not stop.wait(min(5.0, max(0.2, idle_seconds / 4))):
            if time.monotonic() - last > idle_seconds:
                os._exit(0)

    threading.Thread(target=watchdog, name="voice-idle", daemon=True).start()
    for raw in iter(stdin.readline, ""):
        last = time.monotonic()
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
            if not isinstance(req, dict):
                raise ValueError("kein Objekt")
        except ValueError as exc:
            emit({"ok": False, "error": f"Auftrag unlesbar: {exc}"})
            continue
        op = str(req.get("op") or "")
        if op == "ping":
            hermes = False
            try:
                import tools.transcription_tools  # type: ignore # noqa: F401
                hermes = True
            except Exception:
                pass
            emit({"ok": True, "hermes": hermes, "python": sys.version.split()[0]})
        elif op == "transcribe":
            emit(transcriber.transcribe(str(req.get("path") or "")))
        elif op == "speak":
            emit(speaker.speak(str(req.get("text") or ""), str(req.get("out") or "")))
        elif op == "quit":
            emit({"ok": True})
            break
        else:
            emit({"ok": False, "error": f"unbekannter Auftrag: {op}"})
        last = time.monotonic()
    stop.set()
    return 0


def main(argv) -> int:
    if "--check" in argv:
        return check_imports()
    idle = WORKER_IDLE_SECONDS
    if "--idle" in argv:
        try:
            idle = float(argv[argv.index("--idle") + 1])
        except (IndexError, ValueError):
            pass
    return serve(sys.stdin, sys.stdout, idle)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
