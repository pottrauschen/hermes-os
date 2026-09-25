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
HERMES_PYTHON="${HERMES_PYTHON:?HERMES_PYTHON must be set (Dockerfile ARG)}"
HERMES_REPO="${HERMES_REPO:-https://github.com/NousResearch/hermes-agent.git}"

# ---- Build-Abhängigkeiten ----------------------------------------------------
# uv wird gepinnt aus PyPI geholt (nicht aus dem Fedora-Repo, dessen Version
# vom Basis-Image abhängt). Hermes 0.21.x braucht ein uv, das relative
# exclude-newer-Angaben und das aktuelle Lock-Format kennt; 0.8 ist zu alt,
# 0.11.33 ist gegen das Release getestet (tests/venv-smoke.sh).
# Die Compiler werden nur gebraucht, falls ein Paket kein Wheel hat; sie
# werden am Ende wieder entfernt.
UV_PIN="${UV_PIN:-0.11.33}"
BUILD_DEPS=(gcc gcc-c++ make cmake python3-devel libffi-devel openssl-devel python3-pip)
dnf install -y git "${BUILD_DEPS[@]}"
python3 -m pip install --quiet --target /tmp/uv-bootstrap "uv==${UV_PIN}"
export PATH="/tmp/uv-bootstrap/bin:${PATH}"
uv --version

# ---- Quellcode auf dem Release-Tag -------------------------------------------
rm -rf "${HERMES_ROOT}"
git clone --depth 1 --branch "${HERMES_REF}" "${HERMES_REPO}" "${HERMES_ROOT}"
HERMES_COMMIT="$(git -C "${HERMES_ROOT}" rev-parse HEAD)"

# ---- Python und Venv ---------------------------------------------------------
# uv holt einen eigenen Interpreter (python-build-standalone) nach
# /usr/lib/hermes-agent/python. Damit hängt Hermes nicht am Fedora-Python
# und ein Fedora-Major-Bump ändert nichts an der Venv.
# Die Version muss zum gepinnten Tag passen (0.21.x: 3.11 bis 3.13).
export UV_PYTHON_INSTALL_DIR="${HERMES_ROOT}/python"
export UV_CACHE_DIR=/var/cache/uv
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${HERMES_ROOT}/.venv"

cd "${HERMES_ROOT}"
uv python install "${HERMES_PYTHON}"
# --locked: exakt uv.lock des Tags, Build bricht ab, wenn das Lock nicht passt
#           (dieselbe Form, die Hermes' eigenes setup-hermes.sh benutzt).
# --extra all: der von Hermes selbst für Produktions-Images vorgesehene Satz.
# Das Projekt selbst wird editierbar eingebunden (Pfad ist im Image stabil).
uv sync --locked --extra all --python "${HERMES_PYTHON}"

# ---- Launcher ----------------------------------------------------------------
cat > /usr/bin/hermes <<'EOF'
#!/bin/sh
# hermes-os: Launcher für den ins Image gebackenen Hermes Agent.
exec /usr/lib/hermes-agent/.venv/bin/hermes "$@"
EOF
chmod 0755 /usr/bin/hermes

# ---- Install-Stempel ---------------------------------------------------------
# Hermes 0.21.x kennt die Werte apt/docker/nix/nixos/home-manager/git/unknown.
# "apt" heißt: paketverwaltet, `hermes update` verweigert und verweist auf den
# Paketmanager. Das ist hier semantisch richtig: das Image ist der Paketmanager.
printf 'apt\n' > "${HERMES_ROOT}/.install_method"

# Eigener Stempel für os_status und ujust hermes-os-info.
cat > "${HERMES_ROOT}/.hermes-os-release" <<EOF
ref=${HERMES_REF}
commit=${HERMES_COMMIT}
python=${HERMES_PYTHON}
update=image
EOF

# ---- Aufräumen ---------------------------------------------------------------
rm -rf "${HERMES_ROOT}/.git" /tmp/uv-bootstrap
find "${HERMES_ROOT}" -name '__pycache__' -type d -prune -exec rm -rf {} +
dnf remove -y "${BUILD_DEPS[@]}"

# Smoke-Test schon hier, damit ein kaputter Build früh abbricht.
HERMES_HOME=/tmp/hermes-build-check /usr/bin/hermes --version
