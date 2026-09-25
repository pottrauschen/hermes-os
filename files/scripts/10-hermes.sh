#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Hermes Agent als Systembestandteil
# =============================================================================
# Baut Hermes aus einem festgenagelten Release (HERMES_REF) nach
# /usr/lib/hermes-agent mit eigener, von uv verwalteter Python-Venv
# (Version aus HERMES_PYTHON, derzeit 3.13, passend zur Release-Linie 0.21.x).
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

# ---- uv, gepinnt und geprüft ------------------------------------------------
# uv kommt als Release-Tarball von GitHub mit SHA256-Prüfung, nicht aus dem
# Fedora-Repo (Version hängt am Basis-Image) und nicht über pip (bräuchte
# python3-pip im Image). Hermes 0.21.x braucht ein uv, das relative
# exclude-newer-Angaben und das aktuelle Lock-Format kennt; 0.8 ist zu alt,
# 0.11.33 ist gegen das Release getestet (tests/venv-smoke.sh).
#
# Das Binary bleibt als /usr/bin/uv im Image: Hermes' Lazy-Installer
# (tools/lazy_deps.py) braucht zur Laufzeit einen Installer, und die
# uv-erzeugte Venv hat kein pip. Ohne /usr/bin/uv wäre jedes optionale
# Backend (Messaging-Plattformen, Wake-Word, Cloud-Suche) tot.
UV_PIN="${UV_PIN:-0.11.33}"
UV_TRIPLE="x86_64-unknown-linux-gnu"
UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_PIN}/uv-${UV_TRIPLE}.tar.gz"
mkdir -p /tmp/uv-bootstrap
cd /tmp/uv-bootstrap
curl -fsSL --retry 3 -o uv.tar.gz "${UV_URL}"
curl -fsSL --retry 3 -o uv.tar.gz.sha256 "${UV_URL}.sha256"
# Die .sha256-Datei nennt den Dateinamen ohne Pfad; auf unseren Namen umbiegen.
echo "$(cut -d' ' -f1 uv.tar.gz.sha256)  uv.tar.gz" | sha256sum -c -
tar -xzf uv.tar.gz --strip-components=1
install -m0755 ./uv /usr/bin/uv
uv --version

# git bringt Aurora mit; der Aufruf ist ein No-op und dokumentiert die
# Abhängigkeit. Compiler werden nicht gebraucht: alle gepinnten
# Abhängigkeiten kommen als Wheels (geprüft mit tests/venv-smoke.sh).
dnf install -y git

# ---- Quellcode auf dem Release-Tag -------------------------------------------
rm -rf "${HERMES_ROOT}"
git clone --depth 1 --branch "${HERMES_REF}" "${HERMES_REPO}" "${HERMES_ROOT}"
HERMES_COMMIT="$(git -C "${HERMES_ROOT}" rev-parse HEAD)"

# ---- Python und Venv ---------------------------------------------------------
# uv holt einen eigenen Interpreter (python-build-standalone) nach
# /usr/lib/hermes-agent/python. Damit hängt Hermes nicht am Fedora-Python
# und ein Fedora-Major-Bump ändert nichts an der Venv.
export UV_PYTHON_INSTALL_DIR="${HERMES_ROOT}/python"
export UV_CACHE_DIR=/var/cache/uv
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${HERMES_ROOT}/.venv"
export UV_NO_MODIFY_PATH=1

cd "${HERMES_ROOT}"
# --no-bin: keine python3.13-Shims nach /root/.local/bin (das Image hat kein
# brauchbares /root, und bootc container lint mag dort keine Reste).
uv python install --no-bin "${HERMES_PYTHON}"
# --locked: exakt uv.lock des Tags, Build bricht ab, wenn das Lock nicht passt
#           (dieselbe Form, die Hermes' eigenes setup-hermes.sh benutzt).
# --extra all:   der von Hermes selbst für Produktions-Images vorgesehene Satz.
# --extra voice: lokale Spracherkennung (faster-whisper). Hermes würde sie
#                sonst beim ersten Gebrauch in die Venv nachinstallieren, und
#                die liegt hier read-only unter /usr.
# Das Projekt selbst wird editierbar eingebunden (Pfad ist im Image stabil).
uv sync --locked --extra all --extra voice --python "${HERMES_PYTHON}"

