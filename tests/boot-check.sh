#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Prüfungen nach dem Boot, per SSH in der Test-VM (nur lesend)
# =============================================================================
# Deckt die Punkte der Boot-Checkliste ab, die ohne grafische Sitzung gehen:
# Image und Version, Hermes aus der read-only Venv, Plugin und Skill im Image,
# ujust-Rezepte, Umgebung der User-Instanz, Boot-Fehler im Journal. Was eine
# Sitzung braucht (First-Login, Freigabe-Dialog, Sprache, AT-SPI), wird nur
# geprüft, wenn der aufrufende Nutzer grafisch angemeldet ist.
#
# Aufruf vom Arbeitsplatz:
#   ssh stephan@<vm> 'bash -s' < tests/boot-check.sh [erwartete-version]
# Die erwartete Version ist das Label org.opencontainers.image.version, das
# build-qcow2.sh vor dem Bau ausgibt (z. B. 44.20260922.1.20260925).
# =============================================================================
set -uo pipefail
EXPECT="${1:-}"
fail=0
ok()   { echo "OK    $*"; }
warn() { echo "WARN  $*"; }
bad()  { echo "FEHL  $*"; fail=1; }

echo "== Image =="
grep -E '^(PRETTY_NAME|IMAGE_VERSION|VARIANT_ID)=' /usr/lib/os-release
booted=""
if status=$(rpm-ostree status --json 2>/dev/null); then
  booted=$(printf '%s' "$status" | python3 -c 'import json,sys; d=[x for x in json.load(sys.stdin)["deployments"] if x.get("booted")][0]; print(d.get("container-image-reference",""), d.get("version",""))' 2>/dev/null || true)
  [ -n "$booted" ] && ok "gebootet: $booted" || warn "rpm-ostree status ohne Deployment-Angabe"
else
  warn "rpm-ostree status nicht verfügbar; bootc status braucht root"
fi
if [ -n "$EXPECT" ]; then
  if printf '%s' "$booted" | grep -qF "$EXPECT"; then ok "erwartete Version $EXPECT gebootet"; else bad "gebootet ist nicht $EXPECT"; fi
fi

echo "== Hermes =="
[ -d /usr/lib/hermes-agent ] && ok "/usr/lib/hermes-agent vorhanden" || bad "/usr/lib/hermes-agent fehlt"
cat /usr/lib/hermes-agent/.hermes-os-release 2>/dev/null || warn ".hermes-os-release fehlt"
if v=$(/usr/bin/hermes --version 2>&1); then ok "hermes --version: $(printf '%s' "$v" | head -1)"; else bad "hermes --version: $v"; fi
/usr/bin/hermes update >/dev/null 2>&1; rc=$?
[ "$rc" -eq 2 ] && ok "hermes update verweigert mit Exit 2" || bad "hermes update Exit $rc, erwartet 2"
[ -w /usr/lib/hermes-agent ] && bad "/usr/lib/hermes-agent ist beschreibbar" || ok "Venv read-only"

echo "== Agent-Schicht im Image =="
for p in /usr/share/hermes-os/plugins/hermes_os/__init__.py /usr/share/hermes-os/plugins/hermes_os/plugin.yaml \
         /usr/share/hermes-os/skills/hermes-os-system/SKILL.md /usr/share/hermes-os/config.yaml.default \
         /usr/share/ublue-os/just/60-custom.just /usr/libexec/hermes-os-first-login \
         /etc/xdg/autostart/hermes-os-first-login.desktop /usr/lib/systemd/user/hermes-gateway.service \
         /usr/lib/environment.d/60-hermes-os.conf /usr/libexec/hermes-os-setup \
         /usr/share/hermes-os/setup/Main.qml /usr/share/applications/hermes-os-setup.desktop; do
  [ -e "$p" ] && ok "$p" || bad "$p fehlt"
