# hermes-os -- ujust-Rezepte. 20-agent-layer.sh legt diese Datei als
# /usr/share/ublue-os/just/60-custom.just ab, die einzige Datei, die Auroras
# ujust zusätzlich zu seiner festen Liste importiert.

# Hermes einrichten: Fenster für Anbieter, Schlüssel und Modell
hermes-setup:
    /usr/libexec/hermes-os-setup

# Hermes im Terminal einrichten (voller Wizard: Modell, TTS, Terminal, Gateway, Tools)
hermes-setup-terminal:
    /usr/bin/hermes setup

# Hermes-Fenster öffnen (sonst: Symbol in der Systemleiste oder Meta+H)
hermes-tray:
    /usr/libexec/hermes-os-tray --show

# Hermes-Dashboard als Fenster öffnen (Web-Oberfläche: Modelle, Schlüssel, Sessions, Cron, Plugins)
hermes-dashboard:
    /usr/libexec/hermes-os-dashboard

# Hermes-Diagnose
hermes-doctor:
    /usr/bin/hermes doctor

# Gateway (Messaging, Cron, Sprachnachrichten auf Plattformen) als Nutzerdienst einschalten
hermes-gateway-enable:
    systemctl --user reenable hermes-gateway.service
    systemctl --user start hermes-gateway.service
    systemctl --user status hermes-gateway.service --no-pager

# Sprache am Desktop: Push-to-Talk im Terminal (lokale Erkennung und Ausgabe)
hermes-voice:
    @echo "Im Chat eingeben: /voice on   (Push-to-Talk, faster-whisper + piper lokal)"
    /usr/bin/hermes

# Gateway ausschalten
hermes-gateway-disable:
    systemctl --user disable --now hermes-gateway.service

# Gateway-Status und letzte Logzeilen
hermes-gateway-status:
    systemctl --user status hermes-gateway.service --no-pager || true
    journalctl --user -u hermes-gateway.service -n 30 --no-pager

# Welches Hermes steckt im Image?
hermes-os-info:
    @echo "Image:"
    @grep -E '^(PRETTY_NAME|VARIANT_ID|IMAGE_VERSION)=' /usr/lib/os-release
    @echo
    @echo "Hermes:"
    @/usr/bin/hermes --version
    @cat /usr/lib/hermes-agent/.hermes-os-release

# Nutzer-Einrichtung erneut ausführen (Plugin, Skill, Config-Vorlage)
hermes-os-relink:
    /usr/libexec/hermes-os-first-login
    @tail -5 ~/.hermes/hermes-os-first-login.log

# Morgenbericht einschalten: täglich eine Benachrichtigung zum Systemzustand (Uhrzeit HH:MM, Vorgabe 08:30)
hermes-morgenbericht-ein zeit="":
    #!/usr/bin/bash
    set -euo pipefail
    zeit={{ quote(zeit) }}
    if [ -z "$zeit" ] && [ -t 0 ]; then
        read -r -p "Uhrzeit für den Morgenbericht (HH:MM) [08:30]: " zeit || true
    fi
    zeit="${zeit:-08:30}"
    if [[ ! "$zeit" =~ ^([01]?[0-9]|2[0-3]):([0-5][0-9])$ ]]; then
        echo "Uhrzeit bitte als HH:MM angeben, etwa: ujust hermes-morgenbericht-ein 07:45"
        exit 1
    fi
    stunde=$((10#${BASH_REMATCH[1]}))
    minute=$((10#${BASH_REMATCH[2]}))
    # Hermes führt Skript-Jobs nur aus ~/.hermes/scripts aus (auch kein Symlink
    # nach draußen); die Datei springt nur ins Image, die Logik bleibt dort.
    scripts="${HERMES_HOME:-$HOME/.hermes}/scripts"
    mkdir -p "$scripts"
    printf '%s\n' '#!/usr/bin/bash' \
        '# hermes-os: Morgenbericht, angelegt von ujust hermes-morgenbericht-ein.' \
        '# Die Logik liegt im Image (/usr/libexec/hermes-os-morgenbericht).' \
        'exec /usr/libexec/hermes-os-morgenbericht' > "$scripts/hermes-os-morgenbericht.sh"
    for _ in 1 2 3 4 5; do
        /usr/bin/hermes cron remove hermes-os-morgenbericht >/dev/null 2>&1 || break
    done
    # Skript-Job ohne Modell: kostet nichts, braucht keinen Anbieter, darf nichts ändern.
    # deliver local: nichts an Messaging-Plattformen, die Ausgabe liegt unter ~/.hermes/cron/output.
    if ! out="$(/usr/bin/hermes cron create "$minute $stunde * * *" --name hermes-os-morgenbericht \
            --script hermes-os-morgenbericht.sh --no-agent --deliver local 2>&1)"; then
        echo "$out"
        echo "Morgenbericht nicht eingerichtet."
        exit 1
    fi
    printf 'Morgenbericht eingeschaltet: täglich um %02d:%02d (Zeitzone des Systems oder timezone in ~/.hermes/config.yaml).\n' "$stunde" "$minute"
    echo "Probelauf ohne Benachrichtigung: /usr/libexec/hermes-os-morgenbericht --probe"
    if ! systemctl --user is-active --quiet hermes-gateway.service 2>/dev/null; then
        echo "Hinweis: Das Gateway läuft nicht; ohne Gateway kommt kein Bericht. Einschalten: ujust hermes-gateway-enable"
    fi

# Morgenbericht ausschalten
hermes-morgenbericht-aus:
    #!/usr/bin/bash
    set -uo pipefail
    n=0
    for _ in 1 2 3 4 5; do
        /usr/bin/hermes cron remove hermes-os-morgenbericht >/dev/null 2>&1 || break
        n=$((n + 1))
    done
    rm -f "${HERMES_HOME:-$HOME/.hermes}/scripts/hermes-os-morgenbericht.sh"
    if [ "$n" -gt 0 ]; then
        echo "Morgenbericht ausgeschaltet."
    else
        echo "Es war kein Morgenbericht eingerichtet."
    fi
