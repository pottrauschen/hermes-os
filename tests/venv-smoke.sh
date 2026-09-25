#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Smoke-Test für den riskantesten Build-Schritt ohne Podman
# =============================================================================
# Führt die Venv-Schritte aus 10-hermes.sh in einem temporären Verzeichnis
# aus (uv-verwaltetes Python 3.14, uv sync --frozen --extra all) und ruft
# danach hermes --version auf. Läuft auf jedem Linux mit uv und git,
# braucht keinen Container. Prüft NICHT die Fedora-Paketschicht.
#
#   ./tests/venv-smoke.sh [HERMES_REF] [WORKDIR]
# =============================================================================
set -euo pipefail

HERMES_REF="${1:-v2026.9.24}"
WORK="${2:-$(mktemp -d)}"
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
uv python install 3.14
uv sync --frozen --extra all --python 3.14

echo "== python: $("${ROOT}/.venv/bin/python" --version)"
HERMES_HOME="${WORK}/home" "${ROOT}/.venv/bin/hermes" --version
"${ROOT}/.venv/bin/python" -c 'import hermes_cli.main, hermes_cli.plugins, tools.checkpoint_manager; print("core imports ok")'

# Install-Stempel wie im Image
"${ROOT}/.venv/bin/python" "${ROOT}/scripts/write_install_stamp.py" \
  --output "${WORK}/install-stamp.json" \
  --commit "$(git -C "${ROOT}" rev-parse HEAD)" \
  --base-version "${HERMES_REF#v}" \
  --source bootc-image --update-mechanism external
cat "${WORK}/install-stamp.json"
echo "== venv smoke test OK"
