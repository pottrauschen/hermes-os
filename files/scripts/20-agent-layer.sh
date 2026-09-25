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
chmod 0755 /usr/libexec/hermes-os-first-login
chmod 0644 "${SHARE}/config.yaml.default"
find "${SHARE}/plugins" "${SHARE}/skills" -type f -exec chmod 0644 {} +
find "${SHARE}/plugins" "${SHARE}/skills" -type d -exec chmod 0755 {} +

# ---- Werkzeuge, die das Plugin und die Sprachschicht brauchen ---------------
# libnotify: notify-send für Hinweise aus dem First-Login-Skript.
# ffmpeg-free: Audio-Konvertierung für STT/TTS (Aurora bringt meist ffmpeg
#              mit; das Paket ist dann ein No-op).
dnf install -y libnotify ffmpeg-free || dnf install -y libnotify

# ---- systemd: User-Unit bleibt vorhanden, aber standardmäßig aus ------------
# Das Gateway (Sprache, Messaging) startet erst, wenn `hermes setup` gelaufen
# ist. Das First-Login-Skript schaltet es dann ein.
mkdir -p /usr/lib/systemd/user-preset
cat > /usr/lib/systemd/user-preset/90-hermes-os.preset <<'EOF'
disable hermes-gateway.service
EOF

# ---- Sicherheitsnetz: Hermes darf sich nicht selbst aktualisieren -----------
# Der Code liegt read-only unter /usr. `hermes update` würde scheitern; ein
# Hinweis in der MOTD sagt, wie Updates hier laufen.
mkdir -p /etc/motd.d
cat > /etc/motd.d/hermes-os <<'EOF'
hermes-os: Hermes ist Teil des System-Images. Updates kommen über
`ujust update` (neues Image), nicht über `hermes update`.
EOF
