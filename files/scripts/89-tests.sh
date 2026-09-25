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

echo "=== Command Presence (used by hermes_os plugin) ==="
for cmd in bootc rpm-ostree systemctl journalctl flatpak nmcli lsblk lscpu lspci \
           free gio gdbus qdbus notify-send ujust just distrobox podman; do
  if command -v "$cmd" >/dev/null 2>&1; then check_pass "$cmd"; else check_fail "$cmd not found"; fi
done

echo "=== Base image identity ==="
if grep -qiE 'aurora' /usr/lib/os-release; then check_pass "Aurora base"; else check_fail "os-release does not mention Aurora"; fi
if grep -q 'VARIANT_ID="hermes-os' /usr/lib/os-release; then check_pass "VARIANT_ID set"; else check_fail "VARIANT_ID not set (91-image-info.sh)"; fi

echo "=== Build deps removed ==="
for pkg in gcc gcc-c++ cmake; do
  if rpm -q "$pkg" >/dev/null 2>&1; then check_fail "$pkg still installed"; else check_pass "$pkg removed"; fi
done

echo "=== Size sanity ==="
SIZE_MB=$(du -sm /usr/lib/hermes-agent | cut -f1)
echo "  /usr/lib/hermes-agent: ${SIZE_MB} MB"
if [ "${SIZE_MB}" -gt 4000 ]; then check_fail "hermes tree larger than 4 GB, check extras"; else check_pass "hermes tree size ok"; fi

if [ "${FAILURES}" -ne 0 ]; then
  echo "=== ${FAILURES} test(s) FAILED ==="
  exit 1
fi
echo "=== all tests passed ==="
