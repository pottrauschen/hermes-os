#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Smoke-Test für den riskantesten Build-Schritt ohne Podman
# =============================================================================
# Führt die Venv-Schritte aus 10-hermes.sh in einem temporären Verzeichnis
# aus (uv-verwaltetes Python 3.14, uv sync --frozen --extra all) und ruft
# danach hermes --version auf. Läuft auf jedem Linux mit uv und git,
# braucht keinen Container. Prüft NICHT die Fedora-Paketschicht.
#
#   ./tests/venv-smoke.sh [HERMES_REF] [WORKDIR] [HERMES_PYTHON]
#
# Die Release-Tags (v2026.x.y) liegen auf der 0.21-Linie mit Python <3.14;
# main ist bereits bei 3.14. HERMES_PYTHON muss zum Tag passen.
# =============================================================================
set -euo pipefail

HERMES_REF="${1:-v2026.9.24}"
WORK="${2:-$(mktemp -d)}"
HERMES_PYTHON="${3:-3.13}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="${REPO_DIR}/files/system/usr/share/hermes-os/plugins"
HERMES_REPO="${HERMES_REPO:-https://github.com/NousResearch/hermes-agent.git}"
ROOT="${WORK}/hermes-agent"

echo "== workdir ${WORK}, ref ${HERMES_REF}"
if [ ! -d "${ROOT}" ]; then
  git clone --depth 1 --branch "${HERMES_REF}" "${HERMES_REPO}" "${ROOT}"
fi

export UV_PYTHON_INSTALL_DIR="${ROOT}/python"
export UV_CACHE_DIR="${WORK}/uv-cache"
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${ROOT}/.venv"

cd "${ROOT}"
rm -rf "${ROOT}/.venv"
uv python install "${HERMES_PYTHON}"
uv sync --locked --extra all --python "${HERMES_PYTHON}"

echo "== python: $("${ROOT}/.venv/bin/python" --version)"
HERMES_HOME="${WORK}/home" "${ROOT}/.venv/bin/hermes" --version
"${ROOT}/.venv/bin/python" -c 'import hermes_cli.main, hermes_cli.plugins, tools.checkpoint_manager; print("core imports ok")'

# Das hermes-os-Plugin so laden, wie es das First-Login-Skript einrichtet:
# Symlink unter ~/.hermes/plugins, Config-Vorlage, `hermes plugins enable`,
# dann der echte Plugin-Loader des Releases.
export HERMES_HOME="${WORK}/home"
rm -rf "${HERMES_HOME}"; mkdir -p "${HERMES_HOME}/plugins"
ln -sfn "${PLUGIN_DIR}/hermes_os" "${HERMES_HOME}/plugins/hermes_os"
cp "${REPO_DIR}/files/system/usr/share/hermes-os/config.yaml.default" "${HERMES_HOME}/config.yaml"
"${ROOT}/.venv/bin/hermes" plugins enable hermes-os
for k in checkpoints.enabled approvals.mode terminal.backend stt.provider tts.provider; do
  printf "  config %-22s %s\n" "$k" "$("${ROOT}/.venv/bin/hermes" config get "$k" 2>&1 | head -1)"
done
(cd "${ROOT}" && "${ROOT}/.venv/bin/python" - <<'PY'
import hermes_cli.plugins as hp
from tools.registry import registry
hp.discover_plugins(force=True)
names = sorted(n for n in registry.get_all_tool_names() if n.startswith(("os_", "app_launch")))
assert len(names) == 8, names
assert registry.get_toolset_for_tool("os_status") == "hermes_os"
pm = hp._ensure_plugins_discovered()
sections = getattr(pm, "_system_prompt_sections", None) or getattr(pm, "system_prompt_sections", {})
assert "hermes-os.system" in sections, list(sections)
print("plugin loaded by release loader:", names, "+ prompt section hermes-os.system")
PY
)

# Update-Verweigerung mit dem Install-Stempel, den 10-hermes.sh schreibt
printf 'apt\n' > "${ROOT}/.install_method"
set +e
"${ROOT}/.venv/bin/hermes" update >/dev/null 2>&1
RC=$?
set -e
rm -f "${ROOT}/.install_method"
[ "${RC}" -eq 2 ] && echo "hermes update refuses (exit 2)" || { echo "hermes update exit ${RC}, expected 2"; exit 1; }
echo "== venv smoke test OK"
