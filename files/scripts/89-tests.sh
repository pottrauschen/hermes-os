#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Build-Tests (Basis-Image unverändert? Werkzeuge da?)
# =============================================================================
# 80-validate.sh prüft die Agent-Schicht. Hier: was das Plugin zur Laufzeit
# aufruft, muss im Image existieren, sonst antwortet der Agent mit Fehlern.
# =============================================================================
set -euo pipefail

FAILURES=0
check_pass() { echo "  PASS: $1"; }
check_fail() { echo "  FAIL: $1"; FAILURES=$((FAILURES + 1)); }

echo "=== Commands the hermes_os plugin and launcher call (hard) ==="
for cmd in bootc rpm-ostree skopeo systemctl systemd-run journalctl flatpak nmcli lsblk lscpu lspci \
           free df uname gio notify-send uv; do
  if command -v "$cmd" >/dev/null 2>&1; then check_pass "$cmd"; else check_fail "$cmd not found"; fi
done

echo "=== Commands the docs and ujust recipes mention (soft) ==="
for cmd in ujust just distrobox podman konsole; do
  if command -v "$cmd" >/dev/null 2>&1; then check_pass "$cmd"; else echo "  WARN: $cmd not found"; fi
done

echo "=== Base image identity ==="
# VARIANT_ID wird erst in 91-image-info.sh gesetzt, also hier nicht prüfen.
if grep -qiE 'aurora' /usr/lib/os-release; then check_pass "Aurora base"; else echo "  WARN: os-release does not mention Aurora: $(grep -E '^(NAME|ID|VARIANT_ID)=' /usr/lib/os-release | tr '\n' ' ')"; fi

echo "=== No build-only packages added ==="
# 10-hermes.sh installiert keine Compiler mehr (alle Abhängigkeiten kommen
# als Wheels). Diese Pakete bringt Aurora nicht mit; tauchen sie auf, hat
# jemand den Build wieder mit Build-Deps aufgeblasen.
for pkg in cmake python3-devel libffi-devel python3-pip; do
  if rpm -q "$pkg" >/dev/null 2>&1; then check_fail "$pkg installed (build-only package left in image)"; else check_pass "$pkg not present"; fi
done

echo "=== Precompiled bytecode present ==="
# Kein `find | grep -q`: unter pipefail beendet grep die Pipe nach dem ersten
# Treffer, find stirbt an SIGPIPE und der Test schlägt fälschlich fehl.
if [ -n "$(find /usr/lib/hermes-agent/hermes_cli -name '*.pyc' -path '*__pycache__*' -print -quit)" ]; then
  check_pass "hermes_cli has .pyc ($(find /usr/lib/hermes-agent/hermes_cli -name '*.pyc' | wc -l) files)"
else
  check_fail "no .pyc under /usr/lib/hermes-agent/hermes_cli (compileall missing?)"
fi

echo "=== Size sanity ==="
SIZE_MB=$(du -sm /usr/lib/hermes-agent | cut -f1)
echo "  /usr/lib/hermes-agent: ${SIZE_MB} MB"
if [ "${SIZE_MB}" -gt 4000 ]; then check_fail "hermes tree larger than 4 GB, check extras"; else check_pass "hermes tree size ok"; fi

if [ "${FAILURES}" -ne 0 ]; then
  echo "=== ${FAILURES} test(s) FAILED ==="
  exit 1
fi
echo "=== all tests passed ==="
