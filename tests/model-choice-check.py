#!/usr/bin/python3
# =============================================================================
# hermes-os -- Modell und Denkaufwand (tray/model_choice.py) ohne Qt prüfen
# =============================================================================
# Liest und schreibt eine config.yaml mit Kommentaren wie die Vorlage, fragt
# einen nachgebauten Endpunkt nach /models und prüft die Beschriftung des
# Knopfs. Braucht local_model.py (Helfer für config.yaml) und PyYAML.
#
# Aufruf:
#   tests/model-choice-check.py [--tray-dir DIR] [--local-dir DIR]
# Exit 0 = alles sauber.
# =============================================================================
import argparse
import importlib.util
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Die Prüfungen vergleichen deutsche Texte: die Sprache der Oberfläche festhalten,
# auch wenn die Sitzung englisch ist (tray/lang.py, docs/systemagent.md)
os.environ["HERMES_OS_LANG"] = "de"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAILS = []

CONFIG = """# hermes-os: Vorlage
# ---- Modell ----
model:
  default: claude-sonnet-5
  provider: custom
  base_url: http://127.0.0.1:{port}/v1
  api_mode: chat_completions
  context_length: 200000

# ---- Anzeige ----
display:
  interface: cli
"""


def check(name, cond, detail=""):
    print(("OK    " if cond else "FEHL  ") + name + ("" if cond or not detail else f": {detail}"))
    if not cond:
        FAILS.append(name)


class Models(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [
            {"id": "claude-sonnet-5", "object": "model", "label": "Sonnet 5"},
            {"id": "claude-opus-5-5", "object": "model", "label": "Opus 5.5"},
            {"id": "qwen3.5:9b", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tray-dir", default=os.path.join(REPO, "files", "system", "usr", "share", "hermes-os", "tray"))
    ap.add_argument("--local-dir", default=os.path.join(REPO, "files", "system", "usr", "share", "hermes-os", "local"))
    a = ap.parse_args()
    home = tempfile.mkdtemp(prefix="model-choice-")
    os.environ["HERMES_HOME"] = home
    os.environ["HERMES_OS_LOCAL_PY"] = os.path.join(a.local_dir, "local_model.py")
    spec = importlib.util.spec_from_file_location("model_choice", os.path.join(a.tray_dir, "model_choice.py"))
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Models)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    path = os.path.join(home, "config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(CONFIG.format(port=port))

    c = mc.read_choice()
    check("read_choice: Modell, Anbieter, Adresse, kein Denkaufwand",
          c == {"model": "claude-sonnet-5", "provider": "custom", "base_url": f"http://127.0.0.1:{port}/v1", "effort": ""},
          str(c))
    check("is_local: custom unter 127.0.0.1 ja, Cloud nein",
          mc.is_local(c) and not mc.is_local({"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"})
          and not mc.is_local({"provider": "custom", "base_url": "https://example.org/v1"}))
    options = mc.fetch_models(c["base_url"])
    check("fetch_models: IDs mit kurzem Namen, sonst die ID",
          options == [{"id": "claude-sonnet-5", "label": "Sonnet 5"}, {"id": "claude-opus-5-5", "label": "Opus 5.5"},
                      {"id": "qwen3.5:9b", "label": "qwen3.5:9b"}], str(options))
    check("button_text: kurzer Name und Denkaufwand", mc.button_text(c, options) == "Sonnet 5 · Vorgabe"
          and mc.button_text(dict(c, model="openai/gpt-5.6"), []) == "gpt-5.6 · Vorgabe", mc.button_text(c, options))

    mc.write_model("claude-opus-5-5")
    mc.write_effort("high")
    c2 = mc.read_choice()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    check("write_model und write_effort: Stand stimmt, Anbieter und Adresse bleiben",
          c2 == dict(c, model="claude-opus-5-5", effort="high"), str(c2))
    check("config.yaml behält ihre Kommentare", "# ---- Anzeige ----" in text and "# hermes-os: Vorlage" in text, text)
    mc.write_effort("")
    c3 = mc.read_choice()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    check("Vorgabe entfernt den Eintrag (und den leeren agent-Block)", c3["effort"] == "" and "agent:" not in text, text)
    try:
        mc.write_effort("turbo")
        check("unbekannte Stufe abgelehnt", False)
    except ValueError:
        check("unbekannte Stufe abgelehnt", True)
    check("fehlende config.yaml liefert leere Werte",
          mc.read_choice(os.path.join(home, "gibt-es-nicht.yaml")) == {"model": "", "provider": "", "base_url": "", "effort": ""})
    srv.shutdown()
    print()
    print("ERGEBNIS: " + ("ok" if not FAILS else "Fehler, siehe FEHL"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
