# hermes-os -- ujust-Rezepte. 20-agent-layer.sh legt diese Datei als
# /usr/share/ublue-os/just/60-custom.just ab, die einzige Datei, die Auroras
# ujust zusätzlich zu seiner festen Liste importiert.

# Hermes einrichten (Provider, Modell, Tools)
hermes-setup:
    /usr/bin/hermes setup

# Hermes-Diagnose
hermes-doctor:
    /usr/bin/hermes doctor

# Gateway (Sprache, Messaging, Cron) als Nutzerdienst einschalten
hermes-gateway-enable:
    systemctl --user enable --now hermes-gateway.service
    systemctl --user status hermes-gateway.service --no-pager

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
