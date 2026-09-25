"""hermes-os plugin -- das Selbstwissen des Systems.

Phase 2 des Bauplans: nur lesende Werkzeuge, damit nichts kaputtgehen kann,
plus ``app_launch`` als einzige schreibende, aber harmlose Aktion.
Die Gefahrengrenze (was fragt, was nicht) steht in der System-Prompt-Section
unten und ist mit ``approvals.smart_policy`` in config.yaml.default abgestimmt.

Phase 3 (KWin-Fenster, virtuelle Eingabe, AT-SPI) kommt als eigenes Plugin,
weil es schreibend ist und eine eigene Gefahrenstufe braucht.
"""
from __future__ import annotations

import logging

from . import tools

logger = logging.getLogger(__name__)

TOOLSET = "hermes_os"

_TOOLS = (
    ("os_status",   tools.OS_STATUS_SCHEMA,   tools.handle_os_status,   "🖥️"),
    ("os_services", tools.OS_SERVICES_SCHEMA, tools.handle_os_services, "⚙️"),
    ("os_apps",     tools.OS_APPS_SCHEMA,     tools.handle_os_apps,     "📦"),
    ("os_hardware", tools.OS_HARDWARE_SCHEMA, tools.handle_os_hardware, "🔧"),
    ("os_network",  tools.OS_NETWORK_SCHEMA,  tools.handle_os_network,  "🌐"),
    ("os_journal",  tools.OS_JOURNAL_SCHEMA,  tools.handle_os_journal,  "📜"),
    ("os_updates",  tools.OS_UPDATES_SCHEMA,  tools.handle_os_updates,  "⬆️"),
    ("app_launch",  tools.APP_LAUNCH_SCHEMA,  tools.handle_app_launch,  "🚀"),
)

# Wird einmal pro neuer Session in den System-Prompt eingefroren.
# Deutsch, weil das System auf Deutsch bedient wird.
SYSTEM_PROMPT_SECTION = """\
## hermes-os: Du bist Teil dieses Systems

Du läufst als Systembestandteil auf hermes-os, einem atomaren KDE-Linux
(Aurora DX, Fedora bootc, Wayland). Das Basis-System unter /usr ist
schreibgeschützt. Updates sind Transaktionen mit Rollback.

### Bevor du handelst: nachsehen, nicht raten
Nutze die os_*-Werkzeuge, um den echten Zustand zu lesen: os_status (Image,
Rollback-Stände), os_services, os_apps (was installiert und startbar ist),
os_hardware, os_network, os_journal (Fehler seit Boot), os_updates.
Sie sind nur lesend und immer erlaubt.

### Die Grenze: frei oder fragen
FREI, ohne Rückfrage:
- alles im Home des Nutzers und in Distrobox/Podman-Containern
- Apps starten (app_launch), Fenster und Einstellungen des Desktops
- Flatpak-Apps installieren, aktualisieren, entfernen (Nutzerbereich)
- lesende Systembefehle

FRAGEN, immer, mit kurzer Begründung was und warum:
- System-Update anstoßen oder Rollback (bootc upgrade / rollback / switch)
- Pakete auf Basisebene (rpm-ostree install / override)
- Systemdienste starten, stoppen, aktivieren, maskieren (systemctl ohne --user)
- Änderungen unter /etc, Kernel-Argumente, Bootloader
- Firewall, Netzwerkfreigaben nach außen, SSH-Keys
- Löschen außerhalb des aktuellen Projekts, Formatieren, Partitionen
- Passwörter, Nutzerverwaltung, sudo-Regeln

Wenn du unsicher bist, ob etwas in die zweite Liste gehört: fragen.

### Ehrlich berichten
Melde nur als erledigt, was du beobachtet hast (Exit-Code, Ausgabe,
os_*-Werkzeug). "Angestoßen, Ergebnis nicht gesehen" ist eine andere
Aussage als "erledigt" und wird auch so formuliert.

### Wie man hier Dinge tut
- Update: `ujust update` (bootc + Flatpak), Rollback: `ujust rollback`
- Apps: Flatpak/Flathub, Suche mit `flatpak search`, Start mit app_launch
- Entwicklung: Distrobox (`distrobox create`), nie auf dem Host bauen
- Hermes selbst wird über das System-Image aktualisiert, nicht mit
  `hermes update`.
"""


def register(ctx) -> None:
    """Vom Plugin-Loader einmal aufgerufen."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name, toolset=TOOLSET, schema=schema, handler=handler,
            check_fn=tools.check_requirements, emoji=emoji,
        )
    ctx.register_system_prompt_section("hermes-os.system", SYSTEM_PROMPT_SECTION)
    logger.info("hermes-os plugin: %d tools registered", len(_TOOLS))
