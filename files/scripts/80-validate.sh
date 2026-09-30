#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Validierungs-Gate (bricht den Build hart ab)
# =============================================================================
# Prüft, dass die Agent-Schicht wirklich lauffähig ist, nicht nur vorhanden.
# Muster aus querencia-linux 88-validate-repos.sh: reines Gate, ändert nichts.
# =============================================================================
set -euo pipefail

FAIL=0
fail() { echo "  FAIL: $*"; FAIL=1; }
pass() { echo "  PASS: $*"; }

export HERMES_HOME=/tmp/hermes-validate
mkdir -p "${HERMES_HOME}"

echo "=== hermes-os validation gate ==="

# 1. Launcher und Venv
if [ -x /usr/bin/hermes ] && [ -x /usr/lib/hermes-agent/.venv/bin/hermes ]; then
  pass "launcher and venv present"
else
  fail "launcher or venv missing"
fi

# 2. Interpreter ist der gepinnte (uv-verwaltet, nicht Fedora-Python)
WANT="$(sed -n 's/^python=//p' /usr/lib/hermes-agent/.hermes-os-release 2>/dev/null || true)"
PYV="$(/usr/lib/hermes-agent/.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ -n "${WANT}" ] && [ "${PYV}" = "${WANT}" ]; then pass "venv python ${PYV}"; else fail "venv python is ${PYV}, expected ${WANT:-?}"; fi
case "$(readlink -f /usr/lib/hermes-agent/.venv/bin/python)" in
  /usr/lib/hermes-agent/python/*) pass "interpreter is uv-managed" ;;
  *) fail "interpreter is not under /usr/lib/hermes-agent/python" ;;
esac

# 3. Hermes startet und meldet das gepinnte Release
if VER="$(/usr/bin/hermes --version 2>&1)"; then
  pass "hermes --version: ${VER}"
else
  fail "hermes --version failed: ${VER}"
fi

# 4. Kern-Module importierbar (Gateway, Plugins, Checkpoints)
if /usr/lib/hermes-agent/.venv/bin/python -c 'import hermes_cli.main, hermes_cli.plugins, tools.checkpoint_manager' 2>/dev/null; then
  pass "core modules import"
else
  fail "core module import failed"
fi

# 4b. Sprachpakete sind fest eingebaut (read-only Venv kann nicht nachladen)
if /usr/lib/hermes-agent/.venv/bin/python -c 'import faster_whisper, piper' 2>/dev/null; then
  pass "voice packages baked in (faster_whisper, piper)"
else
  fail "faster_whisper or piper not importable from the venv"
fi

# 4c. Launcher und environment.d setzen das Lazy-Install-Ziel ins Home
if grep -q 'HERMES_LAZY_INSTALL_TARGET' /usr/bin/hermes \
   && grep -q '^HERMES_LAZY_INSTALL_TARGET=' /usr/lib/environment.d/60-hermes-os.conf; then
  pass "HERMES_LAZY_INSTALL_TARGET set in launcher and environment.d"
else
  fail "HERMES_LAZY_INSTALL_TARGET missing in launcher or environment.d"
fi
if grep -q 'HERMES_WEB_DIST' /usr/bin/hermes \
   && grep -q '^HERMES_WEB_DIST=/usr/lib/hermes-agent/hermes_cli/web_dist$' /usr/lib/environment.d/60-hermes-os.conf; then
  pass "HERMES_WEB_DIST set in launcher and environment.d"
else
  fail "HERMES_WEB_DIST missing in launcher or environment.d"
fi

# 4d. Ein Installer für Nachinstallationen ist im Image (uv-Venv hat kein pip)
if /usr/bin/uv --version >/dev/null 2>&1; then
  pass "uv available at runtime: $(/usr/bin/uv --version)"
else
  fail "/usr/bin/uv missing; lazy installs would fail"
fi

# 5. Install-Stempel: paketverwaltet, hermes update verweigert
if [ "$(cat /usr/lib/hermes-agent/.install_method 2>/dev/null)" = "apt" ] \
   && grep -q '^update=image' /usr/lib/hermes-agent/.hermes-os-release 2>/dev/null; then
  pass "install method stamp: apt (image-managed)"
else
  fail "install method stamp missing"
fi
# Hermes 0.21.x beendet einen verweigerten Update-Versuch mit Exit-Code 2
# (refused-by-contract) und druckt nur den Paketmanager-Befehl.
set +e
/usr/bin/hermes update >/dev/null 2>&1
UPDATE_RC=$?
set -e
if [ "${UPDATE_RC}" -eq 2 ]; then
  pass "hermes update refuses on image-managed install (exit 2)"
else
  fail "hermes update exited ${UPDATE_RC}, expected 2 (refusal)"
fi

# 6. Das hermes-os-Plugin lädt über den echten Plugin-Loader (wie nach dem
#    First-Login: Symlink unter ~/.hermes/plugins, Config-Vorlage, enable)
PLUGIN=/usr/share/hermes-os/plugins/hermes_os
if [ -f "${PLUGIN}/plugin.yaml" ] && [ -f "${PLUGIN}/__init__.py" ]; then
  mkdir -p "${HERMES_HOME}/plugins"
  ln -sfn "${PLUGIN}" "${HERMES_HOME}/plugins/hermes_os"
  cp /usr/share/hermes-os/config.yaml.default "${HERMES_HOME}/config.yaml"
  if /usr/bin/hermes plugins enable hermes-os >/dev/null 2>&1 \
     && (cd /usr/lib/hermes-agent && XDG_STATE_HOME="${HERMES_HOME}/state" /usr/lib/hermes-agent/.venv/bin/python - <<'PY'
import json, os
import hermes_cli.plugins as hp
from tools.registry import registry
hp.discover_plugins(force=True)
names = sorted(n for n in registry.get_all_tool_names() if n.startswith(("os_", "app_launch", "library_", "desktop_notify")))
assert len(names) == 15, names
assert registry.get_toolset_for_tool("os_status") == "hermes_os"
assert registry.get_toolset_for_tool("os_locale") == "hermes_os"
assert registry.get_toolset_for_tool("os_report") == "hermes_os"
pm = hp._ensure_plugins_discovered()
sections = getattr(pm, "_system_prompt_sections", None) or getattr(pm, "system_prompt_sections", {})
assert "hermes-os.system" in sections, list(sections)
assert "hermes-os.library" in sections, list(sections)
# Freigabe-Hook: System-Befehle landen im Dialog, freie Befehle nicht
d = hp._get_pre_tool_call_directive_details("terminal", {"command": "sudo bootc switch ghcr.io/x/y:latest"})
assert d.action == "approve", d
d = hp._get_pre_tool_call_directive_details("terminal", {"command": "systemctl --user restart hermes-gateway"})
assert d.action is None, d
d = hp._get_pre_tool_call_directive_details("terminal", {"command": "sudo localectl set-x11-keymap de"})
assert d.action == "approve", d
d = hp._get_pre_tool_call_directive_details("terminal", {"command": "kwriteconfig6 --notify --file kxkbrc --group Layout --key LayoutList de"})
assert d.action is None, d
# Die ganze Angriffsbatterie durch den echten Dispatch (block und approve)
import importlib.util, os
if os.path.exists("/ctx/tests/boundary-check.py"):
    spec = importlib.util.spec_from_file_location("boundary_check", "/ctx/tests/boundary-check.py")
    bc = importlib.util.module_from_spec(spec); spec.loader.exec_module(bc)
    for cmd, group in bc.CASES:
        d = hp._get_pre_tool_call_directive_details("terminal", {"command": cmd})
        assert d.action == bc.expected_action(group), (cmd, d)
    print("boundary cases through the release dispatch:", len(bc.CASES))
# Protokoll (audit.py): Hooks hängen, ein erkannter Befehl landet mit Ergebnis in der Datei
for h in ("pre_approval_request", "post_approval_response", "post_tool_call"):
    assert hp.has_hook(h), h
from hermes_cli.lifecycle import invoke_hook
invoke_hook("post_tool_call", tool_name="terminal", args={"command": "sudo systemctl restart sshd"},
            result=json.dumps({"output": "", "exit_code": 0, "error": None}), task_id="", session_id="",
            tool_call_id="gate-1", turn_id="", api_request_id="", duration_ms=1, status="ok",
            error_type=None, error_message=None, middleware_trace=[])
path = os.path.join(os.environ["XDG_STATE_HOME"], "hermes-os", "audit.jsonl")
last = json.loads(open(path, encoding="utf-8").read().splitlines()[-1])
assert last["kind"] == "command.result" and last["group"] == "services" and last["exit_code"] == 0, last
assert oct(os.stat(path).st_mode & 0o777) == "0o600", oct(os.stat(path).st_mode)
print("tools:", ", ".join(names), "| approval hook active | audit log written")
PY
  ); then pass "plugin hermes_os loads through the release plugin loader"; else fail "plugin hermes_os failed to load"; fi
else
  fail "plugin hermes_os files missing"
fi

# 7. Skill, Config-Vorlage, Dienst, Autostart
for f in /usr/share/hermes-os/skills/hermes-os-system/SKILL.md \
         /usr/share/hermes-os/config.yaml.default \
         /usr/lib/systemd/user/hermes-gateway.service \
         /etc/xdg/autostart/hermes-os-first-login.desktop \
         /usr/libexec/hermes-os-first-login \
         /usr/libexec/hermes-os-setup \
         /usr/share/hermes-os/setup/Main.qml \
         /usr/share/hermes-os/setup/hermes_bridge.py \
         /usr/share/applications/hermes-os-setup.desktop \
         /usr/share/ublue-os/just/60-custom.just; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done

# 7b. ujust sieht unsere Rezepte wirklich. Aurora's /usr/bin/ujust ruft
#     just mit /usr/share/ublue-os/just/00-entry.just auf (aus dem
#     common-Image), und die importiert optional 60-custom.just. Deshalb
#     den echten Wrapper fragen, nicht /usr/share/ublue-os/justfile aus dem
#     RPM ublue-os-just, das Aurora gar nicht benutzt.
JUST_OUT="$(ujust --list 2>&1)" || true
# Here-String statt Pipe: unter pipefail koennte grep -q die Pipe vorzeitig
# schliessen und den Test faelschlich scheitern lassen.
if grep -qE '^\s*hermes-setup\b' <<< "${JUST_OUT}"; then
  pass "ujust lists hermes-setup"
else
  fail "ujust does not list hermes-setup (60-custom.just not imported?)"
  echo "  --- ujust --list output (head) ---"
  echo "${JUST_OUT}" | head -15 | sed 's/^/  /'
  echo "  --- /usr/bin/ujust ---"
  sed 's/^/  /' /usr/bin/ujust 2>/dev/null | head -5
  echo "  --- /usr/share/ublue-os/just/ ---"
  ls -la /usr/share/ublue-os/just/ 2>/dev/null | sed 's/^/  /'
fi

# 7a. Die Config-Vorlage sperrt das Übernehmen fremder Anmeldungen. Hermes
#     würde sonst eine Claude-Code-Anmeldung im Home von selbst benutzen,
#     was Anthropics Bedingungen verletzt (docs/einrichtung.md).
if /usr/lib/hermes-agent/.venv/bin/python - <<'PY'
import yaml
cfg = yaml.safe_load(open("/usr/share/hermes-os/config.yaml.default"))
assert cfg["auth"]["adopt_external_logins"] is False, cfg.get("auth")
PY
then pass "config template: auth.adopt_external_logins is false"; else fail "config template does not disable adopt_external_logins"; fi

# 7c. Einrichtungsassistent: PySide6 und Kirigami aus dem Basis-Image, die
#     Brücke in die Hermes-Venv, und jede QML-Seite rendert offscreen ohne
#     QML-Warnung. Das Render-Skript liegt im Repo unter tests/ und kommt über
#     den Build-Kontext (/ctx/tests), nicht ins Image.
if [ -x /usr/libexec/hermes-os-setup ] && [ -f /usr/share/hermes-os/setup/Main.qml ] \
   && [ -f /usr/share/applications/hermes-os-setup.desktop ]; then
  if /usr/libexec/hermes-os-setup --check; then
    pass "hermes-os-setup --check (PySide6, QML, bridge)"
  else
    fail "hermes-os-setup --check failed"
  fi
  if [ -f /ctx/tests/setup-gui-check.py ]; then
    mkdir -p /tmp/hermes-validate-xdg
    if HOME="${HERMES_HOME}" XDG_RUNTIME_DIR=/tmp/hermes-validate-xdg \
       /usr/bin/python3 /ctx/tests/setup-gui-check.py --qml-dir /usr/share/hermes-os/setup; then
      pass "setup assistant renders every page offscreen"
    else
      fail "setup assistant offscreen render failed (see above)"
    fi
    rm -rf /tmp/hermes-validate-xdg
  else
    echo "  WARN: /ctx/tests/setup-gui-check.py not in build context, render check skipped"
  fi
else
  fail "setup assistant files missing (hermes-os-setup, Main.qml, .desktop)"
fi

# 7d. Leisten-Symbol: Startprogramm, QML, Client, Icons, Desktop-Dateien
#     (Menü, Autostart, Kurzbefehl Meta+H über kglobalaccel). --check prüft
#     PySide6 und den Client, der Client-Test spielt einen ganzen Chat samt
#     Freigabe gegen ein nachgebautes Gateway durch, der Render-Test die
#     Zustände des Fensters offscreen, der Sprach-Test die englische Fassung der
#     Oberfläche (Deutsch bleibt Vorgabe, docs/systemagent.md). Die Tests kommen
#     aus /ctx/tests.
for f in /usr/libexec/hermes-os-tray \
         /usr/share/hermes-os/tray/Main.qml \
         /usr/share/hermes-os/tray/hermes_client.py \
         /usr/share/hermes-os/tray/lang.py \
         /usr/share/hermes-os/plugins/hermes_os/lang.py \
         /usr/share/hermes-os/tray/chat_text.py \
         /usr/share/applications/hermes-os-tray.desktop \
         /usr/share/kglobalaccel/hermes-os-tray.desktop \
         /etc/xdg/autostart/hermes-os-tray.desktop \
         /usr/share/icons/hicolor/scalable/apps/hermes-os.svg \
         /usr/share/icons/hicolor/scalable/status/hermes-os-tray-ready.svg \
         /usr/share/icons/hicolor/scalable/status/hermes-os-tray-busy.svg \
         /usr/share/icons/hicolor/scalable/status/hermes-os-tray-asking.svg \
         /usr/share/icons/hicolor/scalable/status/hermes-os-tray-off.svg; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done
if [ -x /usr/libexec/hermes-os-tray ]; then
  if /usr/libexec/hermes-os-tray --check; then
    pass "hermes-os-tray --check (PySide6, QML, client)"
  else
    fail "hermes-os-tray --check failed"
  fi
fi
if diff -q /usr/share/applications/hermes-os-tray.desktop /usr/share/kglobalaccel/hermes-os-tray.desktop >/dev/null 2>&1 \
   && grep -q '^X-KDE-Shortcuts=' /usr/share/kglobalaccel/hermes-os-tray.desktop; then
  pass "tray desktop file and its kglobalaccel copy are identical and carry a shortcut"
else
  fail "tray desktop file and kglobalaccel copy differ or lack X-KDE-Shortcuts"
fi
if command -v desktop-file-validate >/dev/null 2>&1; then
  for d in /usr/share/applications/hermes-os-tray.desktop /usr/share/applications/hermes-os-setup.desktop \
           /etc/xdg/autostart/hermes-os-tray.desktop /etc/xdg/autostart/hermes-os-first-login.desktop; do
    if desktop-file-validate "$d"; then pass "desktop-file-validate $d"; else fail "desktop-file-validate $d"; fi
  done
fi
if [ -f /ctx/tests/tray-client-check.py ]; then
  if /usr/bin/python3 /ctx/tests/tray-client-check.py --tray-dir /usr/share/hermes-os/tray; then
    pass "tray client completes a chat with approval against a fake gateway"
  else
    fail "tray client check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/tray-client-check.py not in build context, client check skipped"
fi
if [ -f /ctx/tests/model-choice-check.py ]; then
  if /usr/bin/python3 /ctx/tests/model-choice-check.py --tray-dir /usr/share/hermes-os/tray \
       --local-dir /usr/share/hermes-os/local; then
    pass "model and reasoning choice reads and writes config.yaml, lists local endpoint models"
  else
    fail "model choice check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/model-choice-check.py not in build context, model choice check skipped"
fi
if [ -f /ctx/tests/tray-gui-check.py ]; then
  mkdir -p /tmp/hermes-validate-xdg
  if HOME="${HERMES_HOME}" XDG_RUNTIME_DIR=/tmp/hermes-validate-xdg \
     /usr/bin/python3 /ctx/tests/tray-gui-check.py --qml-dir /usr/share/hermes-os/tray; then
    pass "tray window renders every state offscreen"
  else
    fail "tray window offscreen render failed (see above)"
  fi
  rm -rf /tmp/hermes-validate-xdg
else
  echo "  WARN: /ctx/tests/tray-gui-check.py not in build context, render check skipped"
fi
# Sprache der Oberfläche: beide lang.py entscheiden gleich, jeder Text aus Main.qml
# und den Modulen hat eine englische Fassung, der Übersetzer greift an der echten
# Main.qml und ohne ihn bleibt alles deutsch.
if [ -f /ctx/tests/lang-check.py ]; then
  mkdir -p /tmp/hermes-validate-xdg
  if HOME="${HERMES_HOME}" XDG_RUNTIME_DIR=/tmp/hermes-validate-xdg \
     /usr/bin/python3 /ctx/tests/lang-check.py --tray-dir /usr/share/hermes-os/tray \
       --plugin-dir /usr/share/hermes-os/plugins/hermes_os --tests-dir /ctx/tests \
       --tray-bin /usr/libexec/hermes-os-tray; then
    pass "ui language: german by default, english dictionary covers every visible text, translator works on Main.qml"
  else
    fail "ui language check failed (see above)"
  fi
  rm -rf /tmp/hermes-validate-xdg
else
  echo "  WARN: /ctx/tests/lang-check.py not in build context, language check skipped"
fi

# 7e. First-Login legt den Schlüssel für den API-Server an. Trockenlauf mit
#     dem Gate-HERMES_HOME: config.yaml liegt seit 6. (also kein erster Lauf,
#     kein Fenster), eine .env mit Anbieter-Schlüssel steht für eine fertige
#     Einrichtung; systemctl gibt es im Build-Container nicht, das Skript
#     meldet das nur als WARN im Log. Der zweite Lauf darf nichts mehr ändern.
printf 'OPENROUTER_API_KEY=sk-or-test\n' > "${HERMES_HOME}/.env"
if HOME="${HOME:-/root}" /usr/libexec/hermes-os-first-login \
   && grep -qE '^API_SERVER_KEY=[0-9a-f]{48}$' "${HERMES_HOME}/.env" \
   && grep -q '^API_SERVER_ENABLED=true$' "${HERMES_HOME}/.env" \
   && grep -q '^OPENROUTER_API_KEY=sk-or-test$' "${HERMES_HOME}/.env"; then
  pass "first-login adds API_SERVER_KEY to .env and keeps the provider key"
else
  fail "first-login did not add API_SERVER_KEY (log follows)"
  sed 's/^/  /' "${HERMES_HOME}/hermes-os-first-login.log" 2>/dev/null | tail -20
fi
KEYS_BEFORE="$(grep -c '^API_SERVER_KEY=' "${HERMES_HOME}/.env" || true)"
HOME="${HOME:-/root}" /usr/libexec/hermes-os-first-login || true
if [ "$(grep -c '^API_SERVER_KEY=' "${HERMES_HOME}/.env" || true)" = "${KEYS_BEFORE}" ] && [ "${KEYS_BEFORE}" = "1" ]; then
  pass "first-login is idempotent for API_SERVER_KEY"
else
  fail "first-login duplicated or lost API_SERVER_KEY on the second run"
fi
if [ "$(stat -c %a "${HERMES_HOME}/.env")" = "600" ]; then pass ".env is 0600"; else fail ".env mode is $(stat -c %a "${HERMES_HOME}/.env"), expected 600"; fi

# 7f. Deutsch ab Werk: Systemlocale und Tastatur wie von localectl geschrieben,
#     Plasma-Vorgaben über die XDG-Kaskade. Der Image-Builder kann Sprache und
#     Tastatur nicht setzen, nur der Anaconda-Installer fragt danach; ohne die
#     Vorgaben kommt jeder Datenträger mit us-Tastatur und Englisch hoch.
if grep -q '^LANG=de_DE.UTF-8$' /etc/locale.conf && grep -q '^KEYMAP=de$' /etc/vconsole.conf \
   && grep -q 'Option "XkbLayout" "de"' /etc/X11/xorg.conf.d/00-keyboard.conf \
   && grep -q '^LayoutList=de$' /etc/xdg/kxkbrc && grep -q '^Use=true$' /etc/xdg/kxkbrc \
   && grep -q '^LANG=de_DE.UTF-8$' /etc/xdg/plasma-localerc && grep -q '^LANGUAGE=de$' /etc/xdg/plasma-localerc; then
  pass "german defaults: locale.conf, vconsole.conf, 00-keyboard.conf, /etc/xdg/kxkbrc, /etc/xdg/plasma-localerc"
else
  fail "german defaults incomplete (locale.conf, vconsole.conf, 00-keyboard.conf, /etc/xdg/kxkbrc, /etc/xdg/plasma-localerc)"
fi
if [ "$(readlink /etc/localtime 2>/dev/null)" = "../usr/share/zoneinfo/Europe/Berlin" ] && [ -e /etc/localtime ]; then
  pass "time zone Europe/Berlin (/etc/localtime)"
else
  fail "/etc/localtime does not point at ../usr/share/zoneinfo/Europe/Berlin"
fi
if locale -a 2>/dev/null | grep -qiE '^de_DE(\.utf8)?$'; then
  pass "locale de_DE.UTF-8 available"
else
  fail "locale de_DE.UTF-8 not available (glibc-all-langpacks missing?)"
fi
if [ -f /usr/share/locale/de/LC_MESSAGES/kcm_keyboard.mo ] && [ -f /usr/share/locale/de/LC_MESSAGES/dolphin.mo ]; then
  pass "german Plasma translations present"
else
  fail "german Plasma translations missing under /usr/share/locale/de"
fi

# 7g. Bibliothek: Ablage, Zuordnung und Abrufer des Plugins (library.py) gegen
#     einen nachgebauten Webserver, mit der Venv-Python wie im Gateway.
if [ -f /ctx/tests/library-check.py ]; then
  if HOME="${HERMES_HOME}" /usr/lib/hermes-agent/.venv/bin/python /ctx/tests/library-check.py \
       --plugin-dir /usr/share/hermes-os/plugins/hermes_os; then
    pass "library: store, matching and fetcher work against a fake site"
  else
    fail "library check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/library-check.py not in build context, library check skipped"
fi
#     Stufe zwei: Spiegel, SQLite-Index mit FTS5 (die Venv-Python muss es
#     mitbringen; der Test meldet, ob es da ist, und prüft den LIKE-Rückfall
#     ebenfalls), Suche, MCP-Schalter gegen eine Wegwerf-config.yaml.
if [ -f /ctx/tests/library2-check.py ]; then
  if HOME="${HERMES_HOME}" /usr/lib/hermes-agent/.venv/bin/python /ctx/tests/library2-check.py \
       --plugin-dir /usr/share/hermes-os/plugins/hermes_os \
       --config-template /usr/share/hermes-os/config.yaml.default; then
    pass "library stage two: mirror, FTS5 index, search, MCP switches"
  else
    fail "library stage two check failed (see above)"
  fi
  if /usr/lib/hermes-agent/.venv/bin/python -c 'import sqlite3; sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(a)")' 2>/dev/null; then
    pass "venv sqlite has FTS5"
  else
    echo "  WARN: venv sqlite lacks FTS5, library_search falls back to LIKE"
  fi
  if /usr/bin/python3 -c 'import sqlite3; sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(a)")' 2>/dev/null; then
    pass "system python sqlite has FTS5 (tray search)"
  else
    echo "  WARN: system python sqlite lacks FTS5, tray search falls back to LIKE"
  fi
else
  echo "  WARN: /ctx/tests/library2-check.py not in build context, library stage two check skipped"
fi

# 7h. Grenze: Angriffsbatterie gegen den Klassifikator des Plugins (boundary.py),
#     mit der Venv-Python wie im Gateway; prüft auch fail-closed.
if [ -f /ctx/tests/boundary-check.py ]; then
  if /usr/lib/hermes-agent/.venv/bin/python /ctx/tests/boundary-check.py \
       --plugin-dir /usr/share/hermes-os/plugins/hermes_os; then
    pass "boundary: attack battery (ask, block, free, fail-closed)"
  else
    fail "boundary check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/boundary-check.py not in build context, boundary check skipped"
fi

# 7i. Protokoll: Ablage, Zusammenführen, Rotation, Filter und Export des Plugins
#     (audit.py), mit der Venv-Python wie im Gateway. Das Leisten-Symbol liest
#     dieselbe Datei; seine Seite prüft tray-gui-check.py in 7d.
if [ -f /ctx/tests/audit-check.py ]; then
  if HOME="${HERMES_HOME}" /usr/lib/hermes-agent/.venv/bin/python /ctx/tests/audit-check.py \
       --plugin-dir /usr/share/hermes-os/plugins/hermes_os; then
    pass "audit: write, read, rotation, filters and export work"
  else
    fail "audit check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/audit-check.py not in build context, audit check skipped"
fi

# 7j. Morgenbericht: os_report und desktop_notify mit nachgebauten Kommandos
#     (rpm-ostree, skopeo, journalctl, df, systemctl, flatpak), mit der
#     Venv-Python wie im Gateway; dazu der Einstieg des Cron-Jobs mit Fedoras
#     Python und die beiden ujust-Rezepte.
if [ -x /usr/libexec/hermes-os-morgenbericht ] && /usr/libexec/hermes-os-morgenbericht --check; then
  pass "hermes-os-morgenbericht --check (report.py and tools.py load with /usr/bin/python3)"
else
  fail "hermes-os-morgenbericht missing or --check failed"
fi
if [ -f /ctx/tests/report-check.py ]; then
  if HOME="${HERMES_HOME}" /usr/lib/hermes-agent/.venv/bin/python /ctx/tests/report-check.py \
       --plugin-dir /usr/share/hermes-os/plugins/hermes_os --libexec /usr/libexec/hermes-os-morgenbericht; then
    pass "morning report: summary, thresholds, comparison with the previous report, notification"
  else
    fail "morning report check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/report-check.py not in build context, report check skipped"
fi
if grep -qE '^\s*hermes-morgenbericht-ein\b' <<< "${JUST_OUT}" && grep -qE '^\s*hermes-morgenbericht-aus\b' <<< "${JUST_OUT}"; then
  pass "ujust lists hermes-morgenbericht-ein and -aus"
else
  fail "ujust does not list hermes-morgenbericht-ein/-aus"
fi

# 7k. KRunner-Runner „Hermes fragen“: Registrierung für KRunner, Runner-Logik
#     und D-Bus-Draht des Leisten-Symbols. Der Test prüft Präfix, Treffer, Run,
#     das Drahtformat und die Desktop-Datei; gibt es dbus-daemon und dbus-send,
#     spielt er Match und Run über einen privaten Bus durch.
for f in /usr/share/krunner/dbusplugins/hermes-os.desktop \
         /usr/share/hermes-os/tray/runner.py \
         /usr/share/hermes-os/tray/dbus_peer.py; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done
if command -v desktop-file-validate >/dev/null 2>&1; then
  if desktop-file-validate /usr/share/krunner/dbusplugins/hermes-os.desktop; then
    pass "desktop-file-validate /usr/share/krunner/dbusplugins/hermes-os.desktop"
  else
    fail "desktop-file-validate /usr/share/krunner/dbusplugins/hermes-os.desktop"
  fi
fi
if [ -f /ctx/tests/runner-check.py ]; then
  if /usr/bin/python3 /ctx/tests/runner-check.py --tray-dir /usr/share/hermes-os/tray \
       --desktop-file /usr/share/krunner/dbusplugins/hermes-os.desktop; then
    pass "krunner runner: prefix, matches, run, wire format and desktop file"
  else
    fail "krunner runner check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/runner-check.py not in build context, runner check skipped"
fi

# 7l. Dashboard: gebautes Frontend aus der Node-Stufe, Stempel passt zum
#     Release, Fenster mit QtWebEngine, Menüeintrag, Rezept. Dann die Logik
#     des Fensters gegen Attrappen (tests/dashboard-check.py) und schließlich
#     das echte `hermes dashboard` aus der Venv: über dashboard_server.py
#     starten (ohne User-Manager direkt), /api/health und die ausgelieferte
#     index.html mit Sitzungs-Token prüfen, beenden.
WEB_DIST=/usr/lib/hermes-agent/hermes_cli/web_dist
for f in "${WEB_DIST}/index.html" "${WEB_DIST}/.hermes-os-web" \
         /usr/libexec/hermes-os-dashboard \
         /usr/share/hermes-os/dashboard/dashboard_server.py \
         /usr/share/applications/hermes-os-dashboard.desktop; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done
if [ -n "$(find "${WEB_DIST}/assets" -name '*.js' -print -quit 2>/dev/null)" ]; then
  pass "web_dist has assets ($(find "${WEB_DIST}" -type f | wc -l) files, $(du -sm "${WEB_DIST}" | cut -f1) MB)"
else
  fail "web_dist/assets has no .js bundle"
fi
WEB_REF="$(sed -n 's/^ref=//p' "${WEB_DIST}/.hermes-os-web" 2>/dev/null || true)"
VENV_REF="$(sed -n 's/^ref=//p' /usr/lib/hermes-agent/.hermes-os-release 2>/dev/null || true)"
if [ -n "${WEB_REF}" ] && [ "${WEB_REF}" = "${VENV_REF}" ]; then
  pass "web_dist built from ${WEB_REF} (node $(sed -n 's/^node=//p' "${WEB_DIST}/.hermes-os-web"))"
else
  fail "web_dist stamp ref '${WEB_REF}' does not match venv ref '${VENV_REF}'"
fi
if grep -qE '^\s*hermes-dashboard\b' <<< "${JUST_OUT}"; then
  pass "ujust lists hermes-dashboard"
else
  fail "ujust does not list hermes-dashboard"
fi
if command -v desktop-file-validate >/dev/null 2>&1; then
  if desktop-file-validate /usr/share/applications/hermes-os-dashboard.desktop; then
    pass "desktop-file-validate hermes-os-dashboard.desktop"
  else
    fail "desktop-file-validate hermes-os-dashboard.desktop"
  fi
fi
if [ -x /usr/libexec/hermes-os-dashboard ]; then
  if /usr/libexec/hermes-os-dashboard --check; then
    pass "hermes-os-dashboard --check (PySide6 QtWebEngine, module, web_dist)"
  else
    fail "hermes-os-dashboard --check failed"
  fi
fi
if [ -f /ctx/tests/dashboard-check.py ]; then
  if /usr/bin/python3 /ctx/tests/dashboard-check.py --dashboard-dir /usr/share/hermes-os/dashboard \
       --launcher /usr/libexec/hermes-os-dashboard \
       --desktop-file /usr/share/applications/hermes-os-dashboard.desktop \
       --just-file /usr/share/hermes-os/hermes-os.just; then
    pass "dashboard start/stop logic works against fakes"
  else
    fail "dashboard check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/dashboard-check.py not in build context, dashboard logic check skipped"
fi
# Echtes Dashboard aus der Venv: Port 9119 wie im Betrieb, HERMES_HOME des Gates.
# Der Marker deckt danach auf, ob der Server etwas unter /usr/lib/hermes-agent
# geschrieben hat (im Build noch beschreibbar, im Image dann Ballast).
touch "${HERMES_HOME}/dashboard-marker"
if HOME="${HERMES_HOME}" /usr/bin/python3 - <<'PY'
import sys, urllib.request
sys.path.insert(0, "/usr/share/hermes-os/dashboard")
import dashboard_server as ds
s = ds.Server(port=9119, use_systemd=False)
r = s.ensure(timeout=90)
try:
    if not r.ok:
        print("start failed:", r.message); print("\n".join(r.log)); sys.exit(1)
    if not r.started:
        print("a dashboard was already running in the build container?"); sys.exit(1)
    h = ds.health(9119)
    assert h and h.get("ok") is True, h
    html = urllib.request.urlopen(r.url + "/", timeout=10).read().decode("utf-8", "replace")
    assert "__HERMES_SESSION_TOKEN__" in html, html[:400]
    assert 'id="root"' in html, html[:400]
    js = [ln for ln in html.splitlines() if "/assets/index-" in ln and "src=" in ln]
    assert js, "index.html references no /assets/index-*.js"
    asset = js[0].split('src="', 1)[1].split('"', 1)[0]
    code = urllib.request.urlopen(r.url + asset, timeout=10).getcode()
    assert code == 200, (asset, code)
    print("dashboard serves index.html with session token and", asset, "| version", h.get("version"))
finally:
    s.stop(timeout=20)
    if s.alive():
        print("dashboard did not stop"); sys.exit(1)
PY
then
  pass "real hermes dashboard starts from the venv, serves the built frontend, stops"
else
  fail "real hermes dashboard check failed (see above)"
fi
STRAY="$(find /usr/lib/hermes-agent -newer "${HERMES_HOME}/dashboard-marker" -print 2>/dev/null | head -20)"
if [ -z "${STRAY}" ]; then
  pass "dashboard run left nothing under /usr/lib/hermes-agent"
else
  fail "dashboard run wrote into /usr/lib/hermes-agent:"
  echo "${STRAY}" | sed 's/^/    /'
fi
# Das Fenster selbst, offscreen mit QtWebEngine gegen das echte Dashboard:
# Warteseite, geladene Seite mit Hermes' Titel, Fehlerseite nach Serverende,
# Neustart über „Erneut versuchen", Stopp beim Beenden. Exit 3 heißt, Chromium
# läuft im Build-Container nicht (Sandbox, /dev/shm); das ist kein Fehler des
# Fensters und bleibt ein WARN, alles andere ist ein FAIL.
if [ -f /ctx/tests/dashboard-gui-check.py ]; then
  mkdir -p /tmp/hermes-validate-xdg
  set +e
  HOME="${HERMES_HOME}" XDG_RUNTIME_DIR=/tmp/hermes-validate-xdg \
    /usr/bin/python3 /ctx/tests/dashboard-gui-check.py --launcher /usr/libexec/hermes-os-dashboard \
      --dashboard-dir /usr/share/hermes-os/dashboard --timeout 120
  GUI_RC=$?
  set -e
  case "${GUI_RC}" in
    0) pass "dashboard window drives start, load, error page, retry and quit offscreen" ;;
    3) echo "  WARN: QtWebEngine not usable in the build container, window check skipped (see above)" ;;
    *) fail "dashboard window check failed (exit ${GUI_RC}, see above)" ;;
  esac
  rm -rf /tmp/hermes-validate-xdg
else
  echo "  WARN: /ctx/tests/dashboard-gui-check.py not in build context, window check skipped"
fi
# 7m. Lokales Modell, optional: Ollama liegt nicht im Image; hermes-os-lokal
#     lädt es auf Wunsch ins Home (gepinnte Version, Prüfsumme). Hier: kein
#     Ollama unter /usr, die User-Unit, der Helfer, die Rezepte und der Test
#     gegen Attrappen, ein nachgebautes Release-Archiv und einen nachgebauten
#     Ollama-Server. Zum Schluss schreibt der Helfer die config.yaml eines
#     eigenen HERMES_HOME und Hermes selbst muss den Anbieter, die Adresse und
#     die Kontextlänge daraus lesen (das ist der Vertrag: unser Schreiber,
#     Hermes' Leser).
if [ -e /usr/bin/ollama ] || [ -e /usr/lib/ollama ]; then
  fail "Ollama is in the image (/usr/bin/ollama or /usr/lib/ollama); it must stay an optional download"
else
  pass "no Ollama in the image; hermes-os-lokal loads it on demand"
fi
if grep -q '^ExecStart=%h/.local/share/hermes-os/ollama/bin/ollama serve' /usr/lib/systemd/user/ollama.service \
   && grep -q '^ConditionPathExists=%h/.local/share/hermes-os/ollama/bin/ollama' /usr/lib/systemd/user/ollama.service; then
  pass "ollama.service starts the downloaded Ollama from the home and stays off without it"
else
  fail "ollama.service does not point at ~/.local/share/hermes-os/ollama/bin/ollama (ExecStart, ConditionPathExists)"
fi
for f in /usr/lib/systemd/user/ollama.service /usr/libexec/hermes-os-lokal /usr/share/hermes-os/local/local_model.py; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done
if grep -q '^Environment=OLLAMA_CONTEXT_LENGTH=65536' /usr/lib/systemd/user/ollama.service \
   && grep -q '^Environment=OLLAMA_HOST=127.0.0.1:11434' /usr/lib/systemd/user/ollama.service; then
  pass "ollama.service serves 64k context on 127.0.0.1 only"
else
  fail "ollama.service lacks OLLAMA_CONTEXT_LENGTH=65536 or OLLAMA_HOST=127.0.0.1:11434"
fi
if command -v systemd-analyze >/dev/null 2>&1; then
  # Das Programm fehlt im Build absichtlich; die Meldung dazu zählt nicht.
  if systemd-analyze --user verify /usr/lib/systemd/user/ollama.service 2>&1 | grep -v -e 'Failed to connect' -e 'is not executable' \
       | grep -qiE 'error|unknown|invalid'; then
    fail "systemd-analyze verify ollama.service"
  else
    pass "systemd-analyze verify ollama.service"
  fi
fi
if /usr/libexec/hermes-os-lokal --check; then
  pass "hermes-os-lokal --check (module, PyYAML)"
else
  fail "hermes-os-lokal --check failed"
fi
if grep -qE '^\s*hermes-lokal-ein\b' <<< "${JUST_OUT}" && grep -qE '^\s*hermes-lokal-aus\b' <<< "${JUST_OUT}" \
   && grep -qE '^\s*hermes-lokal-modell\b' <<< "${JUST_OUT}" && grep -qE '^\s*hermes-lokal-status\b' <<< "${JUST_OUT}" \
   && grep -qE '^\s*hermes-lokal-entfernen\b' <<< "${JUST_OUT}"; then
  pass "ujust lists hermes-lokal-ein, -aus, -modell, -status, -entfernen"
else
  fail "ujust does not list the hermes-lokal recipes"
fi
if [ -f /ctx/tests/lokales-modell-check.py ]; then
  if /usr/bin/python3 /ctx/tests/lokales-modell-check.py --local-dir /usr/share/hermes-os/local \
       --helper /usr/libexec/hermes-os-lokal --template /usr/share/hermes-os/config.yaml.default; then
    pass "local model: GPU detection, download with checksum and space check, config writer, fake Ollama endpoint, helper"
  else
    fail "local model check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/lokales-modell-check.py not in build context, local model check skipped"
fi
LOCAL_HOME=/tmp/hermes-validate-local
rm -rf "${LOCAL_HOME}"; mkdir -p "${LOCAL_HOME}"
cp /usr/share/hermes-os/config.yaml.default "${LOCAL_HOME}/config.yaml"
# eintragen ruft danach das First-Login-Skript: das muss den lokalen Anbieter
# in config.yaml als Einrichtung erkennen und den API-Schlüssel des Gateways
# in .env anlegen, obwohl es keinen Anbieter-Schlüssel gibt.
if HERMES_HOME="${LOCAL_HOME}" HOME="${HOME:-/root}" OLLAMA_HOST=127.0.0.1:11434 /usr/libexec/hermes-os-lokal eintragen qwen3.5:9b >/dev/null \
   && [ "$(HERMES_HOME="${LOCAL_HOME}" /usr/bin/hermes config get model.provider 2>/dev/null | tail -1)" = "custom" ] \
   && [ "$(HERMES_HOME="${LOCAL_HOME}" /usr/bin/hermes config get model.base_url 2>/dev/null | tail -1)" = "http://127.0.0.1:11434/v1" ] \
   && [ "$(HERMES_HOME="${LOCAL_HOME}" /usr/bin/hermes config get model.default 2>/dev/null | tail -1)" = "qwen3.5:9b" ] \
   && [ "$(HERMES_HOME="${LOCAL_HOME}" /usr/bin/hermes config get model.context_length 2>/dev/null | tail -1)" = "65536" ] \
   && [ "$(HERMES_HOME="${LOCAL_HOME}" /usr/bin/hermes config get agent.reasoning_effort 2>/dev/null | tail -1)" = "none" ]; then
  pass "hermes reads provider custom, base_url, model, context_length 65536 and reasoning_effort none written by hermes-os-lokal"
else
  fail "hermes does not read back what hermes-os-lokal wrote (config get follows)"
  for k in model.provider model.base_url model.default model.context_length agent.reasoning_effort; do
    echo "  $k = $(HERMES_HOME="${LOCAL_HOME}" /usr/bin/hermes config get "$k" 2>&1 | tail -1)"
  done
fi
if HERMES_HOME="${LOCAL_HOME}" /usr/lib/hermes-agent/.venv/bin/python - <<'PY'
# Der Vertrag mit Hermes' Kontextprüfung: 65536 liegt über der Untergrenze,
# und die lokale Adresse zählt als lokaler Endpunkt.
from agent.model_metadata import MINIMUM_CONTEXT_LENGTH, is_local_endpoint
assert 65536 >= MINIMUM_CONTEXT_LENGTH, MINIMUM_CONTEXT_LENGTH
assert is_local_endpoint("http://127.0.0.1:11434/v1")
print("MINIMUM_CONTEXT_LENGTH", MINIMUM_CONTEXT_LENGTH)
PY
then pass "65536 context satisfies Hermes' MINIMUM_CONTEXT_LENGTH, 127.0.0.1:11434 is a local endpoint"; else fail "Hermes context floor or local endpoint check failed"; fi
if grep -qE '^API_SERVER_KEY=[0-9a-f]{48}$' "${LOCAL_HOME}/.env" 2>/dev/null; then
  pass "first-login treats a local model in config.yaml as a configured provider (API_SERVER_KEY in .env)"
else
  fail "first-login did not add API_SERVER_KEY for a local-only configuration (log follows)"
  sed 's/^/  /' "${LOCAL_HOME}/hermes-os-first-login.log" 2>/dev/null | tail -10
fi
rm -rf "${LOCAL_HOME}"

# 7n. Sehen und Hören (docs/sehen-hoeren.md): Kürzel-Dateien für „Was sehe ich
#     hier?", die Module des Leisten-Symbols, die Symbole für Zuhören und
#     Sprechen, der Sprachhelfer in der Hermes-Venv (Importe von faster-whisper,
#     piper und Hermes' Helfern, ohne Modelle zu laden) und der Test ohne
#     Audio-Hardware: Zustandsautomat, Helfer gegen Attrappen, Bildweg gegen
#     einen nachgebauten Client, Kürzel-Registrierung.
for f in /usr/share/applications/hermes-os-sehen.desktop \
         /usr/share/kglobalaccel/hermes-os-sehen.desktop \
         /usr/share/hermes-os/tray/desktop.py \
         /usr/share/hermes-os/tray/screenshot.py \
         /usr/share/hermes-os/tray/voice.py \
         /usr/share/hermes-os/tray/voice_worker.py \
         /usr/share/icons/hicolor/scalable/status/hermes-os-tray-listening.svg \
         /usr/share/icons/hicolor/scalable/status/hermes-os-tray-speaking.svg; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done
if diff -q /usr/share/applications/hermes-os-sehen.desktop /usr/share/kglobalaccel/hermes-os-sehen.desktop >/dev/null 2>&1 \
   && grep -q '^X-KDE-Shortcuts=Meta+Shift+H$' /usr/share/kglobalaccel/hermes-os-sehen.desktop \
   && grep -q '^Exec=/usr/libexec/hermes-os-tray --look$' /usr/share/kglobalaccel/hermes-os-sehen.desktop; then
  pass "sehen desktop file and its kglobalaccel copy are identical, Meta+Shift+H runs hermes-os-tray --look"
else
  fail "sehen desktop file and kglobalaccel copy differ or lack the shortcut"
fi
if command -v desktop-file-validate >/dev/null 2>&1; then
  if desktop-file-validate /usr/share/applications/hermes-os-sehen.desktop; then
    pass "desktop-file-validate /usr/share/applications/hermes-os-sehen.desktop"
  else
    fail "desktop-file-validate /usr/share/applications/hermes-os-sehen.desktop"
  fi
fi
if HOME="${HERMES_HOME}" /usr/lib/hermes-agent/.venv/bin/python /usr/share/hermes-os/tray/voice_worker.py --check; then
  pass "voice_worker --check in the Hermes venv (faster_whisper, piper, Hermes helpers)"
else
  fail "voice_worker --check failed in the Hermes venv"
fi
if [ -f /ctx/tests/sehen-hoeren-check.py ]; then
  if HOME="${HERMES_HOME}" /usr/bin/python3 /ctx/tests/sehen-hoeren-check.py --tray-dir /usr/share/hermes-os/tray \
       --desktop-file /usr/share/kglobalaccel/hermes-os-sehen.desktop; then
    pass "sehen-hoeren: shortcuts, push-to-talk automaton, worker against fakes, image path against a fake client"
  else
    fail "sehen-hoeren check failed (see above)"
  fi
else
  echo "  WARN: /ctx/tests/sehen-hoeren-check.py not in build context, sehen-hoeren check skipped"
fi

# 8. Kein Git-Checkout im Image (sonst versucht hermes update einen pull)
if [ -d /usr/lib/hermes-agent/.git ]; then fail ".git left in image"; else pass "no .git in image"; fi

rm -rf "${HERMES_HOME}"
if [ "${FAIL}" -ne 0 ]; then
  echo "=== validation FAILED ==="
  exit 1
fi
echo "=== validation OK ==="
