#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Hermes Agent als Systembestandteil
# =============================================================================
# Baut Hermes aus einem festgenagelten Release (HERMES_REF) nach
# /usr/lib/hermes-agent mit eigener, von uv verwalteter Python-3.14-Venv.
#
# Warum nicht der offizielle Installer (install.sh)?
#   Der zielt auf ~/.hermes im Home des Nutzers und will sich selbst
#   aktualisieren. Hier gehört der Code ins read-only /usr und wird nur über
#   ein neues Image aktualisiert. Nutzerdaten (Config, Sessions, Memory,
#   Checkpoints, Skills, Plugins) liegen weiterhin unter ~/.hermes.
#
# Warum nicht Hermes' eigenes Docker-Image als Podman-Container?
#   Dann läuft die Shell des Agenten im Container und sieht weder bootc,
#   flatpak, systemd noch KWin. Für ein System, das sich selbst bedienen
#   soll, muss der Agent auf dem Host laufen.
# =============================================================================
set -xeuo pipefail

HERMES_ROOT=/usr/lib/hermes-agent
HERMES_REF="${HERMES_REF:?HERMES_REF must be set (Dockerfile ARG)}"
HERMES_REPO="${HERMES_REPO:-https://github.com/NousResearch/hermes-agent.git}"

# ---- Build-Abhängigkeiten ----------------------------------------------------
# uv kommt aus dem Fedora-Repo. Die Compiler werden nur gebraucht, falls ein
# Paket kein Wheel für 3.14 hat; sie werden am Ende wieder entfernt.
BUILD_DEPS=(gcc gcc-c++ make cmake python3-devel libffi-devel openssl-devel)
dnf install -y git uv "${BUILD_DEPS[@]}"

# ---- Quellcode auf dem Release-Tag -------------------------------------------
rm -rf "${HERMES_ROOT}"
git clone --depth 1 --branch "${HERMES_REF}" "${HERMES_REPO}" "${HERMES_ROOT}"
HERMES_COMMIT="$(git -C "${HERMES_ROOT}" rev-parse HEAD)"

# ---- Python 3.14 und Venv ----------------------------------------------------
# uv holt einen eigenen Interpreter (python-build-standalone) nach
# /usr/lib/hermes-agent/python. Damit hängt Hermes nicht am Fedora-Python
# und ein Fedora-Major-Bump ändert nichts an der Venv.
export UV_PYTHON_INSTALL_DIR="${HERMES_ROOT}/python"
export UV_CACHE_DIR=/var/cache/uv
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${HERMES_ROOT}/.venv"

cd "${HERMES_ROOT}"
uv python install 3.14
# --frozen: exakt uv.lock des Tags, keine Neuauflösung.
# --extra all: der von Hermes selbst für Produktions-Images vorgesehene Satz.
# Das Projekt selbst wird editierbar eingebunden (Pfad ist im Image stabil).
uv sync --frozen --extra all --python 3.14

# ---- Launcher ----------------------------------------------------------------
cat > /usr/bin/hermes <<'EOF'
#!/bin/sh
# hermes-os: Launcher für den ins Image gebackenen Hermes Agent.
exec /usr/lib/hermes-agent/.venv/bin/hermes "$@"
EOF
chmod 0755 /usr/bin/hermes

# ---- Install-Stempel ---------------------------------------------------------
# updateMechanism=external: Hermes weiß, dass es sich nicht selbst
# aktualisiert. version_info liest den Stempel, weil .git unten entfernt wird.
"${HERMES_ROOT}/.venv/bin/python" "${HERMES_ROOT}/scripts/write_install_stamp.py" \
    --output "${HERMES_ROOT}/install-stamp.json" \
    --commit "${HERMES_COMMIT}" \
    --base-version "${HERMES_REF#v}" \
    --source bootc-image \
    --update-mechanism external

# ---- Aufräumen ---------------------------------------------------------------
rm -rf "${HERMES_ROOT}/.git"
find "${HERMES_ROOT}" -name '__pycache__' -type d -prune -exec rm -rf {} +
dnf remove -y "${BUILD_DEPS[@]}"

# Smoke-Test schon hier, damit ein kaputter Build früh abbricht.
HERMES_HOME=/tmp/hermes-build-check /usr/bin/hermes --version
