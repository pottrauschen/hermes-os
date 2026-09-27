"""hermes-os -- lokales Modell: GPU erkennen, Ollama bedienen, Hermes eintragen.

Reine Standardbibliothek plus PyYAML (für config.yaml), damit das Modul mit
Fedoras Python (ujust-Rezepte, Helfer /usr/libexec/hermes-os-lokal), mit der
Hermes-Venv (Brücke des Einrichtungsassistenten) und ohne Hermes in
tests/lokales-modell-check.py läuft. Ollama läuft als Nutzerdienst
(ollama.service, systemctl --user) und hört nur auf 127.0.0.1:11434; Hermes
spricht den OpenAI-kompatiblen Endpunkt darunter (/v1) an.

Ollama liegt nicht im Image. Wer das lokale Modell will, lädt das Programm
mit install_ollama in sein Home (~/.local/share/hermes-os/ollama), in der
hier gepinnten Version und nur mit passender Prüfsumme.

Aufbau:
- install_ollama:   Release-Archiv laden, SHA256 prüfen, ohne cuda_v12 entpacken
- remove_ollama:    Programm (und auf Wunsch die Modelle) wieder löschen
- space_check:      reicht der freie Platz für Programm oder Modell?
- detect_gpu:       nvidia-smi fragen (Laufzeit, nicht Bauzeit), AMD über /dev/kfd
                    erkennen; ohne beides läuft Ollama auf der CPU
- server_status:    /api/version und /api/tags des Dienstes
- pull_model:       /api/pull als Strom von JSON-Zeilen, Fortschritt per Rückruf
- check_endpoint:   /v1/models und ein Chat mit Werkzeugdefinition: antwortet
                    das Modell mit einem Werkzeugaufruf?
- recommend:        Modellvorschläge nach VRAM
- write_hermes_config: model-Block in ~/.hermes/config.yaml setzen, Rest bleibt
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

OLLAMA_HOST = "127.0.0.1:11434"


def _base_url_from_env() -> str:
    """Adresse des Dienstes. OLLAMA_HOST ist Ollamas eigene Konvention (die
    CLI liest sie auch); ohne Schema ist http gemeint. Tests biegen sie auf
    einen nachgebauten Server um."""
    host = os.environ.get("OLLAMA_HOST", "").strip() or OLLAMA_HOST
    if not re.match(r"^https?://", host):
        host = "http://" + host
    return host.rstrip("/")


BASE_URL = _base_url_from_env()
HERMES_BASE_URL = BASE_URL + "/v1"          # OpenAI-kompatibler Endpunkt von Ollama
UNIT = "ollama.service"                     # Nutzerdienst aus /usr/lib/systemd/user

# Ollama wird nachgeladen, nicht mitgeliefert. Gepinnt wie früher im Build:
# Version, Archiv und SHA256 aus der sha256sum.txt des Releases. Ein Bump ist
# eine Änderung dieser drei Zeilen; vorher in Test-VM 112 `ujust
# hermes-lokal-ein` und `ollama ps` (100 % GPU) prüfen.
OLLAMA_PIN = "0.34.4"
OLLAMA_ASSET = "ollama-linux-amd64.tar.zst"
OLLAMA_SHA256 = "c238986e61d40c0cc5f4a9b9e40b9eea104350b77efa34741fc134e105cb9533"
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_PIN}/{OLLAMA_ASSET}"
# Zielordner; ollama.service startet %h/.local/share/hermes-os/ollama/bin/ollama.
# HERMES_OS_OLLAMA_DIR nur für Tests.
OLLAMA_DIR = os.environ.get("HERMES_OS_OLLAMA_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "hermes-os", "ollama")
OLLAMA_BIN = os.path.join(OLLAMA_DIR, "bin", "ollama")
OLLAMA_STAMP = os.path.join(OLLAMA_DIR, ".hermes-os-release")
# Wo ollama.service die Modelle ablegt (OLLAMA_MODELS=%h/.local/share/ollama/models)
MODELS_DIR = os.environ.get("HERMES_OS_OLLAMA_MODELS_DIR") or os.path.join(
    os.path.expanduser("~"), ".local", "share", "ollama")
# Platzbedarf: das Archiv (rund 1,3 GB) liegt beim Entpacken neben dem Ergebnis
# (rund 0,9 GB ohne cuda_v12); dazu Luft, damit das Home nicht vollläuft.
INSTALL_ARCHIVE_MB = 1300
INSTALL_SIZE_MB = 900
INSTALL_NEED_MB = INSTALL_ARCHIVE_MB + INSTALL_SIZE_MB + 1024
MODEL_MARGIN_MB = 1024                      # Luft über der Modellgröße
UNKNOWN_MODEL_MIN_MB = 2048                 # eigenes Modell, Größe unbekannt: wenigstens das

HERMES_PROVIDER = "custom"                  # Hermes-Anbieter für OpenAI-kompatible Server (Ollama hat keinen eigenen Slug)
HERMES_API_MODE = "chat_completions"
PROBE_KEY = "no-key-required"               # Ollama prüft keinen Schlüssel; Hermes schickt genau das als Bearer
# Kontextfenster. Hermes 0.21.x verweigert den Start mit Werkzeugen unter 64.000
# Token (agent/model_metadata.py MINIMUM_CONTEXT_LENGTH); Ollamas /v1-Endpunkt
# nimmt kein num_ctx je Anfrage an, deshalb setzt ollama.service
# OLLAMA_CONTEXT_LENGTH auf denselben Wert und die config.yaml sagt Hermes,
# was der Server wirklich bedient (context_length deckelt, ollama_num_ctx hebt).
CONTEXT_LENGTH = 65536

# Modellvorschläge (Ollama-Tags, `ollama pull <tag>`). vram_mb: Gewichte plus
# KV-Cache für CONTEXT_LENGTH mit q8_0-Cache, gerechnet, nicht gemessen
# (docs/lokales-modell.md); cpu_ok: läuft ohne GPU noch erträglich. Dichte
# 14B-Modelle (qwen3:14b, 9,3 GB) passen mit 64k Kontext nicht mehr in 12 GB;
# Qwen3.5 ist hybrid (nur 8 von 32 Schichten mit KV-Cache) und braucht rund
# 32 KiB je Token statt 160 KiB.
RECOMMENDED: List[Dict[str, Any]] = [
    {"tag": "qwen3.5:9b", "label": "Qwen3.5 9B (Vorgabe für 12 GB)", "size_gb": 6.6, "vram_mb": 9500,
     "cpu_ok": False, "tools": True, "german": True,
     "note": "Werkzeugaufrufe verlässlich, 201 Sprachen, 256k Modellkontext; Ollama empfiehlt es selbst für Hermes."},
    {"tag": "qwen3.5:4b", "label": "Qwen3.5 4B (8 GB, schneller, CPU-Fallback)", "size_gb": 3.4, "vram_mb": 5500,
     "cpu_ok": True, "tools": True, "german": True,
     "note": "Gleiche Familie, für 8-GB-Karten oder ohne GPU; auf der CPU dauert der erste Schritt Minuten."},
    {"tag": "gemma4:12b", "label": "Gemma 4 12B (besseres Deutsch, Testkandidat)", "size_gb": 7.6, "vram_mb": 11000,
     "cpu_ok": False, "tools": True, "german": True,
     "note": "Schreibt besseres Deutsch; Werkzeugaufrufe im September 2026 noch mit offenen Fehlern (Hermes #79639, Ollama #18275)."},
    {"tag": "granite4:tiny-h", "label": "Granite 4 Tiny-H (ohne Denkmodus)", "size_gb": 4.2, "vram_mb": 5500,
     "cpu_ok": True, "tools": True, "german": True,
     "note": "IBM, Deutsch offiziell, Mamba-Hybrid mit kaum KV-Cache; kein Denkmodus, schlichter."},
]


# ---- Hilfen -----------------------------------------------------------------

def _run(argv: List[str], timeout: int = 20, env: Optional[Dict[str, str]] = None):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)


def _http(method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: float = 10.0):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {PROBE_KEY}"})
    return urllib.request.urlopen(req, timeout=timeout)


def _get_json(url: str, timeout: float = 10.0) -> Any:
    with _http("GET", url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def _post_json(url: str, body: Dict[str, Any], timeout: float = 60.0) -> Any:
    with _http("POST", url, body, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        return f"HTTP {exc.code}: {detail or exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"nicht erreichbar: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


# ---- Platz ------------------------------------------------------------------

def free_mb(path: str) -> int:
    """Freier Platz in MB auf dem Dateisystem von path, oder vom nächsten
    vorhandenen Elternordner, solange path noch nicht existiert."""
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return int(shutil.disk_usage(p).free // (1024 * 1024))
    except OSError:
        return 0


def space_check(need_mb: int, path: str) -> Dict[str, Any]:
    """Reicht der Platz unter path? {ok, free_mb, need_mb, error}."""
    free = free_mb(path)
    ok = free >= need_mb
    return {"ok": ok, "free_mb": free, "need_mb": int(need_mb),
            "error": "" if ok else (f"Zu wenig Platz: {free / 1024:.1f} GB frei, gebraucht werden rund "
                                    f"{need_mb / 1024:.1f} GB (unter {path})")}


def model_need_mb(tag: str) -> Tuple[int, bool]:
    """Platzbedarf eines Modells in MB und ob die Größe bekannt ist: aus
    RECOMMENDED plus Luft, sonst eine Untergrenze."""
    for m in RECOMMENDED:
        if m["tag"] == tag:
            return int(m["size_gb"] * 1000) + MODEL_MARGIN_MB, True
    return UNKNOWN_MODEL_MIN_MB, False


def _tree_mb(path: str) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return int(total // (1024 * 1024))


# ---- Ollama nachladen -------------------------------------------------------

def ollama_installed() -> Dict[str, Any]:
    """Liegt Ollama im Home, und in welcher Version (Stempel beim Entpacken)?"""
    info = {"installed": os.path.isfile(OLLAMA_BIN) and os.access(OLLAMA_BIN, os.X_OK),
            "version": "", "path": OLLAMA_DIR, "pin": OLLAMA_PIN}
    try:
        with open(OLLAMA_STAMP, encoding="utf-8") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == "version":
                    info["version"] = value
    except OSError:
        pass
    return info


def _download(url: str, dest: str, progress: Optional[Callable[[Dict[str, Any]], None]],
              timeout: float) -> str:
    """url nach dest laden, SHA256 nebenbei rechnen; liefert die Prüfsumme."""
    digest = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-os"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -1
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            percent = int(done * 100 / total) if total else 0
            if progress and percent != last:
                progress({"status": f"lade Ollama {OLLAMA_PIN}", "total": total, "completed": done,
                          "percent": percent})
                last = percent
    return digest.hexdigest()


def install_ollama(progress: Optional[Callable[[Dict[str, Any]], None]] = None, url: Optional[str] = None,
                   sha256: Optional[str] = None, dest: Optional[str] = None, timeout: float = 60.0,
                   force: bool = False) -> Dict[str, Any]:
    """Ollama in der gepinnten Version ins Home laden: Platz prüfen, Archiv
    laden, SHA256 vergleichen, ohne cuda_v12 entpacken (1,3 GB, nur für Treiber
    vor 580), Stempel schreiben, Probelauf, dann erst an den Zielort. Scheitert
    ein Schritt, bleibt ein vorhandenes Ollama unangetastet.

    HERMES_OS_OLLAMA_URL und HERMES_OS_OLLAMA_SHA256 nur für Tests.
    Rückgabe: {ok, skipped, version, path, error}."""
    url = url or os.environ.get("HERMES_OS_OLLAMA_URL") or OLLAMA_URL
    sha256 = (sha256 or os.environ.get("HERMES_OS_OLLAMA_SHA256") or OLLAMA_SHA256).lower()
    dest = os.path.abspath(dest or OLLAMA_DIR)
    out: Dict[str, Any] = {"ok": False, "skipped": False, "version": OLLAMA_PIN, "path": dest, "error": ""}
    have = ollama_installed() if dest == os.path.abspath(OLLAMA_DIR) else {"installed": False, "version": ""}
    if have["installed"] and have["version"] == OLLAMA_PIN and not force:
        out.update(ok=True, skipped=True)
        return out
    for tool in ("tar", "zstd"):
        if not shutil.which(tool):
            out["error"] = f"{tool} fehlt; ohne {tool} lässt sich das Ollama-Archiv nicht entpacken"
            return out
    parent = os.path.dirname(dest)
    room = space_check(INSTALL_NEED_MB, parent)
    if not room["ok"]:
        out["error"] = room["error"]
        return out
    os.makedirs(parent, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".ollama-install-", dir=parent)
    try:
        archive = os.path.join(work, OLLAMA_ASSET)
        try:
            got = _download(url, archive, progress, timeout)
        except Exception as e:
            out["error"] = f"Download von {url} fehlgeschlagen: {_error_text(e)}"
            return out
        if got != sha256:
            out["error"] = (f"Prüfsumme stimmt nicht (erwartet {sha256[:16]}…, erhalten {got[:16]}…); "
                            "nichts installiert")
            return out
        if progress:
            progress({"status": "entpacke Ollama", "total": 0, "completed": 0, "percent": 100})
        extract = os.path.join(work, "extract")
        os.makedirs(extract)
        p = _run(["tar", "--zstd", "-xf", archive, "-C", extract, "--no-same-owner", "--exclude=cuda_v12"],
                 timeout=900)
        os.unlink(archive)
        if p.returncode != 0:
            out["error"] = f"Entpacken fehlgeschlagen: {(p.stderr or p.stdout).strip()[-300:]}"
            return out
        # Das Archiv ist zum Entpacken nach /usr gedacht (bin/, lib/); falls ein
        # Release doch usr/ voranstellt, beide Formen annehmen.
        root = extract
        if os.path.isdir(os.path.join(extract, "usr", "lib", "ollama")):
            root = os.path.join(extract, "usr")
        if not (os.path.isfile(os.path.join(root, "bin", "ollama")) and os.path.isdir(os.path.join(root, "lib", "ollama"))):
            out["error"] = "Archiv ohne bin/ollama und lib/ollama; nichts installiert"
            return out
        stage = os.path.join(work, "stage")
        os.makedirs(os.path.join(stage, "bin"))
        os.makedirs(os.path.join(stage, "lib"))
        os.replace(os.path.join(root, "bin", "ollama"), os.path.join(stage, "bin", "ollama"))
        os.replace(os.path.join(root, "lib", "ollama"), os.path.join(stage, "lib", "ollama"))
        os.chmod(os.path.join(stage, "bin", "ollama"), 0o755)
        libdir = os.path.join(stage, "lib", "ollama")
        backends = sorted(d for d in os.listdir(libdir) if os.path.isdir(os.path.join(libdir, d))
                          and re.match(r"^(cuda_v\d+|vulkan|rocm.*)$", d))
        with open(os.path.join(stage, ".hermes-os-release"), "w", encoding="utf-8") as f:
            f.write(f"version={OLLAMA_PIN}\nasset={OLLAMA_ASSET}\nsha256={sha256}\n"
                    f"backends={' '.join(['cpu'] + backends)}\nupdate=home\n")
        try:
            probe = _run([os.path.join(stage, "bin", "ollama"), "--version"], timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            out["error"] = f"Ollama startet nicht: {e}"
            return out
        if probe.returncode != 0:
            out["error"] = f"Ollama startet nicht: {(probe.stderr or probe.stdout).strip()[-300:]}"
            return out
        old = os.path.join(work, "old")
        if os.path.lexists(dest):
            os.replace(dest, old)
        try:
            os.replace(stage, dest)
        except OSError:
            if os.path.lexists(old):
                os.replace(old, dest)
            raise
        out["ok"] = True
        out["backends"] = backends
        return out
    except Exception as e:
        out["error"] = f"Installation fehlgeschlagen: {_error_text(e)}"
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def remove_ollama(models: bool = False) -> Dict[str, Any]:
    """Ollama aus dem Home löschen, mit models=True auch alle geladenen Modelle.
    Den Dienst vorher stoppen (der Helfer tut das). Rückgabe: {ok, freed_mb, removed}."""
    removed, freed = [], 0
    for path in [OLLAMA_DIR] + ([MODELS_DIR] if models else []):
        if os.path.lexists(path):
            freed += _tree_mb(path)
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path)
    return {"ok": not any(os.path.lexists(p) for p in removed), "freed_mb": freed, "removed": removed}


# ---- GPU --------------------------------------------------------------------

def detect_gpu(env: Optional[Dict[str, str]] = None, dev_kfd: str = "/dev/kfd") -> Dict[str, Any]:
    """Was Ollama zur Laufzeit vorfindet. Vendor nvidia, amd oder none.

    NVIDIA: nvidia-smi im PATH (nur im NVIDIA-Image) und antwortet: Name,
    Speicher in MB, Treiber. nvidia-smi da, aber ohne Antwort (kein Treiber
    geladen, keine Karte): none mit Erklärung. AMD: /dev/kfd vorhanden; die
    ROCm-Bibliotheken von Ollama liegen nicht im Image, also CPU mit Hinweis.
    """
    env = dict(os.environ if env is None else env)
    smi = shutil.which("nvidia-smi", path=env.get("PATH", os.defpath))
    if smi:
        try:
            p = _run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                     timeout=15, env=env)
        except (OSError, subprocess.SubprocessError) as e:
            return {"vendor": "none", "name": "", "vram_mb": 0, "driver": "",
                    "detail": f"nvidia-smi ließ sich nicht ausführen ({e}); Ollama läuft auf der CPU"}
        lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
        if p.returncode == 0 and lines:
            best = None
            for ln in lines:
                parts = [x.strip() for x in ln.split(",")]
                if len(parts) < 3:
                    continue
                try:
                    vram = int(float(parts[1]))
                except ValueError:
                    vram = 0
                cand = {"vendor": "nvidia", "name": parts[0], "vram_mb": vram, "driver": parts[2],
                        "detail": f"{parts[0]}, {vram} MB, Treiber {parts[2]}"}
                if best is None or vram > best["vram_mb"]:
                    best = cand
            if best is not None:
                if len(lines) > 1:
                    best["detail"] += f" ({len(lines)} Karten, die größte zählt)"
                return best
        msg = (p.stderr or p.stdout).strip().splitlines()
        return {"vendor": "none", "name": "", "vram_mb": 0, "driver": "",
                "detail": "nvidia-smi vorhanden, aber keine Karte oder kein Treiber geladen"
                          + (f": {msg[0][:120]}" if msg else "") + "; Ollama läuft auf der CPU"}
    if os.path.exists(dev_kfd):
        return {"vendor": "amd", "name": "", "vram_mb": 0, "driver": "",
                "detail": "AMD-GPU (/dev/kfd) erkannt; die ROCm-Bibliotheken von Ollama liegen nicht im "
                          "Image, Ollama läuft auf der CPU"}
    return {"vendor": "none", "name": "", "vram_mb": 0, "driver": "",
            "detail": "keine NVIDIA-Karte erkannt (nvidia-smi fehlt); Ollama läuft auf der CPU"}


def recommend(gpu: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Vorschläge: erst was in den Speicher passt (in der Rangfolge der Liste), dann der Rest.

    Jeder Eintrag bekommt fits (passt in den VRAM) und default (Vorgabe).
    Ohne GPU ist das CPU-taugliche Modell die Vorgabe.
    """
    vram = int(gpu.get("vram_mb") or 0) if gpu.get("vendor") == "nvidia" else 0
    rows = []
    for m in RECOMMENDED:
        row = dict(m)
        row["fits"] = (vram >= m["vram_mb"]) if vram else bool(m["cpu_ok"])
        rows.append(row)
    rows.sort(key=lambda r: not r["fits"])          # stabil: Reihenfolge der Liste ist die Rangfolge
    for i, r in enumerate(rows):
        r["default"] = i == 0
    return rows


