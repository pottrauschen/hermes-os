#!/usr/bin/env python3
"""hermes-os -- Brücke zwischen dem Einrichtungsassistenten und Hermes.

Läuft mit dem Python der Hermes-Venv (/usr/lib/hermes-agent/.venv), nicht mit
dem Fedora-Python des Assistenten, und spricht nur JSON auf stdout. So bleibt
die Oberfläche frei von Hermes-Importen, und die eigenen Helfer von Hermes
erledigen das Schreiben von .env und config.yaml genau wie `hermes setup`.

Befehle:
  catalog                 Provider-Liste (Hermes-Katalog, gefiltert)
  models <slug>           Modelle des Providers abrufen, Schlüssel prüfen
  save <slug> <modell>    Schlüssel nach .env, Provider und Modell nach config.yaml
  check                   Trockenlauf für das Validierungs-Gate

Der Schlüssel kommt nie über die Kommandozeile (ps würde ihn zeigen), sondern
über die Umgebungsvariable HERMES_OS_SETUP_KEY.
"""
import json
import os
import sys
import urllib.error
import urllib.request

# Provider, die zwar API-Schlüssel nutzen, für den ersten Login aber nicht
# taugen: lokale Server, Cloud-SDK-Auth, Sammelrouten ohne eigenen Schlüssel.
_SKIP = {"custom", "moa", "vertex", "bedrock", "lmstudio", "copilot", "actual"}

# Abo-Anbieter: Anmeldung statt Schlüssel. Der Login läuft im Terminal über
# Hermes' eigene Flows; der Assistent startet nur den passenden Befehl
# (Argumente hinter `hermes`). Nous richtet danach Modell und Anbieter selbst
# ein, die anderen tun das in der Modellwahl von `hermes model`.
_OAUTH = {
    "nous": (["portal"],
             "Nous Portal braucht keinen Schlüssel, sondern eine Anmeldung bei Nous Research. "
             "Hermes zeigt im Terminal eine Adresse und einen Code; die Adresse kannst du auch am Handy "
             "öffnen. Danach wählt Hermes Modell und Anbieter selbst."),
    "openai-codex": (["model"],
                     "ChatGPT- oder Codex-Abo: Anmeldung mit dem ChatGPT-Konto im Terminal, "
                     "danach dort das Modell wählen."),
    "xai-oauth": (["model"],
                  "SuperGrok oder X Premium+: Anmeldung im Terminal, danach dort das Modell wählen."),
    "minimax-oauth": (["model"],
                      "MiniMax-Konto: Anmeldung im Terminal, danach dort das Modell wählen."),
}
_LABELS = {"nous": "Nous Portal", "openai-codex": "ChatGPT / Codex (Abo)",
           "xai-oauth": "xAI Grok (Abo)", "minimax-oauth": "MiniMax (Abo)"}

# Anthropic nur mit API-Schlüssel. Hermes böte auch den Setup-Token aus Claude
# Code an (Claude Pro/Max); Anthropics Bedingungen erlauben das Abo aber nur
# in den eigenen Programmen, nicht in einem fremden Agenten. Siehe
# docs/einrichtung.md, Abschnitt Abo.
_ANTHROPIC_HINT = ("Claude Pro/Max lässt sich hier nicht verwenden, Anthropic erlaubt das Abo nur in "
                   "Claude Code und den Claude-Apps. Der Schlüssel kommt aus dem Konto, Abrechnung nach Verbrauch.")

# Reihenfolge der Liste: die verbreiteten zuerst, der Rest alphabetisch.
_PREFERRED = ["openrouter", "anthropic", "openai-codex", "openai-api", "nous", "gemini",
              "deepseek", "xai", "xai-oauth", "minimax", "minimax-oauth", "zai"]


def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _fail(message, code="error"):
    _out({"ok": False, "error": message, "code": code})
    sys.exit(1)


def _base_url(slug):
    """Basis-URL wie im Wizard: OpenRouter fest, sonst Registry, sonst models.dev."""
    if slug == "openrouter":
        from hermes_constants import OPENROUTER_BASE_URL
        return OPENROUTER_BASE_URL
    try:
        from hermes_cli.auth import PROVIDER_REGISTRY
        pconfig = PROVIDER_REGISTRY.get(slug)
        if pconfig is not None and getattr(pconfig, "inference_base_url", ""):
            return pconfig.inference_base_url
    except Exception:
        pass
    try:
        from hermes_cli.providers import get_provider
        p = get_provider(slug, allow_network=True)
        if p is not None and p.base_url:
            return p.base_url
    except Exception:
        pass
    return ""


def cmd_catalog():
    from hermes_cli.provider_catalog import provider_catalog
    rows = []
    for p in provider_catalog():
        if p.slug in _SKIP:
            continue
        if p.slug in _OAUTH:
            login, hint = _OAUTH[p.slug]
            rows.append({"slug": p.slug, "label": _LABELS.get(p.slug, p.label), "auth": "oauth",
                         "env": "", "signup": p.signup_url, "hint": hint, "login": login})
            continue
        if p.auth_type != "api_key" or not p.api_key_env_vars:
            continue
        signup = p.signup_url
        if p.slug == "anthropic" and not signup:
            signup = "https://platform.claude.com/settings/keys"  # wie im Hermes-Wizard
        rows.append({"slug": p.slug, "label": p.label, "auth": "api_key",
                     "env": p.api_key_env_vars[0], "signup": signup,
                     "hint": _ANTHROPIC_HINT if p.slug == "anthropic" else "",
                     "login": []})

    def order(row):
        try:
            return (0, _PREFERRED.index(row["slug"]), "")
        except ValueError:
            return (1, 0, row["label"].lower())
    rows.sort(key=order)
    _out({"ok": True, "providers": rows})