# Piper (lokale Sprachausgabe) ist in 0.21.x kein Extra, sondern wird von
# `hermes setup` per pip in die Venv installiert. Hier fest eingebaut, mit dem
# Pin, den Hermes main im Extra [piper] führt.
PIPER_PIN="${PIPER_PIN:-1.8.0}"
uv pip install --python "${HERMES_ROOT}/.venv/bin/python" "piper-tts==${PIPER_PIN}"

# ---- Bytecode ----------------------------------------------------------------
# /usr ist zur Laufzeit read-only und die Prozesse laufen mit
# PYTHONDONTWRITEBYTECODE. Ohne vorkompilierte .pyc würde jeder Start Hermes,
# site-packages und Teile der Standardbibliothek im Speicher neu übersetzen
# (etwa 1 bis 2 Sekunden). Hash-basierte, ungeprüfte .pyc sind unabhängig von
# mtimes, die `podman build --timestamp=0` und ostree ohnehin verändern.
# -f erzwingt das Überschreiben der zeitstempelbasierten .pyc, die uv anlegt.
"${HERMES_ROOT}/.venv/bin/python" -m compileall -q -f -j 0 \
    --invalidation-mode unchecked-hash "${HERMES_ROOT}"

# ---- Launcher ----------------------------------------------------------------
# HERMES_LAZY_INSTALL_TARGET: Hermes' eigener Mechanismus für versiegelte
# Images (siehe tools/lazy_deps.py). Optionale Backends, die erst bei Gebrauch
# gebraucht werden (Messaging-Plattformen, Cloud-Suche, Wake-Word), landen
# damit unter ~/.hermes/lazy-packages statt in der read-only Venv. Der
# Ordner wird ans ENDE von sys.path gehängt, kann also nichts überschreiben.
# Für systemd-User-Units setzt /usr/lib/environment.d/60-hermes-os.conf
# dieselbe Variable, auch für die Unit, die `hermes setup` selbst anlegt.
#
# `hermes update` wird abgefangen: Hermes würde mit dem Termux-Hinweis
# `pkg upgrade hermes-agent` verweigern (Stempel apt, siehe unten). Hier gilt
# stattdessen `ujust update`.
cat > /usr/bin/hermes <<'EOF'
#!/bin/sh
# hermes-os: Launcher für den ins Image gebackenen Hermes Agent.
export PYTHONDONTWRITEBYTECODE=1
: "${HERMES_LAZY_INSTALL_TARGET:=${HERMES_HOME:-${HOME}/.hermes}/lazy-packages}"
export HERMES_LAZY_INSTALL_TARGET
for arg in "$@"; do
  case "$arg" in
    -*) continue ;;
    update)
      echo "hermes-os: Hermes ist Teil des System-Images und aktualisiert sich nicht selbst." >&2
      echo "           Neues Image holen: ujust update   (Rollback: sudo bootc rollback)" >&2
      exit 2 ;;
    *) break ;;
  esac
done
exec /usr/lib/hermes-agent/.venv/bin/hermes "$@"
EOF
chmod 0755 /usr/bin/hermes

# ---- Install-Stempel ---------------------------------------------------------
# Hermes 0.21.x kennt die Werte apt/docker/nix/nixos/home-manager/git/unknown.
# "apt" ist dort der Termux-Wert. Er wird nur benutzt, weil `hermes update`
# damit verlässlich mit Exit 2 verweigert und der Update-Hinweis im Banner
# verschwindet; die Meldung nennt `pkg upgrade hermes-agent`, was hier nicht
# gilt. Deshalb fängt der Launcher oben `update` vorher ab.
printf 'apt\n' > "${HERMES_ROOT}/.install_method"

# Eigener Stempel für os_status und ujust hermes-os-info.
cat > "${HERMES_ROOT}/.hermes-os-release" <<EOF
ref=${HERMES_REF}
commit=${HERMES_COMMIT}
python=${HERMES_PYTHON}
uv=${UV_PIN}
update=image
EOF

# ---- Aufräumen ---------------------------------------------------------------
rm -rf "${HERMES_ROOT}/.git" /tmp/uv-bootstrap /root/.cache /root/.local

# Smoke-Test schon hier, damit ein kaputter Build früh abbricht.
HERMES_HOME=/tmp/hermes-build-check /usr/lib/hermes-agent/.venv/bin/hermes --version