def recommended_default(gpu: Dict[str, Any]) -> str:
    return recommend(gpu)[0]["tag"]


# ---- Dienst -----------------------------------------------------------------

def systemctl_user(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return _run(["systemctl", "--user", *args], timeout=timeout)


def unit_state() -> Dict[str, Any]:
    """active/enabled der User-Unit; ohne systemctl (Build-Container) leer."""
    if not shutil.which("systemctl"):
        return {"active": "", "enabled": "", "available": False}
    act = systemctl_user("is-active", UNIT)
    ena = systemctl_user("is-enabled", UNIT)
    return {"active": act.stdout.strip(), "enabled": ena.stdout.strip(), "available": True}


def server_status(base_url: str = BASE_URL, timeout: float = 3.0) -> Dict[str, Any]:
    """Läuft der Dienst, welche Version, welche Modelle liegen da?"""
    out: Dict[str, Any] = {"running": False, "version": "", "models": [], "error": ""}
    try:
        v = _get_json(base_url + "/api/version", timeout=timeout)
        out["running"] = True
        out["version"] = str((v or {}).get("version", ""))
    except Exception as e:
        out["error"] = _error_text(e)
        return out
    try:
        out["models"] = list_models(base_url, timeout=timeout)
    except Exception as e:
        out["error"] = _error_text(e)
    return out


def list_models(base_url: str = BASE_URL, timeout: float = 5.0) -> List[Dict[str, Any]]:
    tags = _get_json(base_url + "/api/tags", timeout=timeout) or {}
    rows = []
    for m in tags.get("models") or []:
        details = m.get("details") or {}
        rows.append({"name": m.get("name") or m.get("model") or "", "size": int(m.get("size") or 0),
                     "size_gb": round(int(m.get("size") or 0) / 1e9, 1),
                     "parameter_size": details.get("parameter_size", ""),
                     "quantization": details.get("quantization_level", ""),
                     "family": details.get("family", "")})
    return [r for r in rows if r["name"]]


def show_model(base_url: str, name: str, timeout: float = 10.0) -> Dict[str, Any]:
    """Fähigkeiten (tools, thinking) und Kontextlänge aus /api/show."""
    info = _post_json(base_url + "/api/show", {"model": name}, timeout=timeout) or {}
    caps = [str(c) for c in (info.get("capabilities") or [])]
    ctx = 0
    for k, v in (info.get("model_info") or {}).items():
        if k.endswith(".context_length"):
            try:
                ctx = int(v)
            except (TypeError, ValueError):
                pass
    return {"name": name, "capabilities": caps, "tools": "tools" in caps,
            "thinking": "thinking" in caps, "context_length": ctx,
            "family": (info.get("details") or {}).get("family", ""),
            "parameter_size": (info.get("details") or {}).get("parameter_size", "")}


def wait_for_server(base_url: str = BASE_URL, seconds: float = 30.0, step: float = 0.5) -> bool:
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if server_status(base_url, timeout=1.5)["running"]:
            return True
        time.sleep(step)
    return False


def pull_model(base_url: str, name: str, progress: Optional[Callable[[Dict[str, Any]], None]] = None,
               timeout: float = 600.0) -> Dict[str, Any]:
    """Modell laden. /api/pull streamt JSON-Zeilen mit status, total, completed.

    progress bekommt je Zeile ein Dict: status, total, completed, percent.
    Rückgabe: {ok, status, error}. Ein bereits vorhandenes Modell ist sofort
    fertig ("success").
    """
    last: Dict[str, Any] = {"status": "", "total": 0, "completed": 0, "percent": 0}
    try:
        with _http("POST", base_url + "/api/pull", {"model": name, "stream": True}, timeout=timeout) as r:
            for raw in r:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if row.get("error"):
                    return {"ok": False, "status": last["status"], "error": str(row["error"])}
                total = int(row.get("total") or 0)
                done = int(row.get("completed") or 0)
                last = {"status": str(row.get("status", "")), "total": total, "completed": done,
                        "percent": int(done * 100 / total) if total else (100 if row.get("status") == "success" else 0)}
                if progress:
                    progress(last)
    except Exception as e:
        return {"ok": False, "status": last["status"], "error": _error_text(e)}
    ok = last["status"] == "success"
    return {"ok": ok, "status": last["status"], "error": "" if ok else "Ladevorgang endete ohne success"}


# ---- Endpunkt so prüfen, wie Hermes ihn benutzt -----------------------------

_TOOL = {"type": "function",
         "function": {"name": "get_time",
                      "description": "Liefert die aktuelle Uhrzeit des Rechners.",
                      "parameters": {"type": "object", "properties": {}, "required": []}}}
_PROBE_PROMPT = "Wie spät ist es gerade? Rufe dafür das Werkzeug get_time auf."


def check_endpoint(base_url: str = HERMES_BASE_URL, model: str = "", timeout: float = 120.0) -> Dict[str, Any]:
    """OpenAI-kompatibler Endpunkt: erreichbar, Modell gelistet, Werkzeugaufruf?

    Schickt eine Anfrage mit einer Werkzeugdefinition. tools ist True, wenn
    das Modell mit tool_calls antwortet, False, wenn es nur Text liefert,
    None, wenn die Anfrage scheitert.
    """
    out: Dict[str, Any] = {"ok": False, "reachable": False, "model_present": False, "tools": None,
                           "reply": "", "error": ""}
    try:
        listing = _get_json(base_url.rstrip("/") + "/models", timeout=10) or {}
    except Exception as e:
        out["error"] = _error_text(e)
        return out
    out["reachable"] = True
    ids = [str(m.get("id", "")) for m in (listing.get("data") or [])]
    out["models"] = ids
    if not model:
        out["error"] = "kein Modell angegeben"
        return out
    out["model_present"] = model in ids or model + ":latest" in ids
    if not out["model_present"]:
        out["error"] = f"Modell {model} ist nicht geladen (vorhanden: {', '.join(ids) or 'keins'})"
        return out
    body = {"model": model, "messages": [{"role": "user", "content": _PROBE_PROMPT}],
            "tools": [_TOOL], "temperature": 0, "max_tokens": 256, "stream": False}
    try:
        resp = _post_json(base_url.rstrip("/") + "/chat/completions", body, timeout=timeout) or {}
    except Exception as e:
        out["error"] = _error_text(e)
        return out
    choice = ((resp.get("choices") or [{}])[0]).get("message") or {}
    calls = choice.get("tool_calls") or []
    out["reply"] = (choice.get("content") or "")[:200]
    out["tools"] = any(((c.get("function") or {}).get("name") == "get_time") for c in calls)
    out["ok"] = True
    if not out["tools"]:
        out["error"] = "Das Modell hat geantwortet, aber kein Werkzeug aufgerufen"
    return out


# ---- Hermes-Konfiguration ---------------------------------------------------

def hermes_home() -> str:
    return os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")


def config_path() -> str:
    return os.path.join(hermes_home(), "config.yaml")


def _load_config(path: str) -> Dict[str, Any]:
    import yaml
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} ist kein YAML-Mapping")
    return cfg


