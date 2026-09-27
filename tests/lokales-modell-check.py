#!/usr/bin/python3
# =============================================================================
# hermes-os -- lokales Modell prüfen: GPU-Erkennung, Config-Schreibweg, Endpunkt
# =============================================================================
# Prüft files/system/usr/share/hermes-os/local/local_model.py ohne GPU, ohne
# Ollama und ohne Hermes:
#   1. GPU-Erkennung gegen Attrappen: ein nvidia-smi im PATH, das eine RTX 3060
#      meldet; eines, das scheitert (kein Treiber); ein /dev/kfd für AMD; nichts.
#   2. Modellvorschlag je nach Speicher.
#   3. Config-Schreibweg gegen eine Wegwerf-config.yaml aus der Vorlage: der
#      model-Block kommt hinein, der Rest bleibt, Rechte 0600, zweimal schreiben
#      ändert nichts mehr.
#   4. Endpunktprüfung gegen einen nachgebauten Ollama-Server auf 127.0.0.1:
#      /api/version, /api/tags, /api/show, /api/pull als Strom, /v1/models und
#      /v1/chat/completions mit und ohne Werkzeugaufruf.
#   5. Nachladen (Ollama liegt nicht im Image) gegen ein nachgebautes
#      Release-Archiv über file://: falsche Prüfsumme installiert nichts,
#      richtige entpackt ohne cuda_v12 und schreibt den Stempel, zu wenig Platz
#      bricht vorher ab, zweiter Aufruf überspringt, Entfernen räumt auf.
#      Braucht tar und zstd, sonst nur ein Hinweis.
#   6. Den Helfer /usr/libexec/hermes-os-lokal (--json status, pruefen,
#      installieren, entfernen) gegen denselben Server, wenn er im Repo bzw.
#      Image liegt.
#
# Kein Schritt geht ins Internet. Läuft mit jedem Python 3.9+ mit PyYAML:
#   tests/lokales-modell-check.py [--local-dir DIR] [--helper PFAD] [--template DATEI]
# Exit 0 = alles sauber. `make lint` und das Gate (80-validate.sh) führen ihn aus.
# =============================================================================
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {
    "qwen3:14b": {"size": 9_300_000_000, "family": "qwen3", "parameter_size": "14.8B",
                  "quant": "Q4_K_M", "caps": ["completion", "tools", "thinking"], "ctx": 40960},
    "textonly:latest": {"size": 1_000_000_000, "family": "llama", "parameter_size": "1B",
                        "quant": "Q4_0", "caps": ["completion"], "ctx": 4096},
}


