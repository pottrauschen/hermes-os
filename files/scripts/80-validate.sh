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

# 2. Interpreter ist 3.14 (uv-verwaltet, nicht Fedora-Python)
PYV="$(/usr/lib/hermes-agent/.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "${PYV}" = "3.14" ]; then pass "venv python ${PYV}"; else fail "venv python is ${PYV}, expected 3.14"; fi

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

# 5. Install-Stempel sagt: Updates kommen von außen
if grep -q '"updateMechanism": *"external"' /usr/lib/hermes-agent/install-stamp.json 2>/dev/null; then
  pass "install stamp: updateMechanism external"
else
  fail "install stamp missing or not external"
fi

# 6. Das hermes-os-Plugin lädt (Manifest + register())
PLUGIN=/usr/share/hermes-os/plugins/hermes_os
if [ -f "${PLUGIN}/plugin.yaml" ] && [ -f "${PLUGIN}/__init__.py" ]; then
  if (cd /usr/share/hermes-os/plugins && /usr/lib/hermes-agent/.venv/bin/python - <<'PY'
import importlib, sys
sys.path.insert(0, ".")
m = importlib.import_module("hermes_os")
class Ctx:
    def __init__(self): self.tools = []; self.sections = []
    def register_tool(self, name, toolset, schema, handler, **kw): self.tools.append(name)
    def register_system_prompt_section(self, id, content, **kw): self.sections.append(id)
ctx = Ctx()
m.register(ctx)
assert len(ctx.tools) >= 6, ctx.tools
assert ctx.sections, "no system prompt section registered"
print("tools:", ", ".join(ctx.tools))
PY
  ); then pass "plugin hermes_os registers"; else fail "plugin hermes_os failed to register"; fi
else
  fail "plugin hermes_os files missing"
fi

# 7. Skill, Config-Vorlage, Dienst, Autostart
for f in /usr/share/hermes-os/skills/hermes-os-system/SKILL.md \
         /usr/share/hermes-os/config.yaml.default \
         /usr/lib/systemd/user/hermes-gateway.service \
         /etc/xdg/autostart/hermes-os-first-login.desktop \
         /usr/libexec/hermes-os-first-login \
         /usr/share/ublue-os/just/90-hermes-os.just; do
  if [ -e "$f" ]; then pass "$f"; else fail "$f missing"; fi
done

# 8. Kein Git-Checkout im Image (sonst versucht hermes update einen pull)
if [ -d /usr/lib/hermes-agent/.git ]; then fail ".git left in image"; else pass "no .git in image"; fi

rm -rf "${HERMES_HOME}"
if [ "${FAIL}" -ne 0 ]; then
  echo "=== validation FAILED ==="
  exit 1
fi
echo "=== validation OK ==="
