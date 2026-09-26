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
     && (cd /usr/lib/hermes-agent && /usr/lib/hermes-agent/.venv/bin/python - <<'PY'
import hermes_cli.plugins as hp
from tools.registry import registry
hp.discover_plugins(force=True)
names = sorted(n for n in registry.get_all_tool_names() if n.startswith(("os_", "app_launch")))
assert len(names) == 8, names
assert registry.get_toolset_for_tool("os_status") == "hermes_os"
pm = hp._ensure_plugins_discovered()
sections = getattr(pm, "_system_prompt_sections", None) or getattr(pm, "system_prompt_sections", {})
assert "hermes-os.system" in sections, list(sections)
# Freigabe-Hook: System-Befehle landen im Dialog, freie Befehle nicht
d = hp._get_pre_tool_call_directive_details("terminal", {"command": "sudo bootc switch ghcr.io/x/y:latest"})
assert d.action == "approve", d
d = hp._get_pre_tool_call_directive_details("terminal", {"command": "systemctl --user restart hermes-gateway"})
assert d.action is None, d
print("tools:", ", ".join(names), "| approval hook active")
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
#     Zustände des Fensters offscreen. Beide Tests kommen aus /ctx/tests.
for f in /usr/libexec/hermes-os-tray \
         /usr/share/hermes-os/tray/Main.qml \
         /usr/share/hermes-os/tray/hermes_client.py \
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

# 8. Kein Git-Checkout im Image (sonst versucht hermes update einen pull)
if [ -d /usr/lib/hermes-agent/.git ]; then fail ".git left in image"; else pass "no .git in image"; fi

rm -rf "${HERMES_HOME}"
if [ "${FAIL}" -ne 0 ]; then
  echo "=== validation FAILED ==="
  exit 1
fi
echo "=== validation OK ==="