class FakeOllama(BaseHTTPRequestHandler):
    """Die Endpunkte, die local_model.py benutzt, mit Ollamas Antwortformen."""
    calls = []

    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_GET(self):
        FakeOllama.calls.append(("GET", self.path))
        if self.path == "/api/version":
            return self._json(200, {"version": "0.12.99"})
        if self.path == "/api/tags":
            return self._json(200, {"models": [
                {"name": n, "model": n, "size": m["size"],
                 "details": {"family": m["family"], "parameter_size": m["parameter_size"],
                             "quantization_level": m["quant"]}} for n, m in MODELS.items()]})
        if self.path == "/v1/models":
            return self._json(200, {"object": "list", "data": [{"id": n, "object": "model"} for n in MODELS]})
        self._json(404, {"error": "unbekannt"})

    def do_POST(self):
        body = self._body()
        FakeOllama.calls.append(("POST", self.path, body))
        if self.path == "/api/show":
            m = MODELS.get(body.get("model", ""))
            if not m:
                return self._json(404, {"error": f"model '{body.get('model')}' not found"})
            return self._json(200, {"capabilities": m["caps"],
                                    "details": {"family": m["family"], "parameter_size": m["parameter_size"]},
                                    "model_info": {f"{m['family']}.context_length": m["ctx"]}})
        if self.path == "/api/pull":
            name = body.get("model") or body.get("name") or ""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            if name not in MODELS and name != "neu:8b":
                self.wfile.write((json.dumps({"error": f"pull model manifest: file does not exist: {name}"}) + "\n").encode())
                return
            total = 4_000_000
            self.wfile.write((json.dumps({"status": "pulling manifest"}) + "\n").encode())
            for done in (0, 1_000_000, 2_500_000, 4_000_000):
                self.wfile.write((json.dumps({"status": "pulling abc123", "digest": "sha256:abc123",
                                              "total": total, "completed": done}) + "\n").encode())
                self.wfile.flush()
            for st in ("verifying sha256 digest", "writing manifest", "success"):
                self.wfile.write((json.dumps({"status": st}) + "\n").encode())
            return
        if self.path == "/v1/chat/completions":
            model = body.get("model", "")
            if model not in MODELS and model + ":latest" in MODELS:
                model += ":latest"          # Ollama ergänzt :latest selbst
            if model not in MODELS:
                return self._json(404, {"error": {"message": f"model '{model}' not found", "type": "api_error"}})
            wants_tool = bool(body.get("tools")) and "tools" in MODELS[model]["caps"]
            msg = {"role": "assistant", "content": None if wants_tool else "Es ist 12 Uhr, glaube ich."}
            if wants_tool:
                msg["tool_calls"] = [{"id": "call_1", "type": "function",
                                      "function": {"name": body["tools"][0]["function"]["name"], "arguments": "{}"}}]
            return self._json(200, {"id": "chatcmpl-1", "object": "chat.completion", "model": model,
                                    "choices": [{"index": 0, "message": msg,
                                                 "finish_reason": "tool_calls" if wants_tool else "stop"}]})
        self._json(404, {"error": "unbekannt"})


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-dir", default=os.environ.get("HERMES_OS_LOCAL_DIR", "/usr/share/hermes-os/local"))
    ap.add_argument("--helper", default="", help="Pfad zu hermes-os-lokal (Vorgabe: Repo oder /usr/libexec)")
    ap.add_argument("--template", default="", help="config.yaml.default (Vorgabe: Repo oder /usr/share/hermes-os)")
    args = ap.parse_args()
    module_path = os.path.join(args.local_dir, "local_model.py")
    if not os.path.isfile(module_path):
        print(f"FEHL  {module_path} fehlt")
        return 1
    helper = args.helper or next((p for p in (os.path.join(repo, "files/system/usr/libexec/hermes-os-lokal"),
                                              "/usr/libexec/hermes-os-lokal") if os.path.isfile(p)), "")
    template = args.template or next((p for p in (os.path.join(repo, "files/system/usr/share/hermes-os/config.yaml.default"),
                                                  "/usr/share/hermes-os/config.yaml.default") if os.path.isfile(p)), "")

    fail = 0

    def check(ok, label, detail=""):
        nonlocal fail
        if ok:
            print(f"OK    {label}")
        else:
            fail = 1
            print(f"FEHL  {label}" + (f": {detail}" if detail else ""))

    tmp = tempfile.mkdtemp(prefix="hermes-lokal-")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, name="fake-ollama", daemon=True).start()
    host = f"127.0.0.1:{port}"
    os.environ["OLLAMA_HOST"] = host          # Modul und Helfer sprechen den Nachbau an
    os.environ["HERMES_HOME"] = os.path.join(tmp, "home")
    os.makedirs(os.environ["HERMES_HOME"])
    # Nachladen und Entfernen nur in Wegwerf-Ordnern, nie im echten Home
    os.environ["HERMES_OS_OLLAMA_DIR"] = os.path.join(tmp, "share", "hermes-os", "ollama")
    os.environ["HERMES_OS_OLLAMA_MODELS_DIR"] = os.path.join(tmp, "share", "ollama")
    os.environ["HERMES_OS_OLLAMA_URL"] = "file:///nirgends/" + "ollama-linux-amd64.tar.zst"

    spec = importlib.util.spec_from_file_location("hermes_os_local_model", module_path)
    lm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lm)
    base = f"http://{host}"
    check(lm.BASE_URL == base and lm.HERMES_BASE_URL == base + "/v1", "OLLAMA_HOST biegt die Adresse um", lm.BASE_URL)

    try:
        # ---- 1. GPU-Erkennung gegen Attrappen ----------------------------------
        fake_bin = os.path.join(tmp, "bin-ok")
        os.makedirs(fake_bin)
        smi = os.path.join(fake_bin, "nvidia-smi")
        with open(smi, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\ncase "$*" in *query-gpu*) echo "NVIDIA GeForce RTX 3060, 12288, 615.71.09";; *) echo "hilfe";; esac\n')
        os.chmod(smi, 0o755)
        env = {"PATH": fake_bin + os.pathsep + os.environ.get("PATH", "")}
        g = lm.detect_gpu(env=env, dev_kfd=os.path.join(tmp, "kein-kfd"))
        check(g["vendor"] == "nvidia" and g["vram_mb"] == 12288 and g["driver"] == "615.71.09"
              and "RTX 3060" in g["name"], "GPU-Attrappe: RTX 3060 mit 12288 MB erkannt", str(g))
        fake_bad = os.path.join(tmp, "bin-bad")
        os.makedirs(fake_bad)
        with open(os.path.join(fake_bad, "nvidia-smi"), "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\necho "NVIDIA-SMI has failed because it couldn\'t communicate with the NVIDIA driver." >&2\nexit 9\n')
        os.chmod(os.path.join(fake_bad, "nvidia-smi"), 0o755)
        g = lm.detect_gpu(env={"PATH": fake_bad}, dev_kfd=os.path.join(tmp, "kein-kfd"))
        check(g["vendor"] == "none" and "Treiber" in g["detail"] and "CPU" in g["detail"],
              "nvidia-smi ohne Treiber: keine GPU, Hinweis auf CPU", str(g))
        kfd = os.path.join(tmp, "kfd")
        open(kfd, "w").close()
        g = lm.detect_gpu(env={"PATH": os.path.join(tmp, "leer")}, dev_kfd=kfd)
        check(g["vendor"] == "amd" and "ROCm" in g["detail"], "AMD über /dev/kfd erkannt, Hinweis auf CPU", str(g))
        g = lm.detect_gpu(env={"PATH": os.path.join(tmp, "leer")}, dev_kfd=os.path.join(tmp, "kein-kfd"))
        check(g["vendor"] == "none" and g["vram_mb"] == 0 and "CPU" in g["detail"], "ohne nvidia-smi und /dev/kfd: CPU", str(g))
        # Zwei Karten: die größte zählt
        with open(smi, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\necho "NVIDIA GeForce GTX 1650, 4096, 615.71.09"\necho "NVIDIA GeForce RTX 3060, 12288, 615.71.09"\n')
        g = lm.detect_gpu(env=env, dev_kfd=os.path.join(tmp, "kein-kfd"))
        check(g["vram_mb"] == 12288 and "2 Karten" in g["detail"], "zwei Karten: die größte zählt", str(g))

        # ---- 2. Vorschläge ---------------------------------------------------------
        r12 = lm.recommend({"vendor": "nvidia", "vram_mb": 12288})
        r8 = lm.recommend({"vendor": "nvidia", "vram_mb": 8192})
        r0 = lm.recommend({"vendor": "none", "vram_mb": 0})
        check(r12[0]["tag"] == "qwen3.5:9b" and r12[0]["default"] and all(r["fits"] for r in r12),
              "12 GB: qwen3.5:9b als Vorgabe, alle passen", str([(r["tag"], r["fits"]) for r in r12]))
        check(r8[0]["tag"] == "qwen3.5:4b" and not [r for r in r8 if r["tag"] == "qwen3.5:9b"][0]["fits"],
              "8 GB: qwen3.5:4b als Vorgabe, 9B passt nicht", str([(r["tag"], r["fits"]) for r in r8]))
        check(r0[0]["tag"] == "qwen3.5:4b" and r0[0]["cpu_ok"], "ohne GPU: CPU-Modell als Vorgabe", str(r0[0]))
        check(lm.recommended_default({"vendor": "amd", "vram_mb": 0}) == "qwen3.5:4b", "AMD ohne ROCm: CPU-Modell")
        check(all(r["tools"] for r in lm.RECOMMENDED) and all(r["vram_mb"] <= 11000 for r in lm.RECOMMENDED)
              and lm.CONTEXT_LENGTH >= 64000, "alle Vorschläge mit Werkzeugen, unter 11 GB, Kontext mindestens 64k (Hermes-Untergrenze)")

        # ---- 3. Config-Schreibweg -------------------------------------------------
        cfg_path = os.path.join(os.environ["HERMES_HOME"], "config.yaml")
        if template:
            with open(template, encoding="utf-8") as src, open(cfg_path, "w", encoding="utf-8") as dst:
                dst.write(src.read())
        else:
            with open(cfg_path, "w", encoding="utf-8") as dst:
                dst.write("checkpoints:\n  enabled: true\napprovals:\n  mode: smart\n  smart_policy: |\n    Zeile eins\n    Zeile zwei\n")
        check(lm.read_hermes_model() == {} and not lm.is_local({}), "Vorlage hat keinen model-Block")
        import yaml
        before = yaml.safe_load(open(cfg_path, encoding="utf-8"))
        written = lm.write_hermes_config("qwen3:14b")
        after = yaml.safe_load(open(cfg_path, encoding="utf-8"))
        check(after["model"] == {"default": "qwen3:14b", "provider": "custom", "base_url": base + "/v1",
                                 "api_mode": "chat_completions", "context_length": 65536, "ollama_num_ctx": 65536}
              and written == after["model"] and "api_key" not in after["model"],
              "model-Block: default, provider custom, base_url /v1, chat_completions, 64k Kontext, kein Schlüssel", str(after.get("model")))
        check(after["agent"] == {"reasoning_effort": "none"}, "agent.reasoning_effort none (Hermes schickt think:false)", str(after.get("agent")))
        rest_before = {k: v for k, v in before.items() if k not in ("model", "agent")}
        rest_after = {k: v for k, v in after.items() if k not in ("model", "agent")}
        check(rest_before == rest_after and "smart_policy" in after.get("approvals", {}),
              "der Rest der config.yaml bleibt unverändert (auch mehrzeilige Werte)")
        check(stat.S_IMODE(os.stat(cfg_path).st_mode) == 0o600, "config.yaml hat 0600", oct(os.stat(cfg_path).st_mode))
        check(lm.read_hermes_model()["default"] == "qwen3:14b" and lm.is_local(lm.read_hermes_model()),
              "read_hermes_model liest zurück, is_local erkennt den lokalen Endpunkt")
        text1 = open(cfg_path, encoding="utf-8").read()
        lm.write_hermes_config("qwen3:14b")
        check(open(cfg_path, encoding="utf-8").read() == text1, "zweites Schreiben ändert nichts")
        # Ein fremder Anbieter davor: seine Schlüssel im Block werden ersetzt, Fremdes bleibt
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("model:\n  default: anthropic/claude-sonnet-5\n  provider: openrouter\n  base_url: https://openrouter.ai/api/v1\n  api_mode: chat_completions\n  api_key: ${OPENROUTER_API_KEY}\n  extra: bleibt\nagent:\n  reasoning_effort: high\n  max_turns: 40\nterminal:\n  backend: local\n")
        lm.write_hermes_config("qwen3:8b")
        after = yaml.safe_load(open(cfg_path, encoding="utf-8"))
        check(after["model"]["default"] == "qwen3:8b" and after["model"]["provider"] == "custom"
              and after["model"]["base_url"] == base + "/v1" and after["model"]["extra"] == "bleibt"
              and "api_key" not in after["model"] and after["terminal"]["backend"] == "local"
              and after["agent"] == {"reasoning_effort": "none", "max_turns": 40},
              "Cloud-Anbieter wird ersetzt, alter api_key weg, unbekannte Schlüssel und agent.max_turns bleiben", str(after))
        check(not lm.is_local({"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"})
              and not lm.is_local({"provider": "custom", "base_url": "https://example.org/v1"}),
              "is_local: nur custom auf 127.0.0.1/localhost")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("model: gpt-6\n")
        lm.write_hermes_config("qwen3:4b")
        after = yaml.safe_load(open(cfg_path, encoding="utf-8"))
        check(after["model"]["default"] == "qwen3:4b", "model als nackter String wird zum Block")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("- liste\n")
        try:
            lm.write_hermes_config("qwen3:4b")
            check(False, "kaputte config.yaml (Liste statt Mapping) wird abgewiesen")
        except ValueError:
            check(True, "kaputte config.yaml (Liste statt Mapping) wird abgewiesen")
        os.remove(cfg_path)
        lm.write_hermes_config("qwen3:14b")
        check(os.path.isfile(cfg_path), "ohne config.yaml wird eine angelegt")
        # Vorherigen Stand merken und zurückholen (ujust hermes-lokal-aus)
        cloud = {"default": "anthropic/claude-sonnet-5", "provider": "openrouter",
                 "base_url": "https://openrouter.ai/api/v1", "api_mode": "chat_completions"}
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"model": dict(cloud), "agent": {"reasoning_effort": "high"}, "terminal": {"backend": "local"}}, f)
        check(lm.remember_previous() is True, "Cloud-Stand gemerkt")
        lm.write_hermes_config("qwen3.5:9b")
        check(lm.remember_previous() is False, "lokal aktiv: zweites Merken überschreibt den Cloud-Stand nicht")
        lm.write_hermes_config("qwen3.5:4b")
        saved = json.load(open(lm.previous_model_path()))
        check(saved == {"model": cloud, "reasoning_effort": "high"}
              and stat.S_IMODE(os.stat(lm.previous_model_path()).st_mode) == 0o600,
              "Merkdatei: model-Block und reasoning_effort, 0600", str(saved))
        back = lm.restore_previous()
        after = yaml.safe_load(open(cfg_path, encoding="utf-8"))
        check(back == cloud and after["model"] == cloud and after["agent"] == {"reasoning_effort": "high"}
              and after["terminal"]["backend"] == "local" and not os.path.isfile(lm.previous_model_path()),
              "zurückgeholt: Cloud-Block und reasoning_effort stehen wieder, Merkdatei weg", str(after))
        check(lm.restore_previous() is None, "nichts gemerkt: restore liefert None")
        # Frische Installation: vorher kein Anbieter, kein agent-Block
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"terminal": {"backend": "local"}}, f)
        lm.remember_previous()
        lm.write_hermes_config("qwen3.5:9b")
        back = lm.restore_previous()
        after = yaml.safe_load(open(cfg_path, encoding="utf-8"))
        check(back == {} and "model" not in after and "agent" not in after and after["terminal"]["backend"] == "local",
              "ohne vorherigen Anbieter: Block und agent-Eintrag werden wieder entfernt", str(after))
        lm.write_hermes_config("qwen3:14b")                      # Stand für die folgenden Prüfungen

        # ---- 4. Endpunkt gegen den Nachbau ------------------------------------------
        st = lm.server_status()
        check(st["running"] and st["version"] == "0.12.99" and [m["name"] for m in st["models"]] == list(MODELS)
              and st["models"][0]["size_gb"] == 9.3 and st["models"][0]["quantization"] == "Q4_K_M",
              "server_status: Version und Modelle mit Größe und Quantisierung", str(st))
        st_down = lm.server_status("http://127.0.0.1:1")
        check(not st_down["running"] and "nicht erreichbar" in st_down["error"], "server_status ohne Dienst: nicht erreichbar", str(st_down))
        info = lm.show_model(base, "qwen3:14b")
        check(info["tools"] and info["thinking"] and info["context_length"] == 40960 and info["parameter_size"] == "14.8B",
              "show_model: Fähigkeiten und Kontextlänge", str(info))
        seen = []
        res = lm.pull_model(base, "neu:8b", progress=seen.append)
        percents = [s["percent"] for s in seen if s["status"].startswith("pulling abc")]
        check(res["ok"] and res["status"] == "success" and percents == [0, 25, 62, 100]
              and seen[-1]["status"] == "success" and seen[-1]["percent"] == 100,
              "pull_model: Fortschritt 0, 25, 62, 100 und success", f"{res} {percents}")
        res = lm.pull_model(base, "gibtesnicht:1b", progress=seen.append)
        check(not res["ok"] and "does not exist" in res["error"], "pull_model: unbekanntes Modell meldet Fehler", str(res))
        ep = lm.check_endpoint(base + "/v1", "qwen3:14b")
        check(ep["ok"] and ep["reachable"] and ep["model_present"] and ep["tools"] is True and ep["error"] == "",
              "check_endpoint: Werkzeugaufruf kommt zurück", str(ep))
        sent = [c for c in FakeOllama.calls if c[0] == "POST" and c[1] == "/v1/chat/completions"][-1][2]
        check(sent["tools"][0]["function"]["name"] == "get_time" and sent["stream"] is False
              and sent["messages"][0]["role"] == "user", "check_endpoint schickt tools wie Hermes (chat_completions)", str(sent)[:200])
        ep = lm.check_endpoint(base + "/v1", "textonly")
        check(ep["ok"] and ep["model_present"] and ep["tools"] is False and "kein Werkzeug" in ep["error"],
              "check_endpoint: Modell ohne Werkzeugaufruf wird erkannt (auch ohne :latest)", str(ep))
        ep = lm.check_endpoint(base + "/v1", "fehlt:7b")
        check(ep["reachable"] and not ep["model_present"] and not ep["ok"] and "nicht geladen" in ep["error"],
              "check_endpoint: fehlendes Modell", str(ep))
        ep = lm.check_endpoint("http://127.0.0.1:1/v1", "qwen3:14b")
        check(not ep["reachable"] and ep["tools"] is None, "check_endpoint: Dienst aus", str(ep))
        st = lm.status_summary()
        check(st["server"]["running"] and st["hermes"]["local"] and st["hermes"]["model"] == "qwen3:14b"
              and st["recommended"][0]["tag"] in ("qwen3.5:4b", "qwen3.5:9b") and "vendor" in st["gpu"]
              and st["ollama_installed"] is False and st["ollama"]["pin"] == lm.OLLAMA_PIN
              and st["ollama"]["need_mb"] > st["ollama"]["size_mb"] > 0 and st["models_free_mb"] > 0,
              "status_summary fasst GPU, Ollama (nicht installiert), Platz, Dienst und Hermes zusammen", str(st)[:300])

        # ---- 5. Nachladen gegen ein nachgebautes Release-Archiv ---------------------
        check(lm.OLLAMA_BIN == os.path.join(os.environ["HERMES_OS_OLLAMA_DIR"], "bin", "ollama")
              and lm.OLLAMA_URL.startswith("https://github.com/ollama/ollama/releases/download/v" + lm.OLLAMA_PIN + "/")
              and len(lm.OLLAMA_SHA256) == 64, "Pin: Version, Release-Adresse und SHA256, Ziel im Home", lm.OLLAMA_BIN)
        need, known = lm.model_need_mb("qwen3.5:9b")
        check(known and need >= 6600 + lm.MODEL_MARGIN_MB and lm.model_need_mb("eigenes:7b") == (lm.UNKNOWN_MODEL_MIN_MB, False),
              "Platzbedarf: bekanntes Modell mit Luft, eigenes mit Untergrenze", str((need, known)))
        check(lm.space_check(1, tmp)["ok"] and not lm.space_check(10 ** 9, tmp)["ok"]
              and "Zu wenig Platz" in lm.space_check(10 ** 9, tmp)["error"]
              and lm.free_mb(os.path.join(tmp, "gibt", "es", "nicht")) == lm.free_mb(tmp),
              "space_check und free_mb (auch für einen Ordner, den es noch nicht gibt)")
        if shutil.which("tar") and shutil.which("zstd"):
            src = os.path.join(tmp, "release")
            os.makedirs(os.path.join(src, "bin"))
            for sub in ("", "cuda_v12", "cuda_v13", "vulkan"):
                os.makedirs(os.path.join(src, "lib", "ollama", sub), exist_ok=True)
                with open(os.path.join(src, "lib", "ollama", sub, "libggml-test.so"), "wb") as f:
                    f.write(b"\0" * 4096)
            fake = os.path.join(src, "bin", "ollama")
            with open(fake, "w", encoding="utf-8") as f:
                f.write(f'#!/bin/sh\necho "ollama version is {lm.OLLAMA_PIN}"\n')
            os.chmod(fake, 0o755)
            archive = os.path.join(tmp, lm.OLLAMA_ASSET)
            subprocess.run(["tar", "--zstd", "-cf", archive, "-C", src, "bin", "lib"], check=True)
            with open(archive, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            url = "file://" + urllib.request.pathname2url(archive)
            dest = lm.OLLAMA_DIR
            parent = os.path.dirname(dest)
            res = lm.install_ollama(url=url, sha256="0" * 64)
            check(not res["ok"] and "Prüfsumme" in res["error"] and not os.path.exists(dest)
                  and not glob.glob(os.path.join(parent, ".ollama-install-*")),
                  "falsche Prüfsumme: nichts installiert, nichts liegen gelassen", str(res))
            seen = []
            res = lm.install_ollama(progress=seen.append, url=url, sha256=sha)
            stamp = open(lm.OLLAMA_STAMP, encoding="utf-8").read() if os.path.isfile(lm.OLLAMA_STAMP) else ""
            check(res["ok"] and not res["skipped"] and os.access(lm.OLLAMA_BIN, os.X_OK)
                  and os.path.isdir(os.path.join(dest, "lib", "ollama", "cuda_v13"))
                  and not os.path.exists(os.path.join(dest, "lib", "ollama", "cuda_v12"))
                  and f"version={lm.OLLAMA_PIN}\n" in stamp and "backends=cpu cuda_v13 vulkan\n" in stamp
                  and f"sha256={sha}\n" in stamp and seen and seen[-1]["percent"] == 100
                  and not glob.glob(os.path.join(parent, ".ollama-install-*")),
                  "richtige Prüfsumme: installiert ohne cuda_v12, Stempel mit Version und Backends, Fortschritt bis 100",
                  f"{res} {stamp!r}")
            info = lm.ollama_installed()
            check(info["installed"] and info["version"] == lm.OLLAMA_PIN, "ollama_installed liest den Stempel", str(info))
            res = lm.install_ollama(url="file:///gibt/es/nicht", sha256=sha)
            check(res["ok"] and res["skipped"], "zweiter Aufruf: gleiche Version liegt schon da, kein Download", str(res))
            orig_free = lm.free_mb
            lm.free_mb = lambda path: 100
            try:
                res = lm.install_ollama(url=url, sha256=sha, force=True)
            finally:
                lm.free_mb = orig_free
            check(not res["ok"] and "Zu wenig Platz" in res["error"] and os.access(lm.OLLAMA_BIN, os.X_OK),
                  "zu wenig Platz: Abbruch vor dem Download, vorhandenes Ollama bleibt", str(res))
            os.makedirs(os.path.join(lm.MODELS_DIR, "models"), exist_ok=True)
            with open(os.path.join(lm.MODELS_DIR, "models", "blob"), "wb") as f:
                f.write(b"\0" * 4096)
            res = lm.remove_ollama(models=True)
            check(res["ok"] and not os.path.exists(dest) and not os.path.exists(lm.MODELS_DIR)
                  and sorted(res["removed"]) == sorted([dest, lm.MODELS_DIR]),
                  "remove_ollama löscht Programm und Modelle", str(res))
            os.environ["HERMES_OS_OLLAMA_URL"] = url            # für den Helfer unten
            os.environ["HERMES_OS_OLLAMA_SHA256"] = sha
        else:
            print("WARN  tar oder zstd fehlt, Nachladen nicht geprüft")

        # ---- 6. Helfer ------------------------------------------------------------------
        if helper:
            env = dict(os.environ)
            env["HERMES_OS_LOCAL_DIR"] = args.local_dir
            # Ein systemctl, das nur mitschreibt: der Test darf keinen echten
            # Nutzerdienst stoppen, falls er auf einem hermes-os-Desktop läuft.
            fake_sys = os.path.join(tmp, "bin-systemctl")
            os.makedirs(fake_sys)
            with open(os.path.join(fake_sys, "systemctl"), "w", encoding="utf-8") as f:
                f.write(f'#!/bin/sh\necho "$*" >> "{os.path.join(tmp, "systemctl.log")}"\nexit 0\n')
            os.chmod(os.path.join(fake_sys, "systemctl"), 0o755)
            env["PATH"] = fake_sys + os.pathsep + os.path.join(tmp, "leer") + os.pathsep + env.get("PATH", "")
            p = subprocess.run([sys.executable, helper, "--json", "status"], capture_output=True, text=True, env=env, timeout=60)
            try:
                js = json.loads(p.stdout.strip().splitlines()[-1])
            except Exception:
                js = {}
            check(p.returncode == 0 and js.get("server", {}).get("running") and js.get("hermes", {}).get("local"),
                  "hermes-os-lokal --json status gegen den Nachbau", (p.stdout + p.stderr)[-300:])
            p = subprocess.run([sys.executable, helper, "pruefen", "qwen3:14b"], capture_output=True, text=True, env=env, timeout=120)
            check(p.returncode == 0 and "Werkzeugaufruf" in p.stdout, "hermes-os-lokal pruefen meldet den Werkzeugaufruf", (p.stdout + p.stderr)[-300:])
            p = subprocess.run([sys.executable, helper, "pruefen", "textonly:latest"], capture_output=True, text=True, env=env, timeout=120)
            check(p.returncode != 0 and "kein Werkzeug" in p.stdout + p.stderr, "hermes-os-lokal pruefen scheitert ohne Werkzeugaufruf", (p.stdout + p.stderr)[-300:])
            # Im JSON für den Assistenten heißt ok „bereit für Hermes“: ohne Werkzeugaufruf false
            p = subprocess.run([sys.executable, helper, "--json", "pruefen", "textonly:latest"], capture_output=True, text=True, env=env, timeout=120)
            steps = []
            for line in p.stdout.splitlines():
                try:
                    steps.append(json.loads(line))
                except ValueError:
                    pass
            chk = next((d for d in steps if isinstance(d, dict) and d.get("step") == "check"), {})
            check(chk.get("ok") is False and chk.get("tools") is False and "kein Werkzeug" in (chk.get("error") or ""),
                  "hermes-os-lokal --json pruefen meldet ok=false ohne Werkzeugaufruf", str(chk)[-300:])
            p = subprocess.run([sys.executable, helper, "eintragen", "qwen3:14b"], capture_output=True, text=True, env=env, timeout=120)
            after = yaml.safe_load(open(cfg_path, encoding="utf-8"))
            check(p.returncode == 0 and after["model"]["default"] == "qwen3:14b" and after["model"]["provider"] == "custom",
                  "hermes-os-lokal eintragen schreibt den model-Block", (p.stdout + p.stderr)[-300:])
            p = subprocess.run([sys.executable, helper, "status"], capture_output=True, text=True, env=env, timeout=60)
            # GPU-Zeile je nach Rechner („GPU: keine nutzbare, … CPU“ in der CI, die Karte in VM 112)
            check(p.returncode == 0 and "qwen3:14b" in p.stdout and p.stdout.startswith("GPU: ")
                  and "Ollama: nicht installiert" in p.stdout, "hermes-os-lokal status als Text", (p.stdout + p.stderr)[-300:])
            p = subprocess.run([sys.executable, helper, "--check"], capture_output=True, text=True, env=env, timeout=60)
            check(p.returncode == 0 or "zstd fehlt" in p.stdout or "tar fehlt" in p.stdout,
                  "hermes-os-lokal --check", (p.stdout + p.stderr)[-300:])
            if env.get("HERMES_OS_OLLAMA_SHA256"):
                p = subprocess.run([sys.executable, helper, "--json", "installieren"], capture_output=True, text=True,
                                   env=env, timeout=120)
                rows = [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
                check(p.returncode == 0 and any(r.get("progress") for r in rows)
                      and rows[-1].get("step") == "installed" and rows[-1].get("ok") is True
                      and os.access(lm.OLLAMA_BIN, os.X_OK),
                      "hermes-os-lokal --json installieren: Fortschritt, dann installed", (p.stdout + p.stderr)[-300:])
                p = subprocess.run([sys.executable, helper, "--json", "status"], capture_output=True, text=True, env=env, timeout=60)
                js = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
                check(js.get("ollama_installed") is True and js.get("ollama", {}).get("version") == lm.OLLAMA_PIN,
                      "hermes-os-lokal --json status meldet Ollama mit Version", str(js.get("ollama")))
                p = subprocess.run([sys.executable, helper, "entfernen"], capture_output=True, text=True, env=env, timeout=60)
                log = open(os.path.join(tmp, "systemctl.log"), encoding="utf-8").read() if os.path.isfile(
                    os.path.join(tmp, "systemctl.log")) else ""
                check(p.returncode == 0 and not os.path.exists(lm.OLLAMA_DIR) and "gelöscht" in p.stdout
                      and "disable --now ollama.service" in log,
                      "hermes-os-lokal entfernen: Dienst aus, Programm weg", (p.stdout + p.stderr)[-300:])
        else:
            print("WARN  hermes-os-lokal nicht gefunden, Helfer-Prüfung übersprungen")
    finally:
        server.shutdown()
    print("lokales-modell-check: " + ("alles sauber" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
