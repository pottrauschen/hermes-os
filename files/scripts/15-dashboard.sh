#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Dashboard: gebautes Frontend in die Hermes-Installation legen
# =============================================================================
# `hermes dashboard` ist ein FastAPI-Server in der Venv (hermes_cli/web_server.py)
# und liefert das React-Frontend aus hermes_cli/web_dist aus. Der Python-Teil
# kommt mit 10-hermes.sh; das Frontend baut die Node-Stufe `webbuild` des
# Dockerfiles aus demselben Release (HERMES_REF) und reicht nur den fertigen
# Ordner über den Build-Kontext nach /ctx/web_dist. Node und npm kommen
# damit nie ins Image, und der Ordner liegt read-only unter /usr wie der
# Rest von Hermes. Der Stempel .hermes-os-web (Ref, Commit, Node, npm) stammt
# aus der Node-Stufe; 80-validate.sh prüft, dass er zum Venv-Release passt.
# =============================================================================
set -xeuo pipefail

HERMES_ROOT=/usr/lib/hermes-agent
WEB_SRC=/ctx/web_dist
WEB_DST="${HERMES_ROOT}/hermes_cli/web_dist"

test -f "${WEB_SRC}/index.html"
test -f "${WEB_SRC}/.hermes-os-web"
rm -rf "${WEB_DST}"
mkdir -p "${WEB_DST}"
cp -a "${WEB_SRC}/." "${WEB_DST}/"
find "${WEB_DST}" -type d -exec chmod 0755 {} +
find "${WEB_DST}" -type f -exec chmod 0644 {} +

# Der Stempel der Node-Stufe muss dasselbe Release nennen wie die Venv.
WEB_REF="$(sed -n 's/^ref=//p' "${WEB_DST}/.hermes-os-web")"
if [ "${WEB_REF}" != "${HERMES_REF}" ]; then
  echo "Dashboard-Frontend gebaut aus ${WEB_REF}, Venv aus ${HERMES_REF}" >&2
  exit 1
fi
echo "web_dist: $(find "${WEB_DST}" -type f | wc -l) Dateien, $(du -sm "${WEB_DST}" | cut -f1) MB"

# ---- Fenster: PySide6 mit QtWebEngine ---------------------------------------
# Das Fenster /usr/libexec/hermes-os-dashboard zeigt das Dashboard mit
# QWebEngineView. python3-pyside6 und qt6-qtwebengine liegen im Aurora-Image
# (als Layer der Kinoite-Basis, nicht von Aurora selbst gewählt; Stand
# 44.20260921.0). Der Aufruf ist dann ein No-op und hält die Pakete, falls
# die Basis sie einmal fallen lässt; 80-validate.sh prüft den Import.
dnf install -y python3-pyside6 qt6-qtwebengine
