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
         /usr/share/ublue-os/just/60-custom.just; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done

# 7b. ujust sieht unsere Rezepte wirklich. Aurora's /usr/bin/ujust ruft
#     just mit /usr/share/ublue-os/just/00-entry.just auf (aus dem
#     common-Image), und die importiert optional 60-custom.just. Deshalb
#     den echten Wrapper fragen, nicht /usr/share/ublue-os/justfile aus dem
#     RPM ublue-os-just, das Aurora gar nicht benutzt.
JUST_OUT="$(ujust --list 2>&1)" || true
if echo "${JUST_OUT}" | grep -qE '^\s*hermes-setup\b'; then
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

# 8. Kein Git-Checkout im Image (sonst versucht hermes update einen pull)
if [ -d /usr/lib/hermes-agent/.git ]; then fail ".git left in image"; else pass "no .git in image"; fi

rm -rf "${HERMES_HOME}"
if [ "${FAIL}" -ne 0 ]; then
  echo "=== validation FAILED ==="
  exit 1
fi
echo "=== validation OK ==="