def _key_check(slug, key):
    """Bestätigt den Schlüssel, wo der Anbieter das erlaubt: ok, rejected oder
    unknown. OpenRouter beantwortet /models auch ohne Schlüssel, deshalb dort
    /key. Andere Anbieter verlangen bei /models Auth, dort zählt die Liste."""
    if slug == "openrouter":
        req = urllib.request.Request("https://openrouter.ai/api/v1/key",
                                     headers={"Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return "ok" if r.status == 200 else "unknown"
        except urllib.error.HTTPError as e:
            return "rejected" if e.code in (401, 403) else "unknown"
        except Exception:
            return "unknown"
    return None


def cmd_models(slug):
    key = os.environ.get("HERMES_OS_SETUP_KEY", "")
    if not key:
        _fail("kein Schlüssel übergeben", "no_key")
    base_url = _base_url(slug)
    if not base_url:
        _fail(f"keine Basis-URL für {slug} bekannt", "no_base_url")
    if slug == "anthropic" and key.startswith("sk-ant-oat"):
        # Setup-Token aus Claude Code: kein Weg für Hermes, siehe _ANTHROPIC_HINT.
        _fail("Das ist ein Abo-Token aus Claude Code. Anthropic erlaubt das Abo nur in den eigenen "
              "Programmen; für Hermes bitte einen API-Schlüssel aus dem Konto verwenden.", "subscription_token")
    from hermes_cli.models import probe_api_models
    from hermes_cli.providers import determine_api_mode
    mode = determine_api_mode(slug, base_url)
    result = probe_api_models(key, base_url, timeout=15, api_mode=mode)
    models = result.get("models") or []
    check = _key_check(slug, key)
    if check is None:
        check = "ok" if models else "rejected"
    default = ""
    try:
        from hermes_cli.models import pick_silent_default_model
        default = pick_silent_default_model(models, slug) if models else ""
    except Exception:
        default = models[0] if models else ""
    _out({"ok": True, "key_check": check, "base_url": base_url,
          "models": models, "default": default,
          "probed_url": result.get("probed_url", "")})


def cmd_save(slug, model):
    key = os.environ.get("HERMES_OS_SETUP_KEY", "")
    if not key:
        _fail("kein Schlüssel übergeben", "no_key")
    if not model:
        _fail("kein Modell gewählt", "no_model")
    from hermes_cli.provider_catalog import provider_catalog_by_slug
    from hermes_cli.config import save_env_value, get_config_path, get_env_path
    from hermes_cli.model_setup_flows_common import _persist_model
    desc = provider_catalog_by_slug().get(slug)
    if desc is None or not desc.api_key_env_vars:
        _fail(f"Provider {slug} unbekannt oder ohne Schlüssel-Variable", "bad_provider")
    base_url = _base_url(slug)
    env_var = desc.api_key_env_vars[0]
    if slug == "anthropic":
        if key.startswith("sk-ant-oat"):
            _fail("Abo-Token aus Claude Code, für Hermes nicht zulässig; bitte API-Schlüssel", "subscription_token")
        # Wie der Wizard: schreibt ANTHROPIC_API_KEY und leert den Token-Slot
        # ANTHROPIC_TOKEN, damit kein alter Abo-Token daneben liegen bleibt.
        from hermes_cli.config import save_anthropic_api_key
        save_anthropic_api_key(key, save_fn=save_env_value)
        env_var = "ANTHROPIC_API_KEY"
    else:
        save_env_value(env_var, key)
    # Wie _finish_model im Wizard: OpenRouter pinnt chat_completions, alle
    # anderen lassen api_mode weg, damit die Laufzeit selbst erkennt.
    if slug == "openrouter":
        _persist_model(model, slug, base_url=base_url, api_mode="chat_completions")
    else:
        _persist_model(model, slug, base_url=base_url or None, drop_api_mode=True)
    _out({"ok": True, "env": str(get_env_path()), "config": str(get_config_path()),
          "provider": slug, "model": model, "env_var": env_var})


def cmd_check():
    """Trockenlauf: alle Importe und der Katalog, ohne Netz und ohne Schreiben."""
    from hermes_cli.provider_catalog import provider_catalog
    from hermes_cli.config import save_env_value, save_anthropic_api_key  # noqa: F401
    from hermes_cli.model_setup_flows_common import _persist_model  # noqa: F401
    from hermes_cli.models import probe_api_models, pick_silent_default_model  # noqa: F401
    n = len([p for p in provider_catalog() if p.auth_type == "api_key"])
    if n < 5:
        _fail(f"Katalog liefert nur {n} Schlüssel-Provider", "catalog")
    _out({"ok": True, "api_key_providers": n, "openrouter_base_url": _base_url("openrouter")})


def main(argv):
    if len(argv) < 2:
        _fail("Befehl fehlt: catalog | models <slug> | save <slug> <modell> | check", "usage")
    cmd = argv[1]
    try:
        if cmd == "catalog":
            cmd_catalog()
        elif cmd == "models" and len(argv) >= 3:
            cmd_models(argv[2])
        elif cmd == "save" and len(argv) >= 4:
            cmd_save(argv[2], argv[3])
        elif cmd == "check":
            cmd_check()
        else:
            _fail("unbekannter Befehl oder Argument fehlt", "usage")
    except SystemExit:
        raise
    except Exception as e:  # Fehler immer als JSON, nie als Traceback in der GUI
        _fail(f"{type(e).__name__}: {e}", "exception")


if __name__ == "__main__":
    main(sys.argv)