def _save_config(path: str, cfg: Dict[str, Any]) -> None:
    """Atomar (Temp-Datei, rename), Rechte 0600. Kommentare gehen wie bei
    jedem YAML-Roundtrip verloren; Hermes' eigenes save_config macht das genauso."""
    import yaml
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config.yaml.", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_hermes_model(path: Optional[str] = None) -> Dict[str, Any]:
    """model-Block aus config.yaml (leer, wenn Datei oder Block fehlen)."""
    block = _load_config(path or config_path()).get("model")
    if isinstance(block, str):
        return {"default": block}
    return dict(block or {})


def is_local(model_block: Dict[str, Any]) -> bool:
    url = str(model_block.get("base_url") or "")
    return model_block.get("provider") == HERMES_PROVIDER and re.match(r"^https?://(127\.0\.0\.1|localhost)(:|/)", url) is not None


def write_hermes_config(model: str, path: Optional[str] = None, base_url: str = HERMES_BASE_URL,
                        provider: str = HERMES_PROVIDER, api_mode: str = HERMES_API_MODE,
                        context_length: int = CONTEXT_LENGTH) -> Dict[str, Any]:
    """Hermes auf den lokalen Endpunkt stellen, wie Hermes' Wizard für einen
    Custom-Endpunkt ohne Schlüssel (_persist_model), plus was ein Agent mit
    Werkzeugen an Ollama braucht:

    - model.context_length: deckelt, was Hermes aus /api/show liest (GGUF
      meldet 256k, der Dienst bedient 64k)
    - model.ollama_num_ctx: hebt über die 64k-Untergrenze, auch wenn das
      Modell selbst weniger meldet
    - agent.reasoning_effort none: Hermes schickt dann think:false; sonst
      denkt ein Qwen3.5 vor jedem Werkzeugschritt, langsam auf kleiner GPU
    Alles andere in der Datei bleibt. Ein alter api_key im Block geht weg,
    Ollama braucht keinen; Hermes schickt selbst "no-key-required".
    """
    path = path or config_path()
    cfg = _load_config(path)
    block = cfg.get("model")
    if not isinstance(block, dict):
        block = {"default": block} if isinstance(block, str) else {}
    for stale in ("api_key", "key_env", "api_key_env"):
        block.pop(stale, None)
    block.update({"default": model, "provider": provider, "base_url": base_url, "api_mode": api_mode,
                  "context_length": int(context_length), "ollama_num_ctx": int(context_length)})
    cfg["model"] = block
    agent = cfg.get("agent")
    if not isinstance(agent, dict):
        agent = {}
    agent["reasoning_effort"] = "none"
    cfg["agent"] = agent
    _save_config(path, cfg)
    return dict(block)


