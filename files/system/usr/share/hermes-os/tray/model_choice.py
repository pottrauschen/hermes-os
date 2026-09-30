"""hermes-os -- Modell und Denkaufwand im Kontor und im Menü am Symbol.

Liest und schreibt zwei Werte in ~/.hermes/config.yaml: model.default (welches
Modell des eingestellten Anbieters) und agent.reasoning_effort (Denkaufwand,
Hermes gibt ihn an den Anbieter weiter). Das Gateway liest die Datei bei jedem
Gesprächsschritt neu; die Wahl gilt ab der nächsten Nachricht.

Eine Modell-Liste gibt es nur für Endpunkte auf diesem Rechner (Anbieter
custom unter 127.0.0.1 oder localhost, etwa das lokale Modell): deren
/models ist kurz und nennt, was wirklich bedient wird. Cloud-Anbieter haben
Listen mit Hunderten Einträgen; dort zeigt das Fenster nur das aktuelle
Modell, gewechselt wird über den Einrichtungsassistenten. Den Denkaufwand gibt
es für jeden Anbieter.

Schreiben über local_model.py (dieselben Helfer wie beim lokalen Modell):
nur der betroffene Block der obersten Ebene wird ersetzt, Kommentare bleiben,
atomar, 0600. Nur Standardbibliothek und PyYAML; Tests:
tests/model-choice-check.py.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional

LOCAL_PY = os.environ.get("HERMES_OS_LOCAL_PY", "/usr/share/hermes-os/local/local_model.py")


def _load_lang():
    """_() aus tray/lang.py (Sprache der Oberfläche). Das Leisten-Symbol legt tray/
    auf sys.path; tests/model-choice-check.py lädt dieses Modul über den Pfad, dann
    lang.py daneben. Ohne lang.py bleibt es deutsch."""
    try:
        from lang import _ as tr
        return tr
    except ImportError:
        pass
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang.py")
        spec = importlib.util.spec_from_file_location("hermes_os_tray_lang", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._
    except Exception:
        return lambda text: text


_ = _load_lang()

# Stufen, die Hermes an OpenAI-kompatible Anbieter weitergibt (agent/reasoning_effort.py:
# OPENAI_COMPAT_WIRE_EFFORTS). "" heißt: nichts eingetragen, der Anbieter entscheidet.
# Die Namen sind deutsch und Schlüssel für tray/lang.py; angezeigt über effort_label.
EFFORTS = [("", "Vorgabe"), ("low", "wenig"), ("medium", "mittel"), ("high", "gründlich"),
           ("xhigh", "sehr gründlich"), ("max", "maximal")]
EFFORT_LABEL = dict(EFFORTS)


def hermes_home() -> str:
    return os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")


def config_path() -> str:
    return os.path.join(hermes_home(), "config.yaml")


def local_model():
    spec = importlib.util.spec_from_file_location("hermes_os_local_model", LOCAL_PY)
    if spec is None or spec.loader is None:
        raise ImportError(f"{LOCAL_PY} nicht ladbar")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_choice(path: Optional[str] = None) -> Dict[str, str]:
    """Aktueller Stand aus config.yaml; leere Werte, wenn Datei oder Blöcke fehlen."""
    import yaml
    out = {"model": "", "provider": "", "base_url": "", "effort": ""}
    try:
        with open(path or config_path(), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return out
    if not isinstance(cfg, dict):
        return out
    block = cfg.get("model")
    if isinstance(block, str):
        block = {"default": block}
    if isinstance(block, dict):
        out["model"] = str(block.get("default") or "")
        out["provider"] = str(block.get("provider") or "")
        out["base_url"] = str(block.get("base_url") or "")
    agent = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    effort = str(agent.get("reasoning_effort") or "")
    out["effort"] = effort if effort in EFFORT_LABEL else ""
    return out


def is_local(choice: Dict[str, str]) -> bool:
    return choice.get("provider") == "custom" and re.match(
        r"^https?://(127\.0\.0\.1|localhost)(:|/)", choice.get("base_url") or "") is not None


def fetch_models(base_url: str, timeout: float = 3.0) -> List[Dict[str, str]]:
    """/models eines Endpunkts auf diesem Rechner: [{"id", "label"}]. Ein Endpunkt
    darf je Modell einen kurzen Namen mitgeben ("label" oder "name"), sonst gilt die ID."""
    req = urllib.request.Request(base_url.rstrip("/") + "/models",
                                 headers={"Authorization": "Bearer no-key-required"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read() or b"{}")
    out = []
    for m in data.get("data") or []:
        mid = str(m.get("id") or "").strip()
        if mid:
            out.append({"id": mid, "label": str(m.get("label") or m.get("name") or mid)})
    return out


def effort_label(effort: str) -> str:
    """Name einer Stufe in der Sprache der Sitzung; eine unbekannte heißt Vorgabe."""
    return _(EFFORT_LABEL.get(effort, "Vorgabe"))


def model_label(model: str, options: List[Dict[str, str]]) -> str:
    for o in options:
        if o["id"] == model:
            return o["label"]
    return model.rsplit("/", 1)[-1] if model else _("kein Modell")


def button_text(choice: Dict[str, str], options: List[Dict[str, str]]) -> str:
    return f"{model_label(choice['model'], options)} · {effort_label(choice['effort'])}"


def write_model(model: str, lm=None, path: Optional[str] = None) -> None:
    """Nur model.default ändern; Anbieter, Adresse und alles andere bleiben."""
    lm = lm or local_model()
    path = path or config_path()
    cfg = lm._load_config(path)
    block = cfg.get("model")
    if not isinstance(block, dict):
        block = {"default": block} if isinstance(block, str) and block else {}
    block["default"] = model
    cfg["model"] = block
    lm._save_config(path, cfg, keys=["model"])


def write_effort(effort: str, lm=None, path: Optional[str] = None) -> None:
    """agent.reasoning_effort setzen; "" entfernt den Eintrag (Vorgabe des Anbieters)."""
    if effort not in EFFORT_LABEL:
        raise ValueError(_("unbekannter Denkaufwand: {effort}").format(effort=effort))
    lm = lm or local_model()
    path = path or config_path()
    cfg = lm._load_config(path)
    agent = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    if effort:
        agent["reasoning_effort"] = effort
    else:
        agent.pop("reasoning_effort", None)
    if agent:
        cfg["agent"] = agent
    else:
        cfg.pop("agent", None)
    lm._save_config(path, cfg, keys=["agent"])