done
n=$(ujust --list 2>/dev/null | grep -c 'hermes' || true)
[ "$n" -ge 5 ] && ok "ujust --list zeigt $n hermes-Rezepte" || bad "ujust --list zeigt nur $n hermes-Rezepte"

echo "== User-Instanz =="
if env=$(systemctl --user show-environment 2>/dev/null); then
  echo "$env" | grep -q '^HERMES_LAZY_INSTALL_TARGET=' && ok "HERMES_LAZY_INSTALL_TARGET in der User-Umgebung" || bad "HERMES_LAZY_INSTALL_TARGET fehlt in systemctl --user show-environment"
  ok "hermes-gateway: $(systemctl --user is-enabled hermes-gateway.service 2>&1) / $(systemctl --user is-active hermes-gateway.service 2>&1)"
else
  warn "keine User-Instanz erreichbar"
fi

echo "== Sitzung und First-Login =="
# Nur eine Sitzung des eigenen Nutzers auf seat0 zählt; Auroras Setup-Wizard
# läuft als Nutzer plasma-setup und wäre sonst ein falscher Treffer.
if loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$USER" '$3==u && $4=="seat0"' | grep -q .; then
  ok "grafische Sitzung von $USER vorhanden"
  if [ -f "$HOME/.hermes/hermes-os-first-login.log" ]; then
    ok "First-Login-Log:"; tail -8 "$HOME/.hermes/hermes-os-first-login.log"
    [ -L "$HOME/.hermes/plugins/hermes_os" ] && ok "Plugin verlinkt" || bad "Plugin nicht verlinkt"
    [ -L "$HOME/.hermes/skills/hermes-os-system" ] && ok "Skill verlinkt" || bad "Skill nicht verlinkt"
    [ -f "$HOME/.hermes/config.yaml" ] && ok "config.yaml vorhanden" || bad "config.yaml fehlt"
    /usr/bin/hermes plugins list 2>/dev/null | grep -i 'hermes.os' && ok "Plugin in hermes plugins list" || warn "Plugin nicht in hermes plugins list"
  else
    bad "First-Login-Log fehlt trotz Sitzung"
  fi
  if busctl --user tree org.a11y.atspi.Registry 2>/dev/null | grep -q '/org/a11y'; then ok "AT-SPI-Registry antwortet"; else warn "AT-SPI-Registry ohne Baum; Accessibility in den KDE-Einstellungen prüfen"; fi
else
  warn "keine grafische Sitzung von $USER; First-Login, AT-SPI und Sprache erst nach Anmeldung an der Konsole"
  if loginctl list-sessions --no-legend 2>/dev/null | grep -q plasma-setup; then
    warn "Auroras Ersteinrichtung läuft (Nutzer plasma-setup); Marker /etc/plasma-setup-done fehlt"
  fi
fi

echo "== Journal (dieser Boot, Fehler) =="
# Bekanntes Rauschen in der VM: agetty auf einer fehlenden seriellen Konsole,
# tmpfiles über die ostree-Symlinke /home /srv /root, udev-Regeln mit der
# Gruppe plugdev, kein Audio-Codec. Alles andere wird gezeigt.
# Dazu udev-Gruppen, die beim frühen Boot noch fehlen (disk, kvm, tss, ...),
# SELinux-Hinweise zu lsblk und chcon aus Aurora und grub-boot-success in der VM.
errs=$(journalctl -b -p err --no-pager -q 2>/dev/null | grep -vE 'agetty|systemd-tmpfiles.*already exists|plugdev|snd_hda_intel|Failed to resolve (group|user)|setroubleshoot|grub-boot-success' || true)
printf '%s\n' "$errs" | tail -15
echo "Fehlerzeilen ohne bekanntes Rauschen: $(printf '%s' "$errs" | grep -c . || true)"

echo
[ "$fail" -eq 0 ] && echo "ERGEBNIS: keine harten Fehler" || echo "ERGEBNIS: harte Fehler, siehe FEHL"
exit "$fail"