def previous_model_path() -> str:
    """Wo der vorherige Stand liegt, während das lokale Modell aktiv ist."""
    return os.path.join(hermes_home(), "hermes-os", "local-previous-model.json")


def remember_previous(path: Optional[str] = None) -> bool:
    """Den Stand vor dem Umschalten merken (model-Block und agent.reasoning_effort),
    damit `aus` ihn zurückholt. Steht Hermes schon auf dem lokalen Endpunkt,
    bleibt die Merkdatei, wie sie ist: sonst überschriebe der zweite Wechsel
    den Cloud-Stand. False, wenn nichts gemerkt wurde."""
    cfg = _load_config(path or config_path())
    block = cfg.get("model")
    if isinstance(block, str):
        block = {"default": block}
    if isinstance(block, dict) and is_local(block):
        return False
    agent = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    mem = previous_model_path()
    os.makedirs(os.path.dirname(mem), exist_ok=True)
    with open(mem, "w", encoding="utf-8") as f:
        json.dump({"model": block if isinstance(block, dict) and block else None,
                   "reasoning_effort": agent.get("reasoning_effort")}, f, ensure_ascii=False, indent=2)
    os.chmod(mem, 0o600)
    return True


def restore_previous(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Den gemerkten Stand zurück in config.yaml schreiben und die Merkdatei
    löschen. Rückgabe: der zurückgeholte model-Block, {} wenn vorher keiner
    da war (Block wird entfernt), None wenn nichts gemerkt war."""
    mem = previous_model_path()
    if not os.path.isfile(mem):
        return None
    with open(mem, encoding="utf-8") as f:
        saved = json.load(f)
    path = path or config_path()
    cfg = _load_config(path)
    block = saved.get("model")
    if isinstance(block, dict) and block:
        cfg["model"] = block
    else:
        cfg.pop("model", None)
    agent = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    if saved.get("reasoning_effort") is None:
        agent.pop("reasoning_effort", None)
    else:
        agent["reasoning_effort"] = saved["reasoning_effort"]
    if agent:
        cfg["agent"] = agent
    else:
        cfg.pop("agent", None)
    _save_config(path, cfg)
    os.unlink(mem)
    return dict(block) if isinstance(block, dict) and block else {}


def status_summary(base_url: str = BASE_URL) -> Dict[str, Any]:
    """Alles auf einmal, für Helfer, Brücke und ujust: GPU, Dienst, Modelle, Hermes."""
    gpu = detect_gpu()
    srv = server_status(base_url)
    model_block = {}
    try:
        model_block = read_hermes_model()
    except Exception as e:  # kaputte config.yaml soll den Status nicht verhindern
        model_block = {"error": str(e)}
    ollama = ollama_installed()
    ollama.update(need_mb=INSTALL_NEED_MB, size_mb=INSTALL_SIZE_MB, free_mb=free_mb(OLLAMA_DIR))
    return {"gpu": gpu, "unit": unit_state(), "server": srv,
            "ollama_installed": ollama["installed"], "ollama": ollama,
            "models_free_mb": free_mb(MODELS_DIR),
            "recommended": recommend(gpu),
            "hermes": {"model": model_block.get("default", ""), "provider": model_block.get("provider", ""),
                       "base_url": model_block.get("base_url", ""), "local": is_local(model_block),
                       "previous_saved": os.path.isfile(previous_model_path())}}
