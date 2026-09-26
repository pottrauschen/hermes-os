#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Agent-Schicht: Plugin, Skill, Config-Vorlage, Dienst, First-Login
# =============================================================================
# Die Dateien selbst liegen unter files/system/ und wurden von build.sh
# bereits nach / kopiert. Hier: Rechte setzen, Presets, Autostart.
# =============================================================================
set -xeuo pipefail

SHARE=/usr/share/hermes-os

# ---- Rechte ------------------------------------------------------------------
chmod 0755 /usr/libexec/hermes-os-first-login /usr/libexec/hermes-os-setup
chmod 0644 "${SHARE}/config.yaml.default" "${SHARE}/setup/"* /usr/share/applications/hermes-os-setup.desktop
find "${SHARE}/plugins" "${SHARE}/skills" -type f -exec chmod 0644 {} +
find "${SHARE}/plugins" "${SHARE}/skills" -type d -exec chmod 0755 {} +

# ---- ujust-Rezepte -----------------------------------------------------------
# Auroras /usr/bin/ujust ruft just mit /usr/share/ublue-os/just/00-entry.just
# auf (aus dem Aurora-common-Image). Die importiert eine feste Liste von
# Rezeptdateien plus optional 60-custom.just; ein Glob über das Verzeichnis
# gibt es nicht. Unsere Rezepte gehören also genau in diese Datei. Falls das
# Basis-Image sie schon mitbringt, hängen wir an, statt sie zu überschreiben.
JUST_DIR=/usr/share/ublue-os/just
mkdir -p "${JUST_DIR}"
if [ -f "${JUST_DIR}/60-custom.just" ]; then
  printf '\n# ---- hermes-os ----\n' >> "${JUST_DIR}/60-custom.just"
  cat "${SHARE}/hermes-os.just" >> "${JUST_DIR}/60-custom.just"
else
  cp "${SHARE}/hermes-os.just" "${JUST_DIR}/60-custom.just"
fi
chmod 0644 "${JUST_DIR}/60-custom.just"

# ---- Werkzeuge, die das Plugin und die Sprachschicht brauchen ---------------
# libnotify: notify-send für Hinweise aus dem First-Login-Skript.
# ffmpeg-free: Audio-Konvertierung für STT/TTS (Aurora bringt meist ffmpeg
#              mit; das Paket ist dann ein No-op).
dnf install -y libnotify ffmpeg-free || dnf install -y libnotify

# ---- systemd: User-Unit ist vorhanden, aber standardmäßig aus ---------------
# Das Gateway (Messaging, Cron, Sprachnachrichten auf Plattformen) startet
# erst, wenn `hermes setup` gelaufen ist. Aus ist es, weil das Image keinen
# WantedBy-Symlink mitliefert; ein User-Preset wäre wirkungslos, weil kein
# User-Manager preset-all ausführt. Das First-Login-Skript schaltet die Unit
# ein, sobald ein Provider konfiguriert ist.
chmod 0644 /usr/lib/systemd/user/hermes-gateway.service /usr/lib/environment.d/60-hermes-os.conf

# ---- Sicherheitsnetz: Hermes darf sich nicht selbst aktualisieren -----------
# Der Code liegt read-only unter /usr. `hermes update` würde scheitern; ein
# Hinweis in der MOTD sagt, wie Updates hier laufen.
mkdir -p /etc/motd.d
cat > /etc/motd.d/hermes-os <<'EOF'
hermes-os: Hermes ist Teil des System-Images. Updates kommen über
`ujust update` (neues Image), nicht über `hermes update`.
EOF
