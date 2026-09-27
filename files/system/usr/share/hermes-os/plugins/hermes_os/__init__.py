"""hermes-os plugin -- das Selbstwissen des Systems und die Freigabe-Grenze.

Phase 2 des Bauplans: nur lesende Werkzeuge, damit nichts kaputtgehen kann,
plus ``app_launch`` als einzige schreibende, aber harmlose Aktion.

Die Grenze (was fragt, was nicht) steht dreifach abgesichert:
1. als System-Prompt-Section, die der Agent in jeder Session liest,
2. als ``approvals.smart_policy`` in config.yaml.default für den Guardian,
   der aber nur Befehle sieht, die Hermes' eigener Detektor als gefährlich
   erkennt (rm -r, Schreiben nach /etc, systemctl stop/mask ...),
3. als ``pre_tool_call``-Hook hier, der die Befehle, die der Detektor NICHT
   kennt (bootc, rpm-ostree, ujust update, systemctl ohne --user, Nutzer-
   und Partitionsverwaltung), zwingend in Hermes' Freigabe-Dialog schickt.

Phase 3 (KWin-Fenster, virtuelle Eingabe, AT-SPI) kommt als eigenes Plugin,
weil es schreibend ist und eine eigene Gefahrenstufe braucht.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from . import audit, boundary, library, report, tools
from .boundary import classify_system_command  # noqa: F401  (Tests, Abwärtskompatibilität)

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
    ("os_locale",   tools.OS_LOCALE_SCHEMA,   tools.handle_os_locale,   "🌍"),
    ("app_launch",  tools.APP_LAUNCH_SCHEMA,  tools.handle_app_launch,  "🚀"),
)
# Bibliothek (library.py): Wissensquellen des Nutzers, eigener Abrufer, kein Root
_LIBRARY_TOOLS = (
    ("library_list",  library.LIBRARY_LIST_SCHEMA,  library.handle_library_list,  "📚"),
    ("library_fetch", library.LIBRARY_FETCH_SCHEMA, library.handle_library_fetch, "📖"),
    ("library_search", library.LIBRARY_SEARCH_SCHEMA, library.handle_library_search, "🔍"),
    ("library_mirror", library.LIBRARY_MIRROR_SCHEMA, library.handle_library_mirror, "🪞"),
)
# Morgenbericht (report.py): Zusammenfassung und Desktop-Benachrichtigung
_REPORT_TOOLS = (
    ("os_report",      report.OS_REPORT_SCHEMA,      report.handle_os_report,      "🌅"),
    ("desktop_notify", report.DESKTOP_NOTIFY_SCHEMA, report.handle_desktop_notify, "🔔"),
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
os_hardware, os_network, os_journal (Fehler seit Boot), os_updates,
os_locale (Sprache und Tastatur samt der Befehle zum Ändern).
Sie sind nur lesend, brauchen kein Root und sind immer erlaubt.

### Die Grenze: frei oder fragen
FREI, ohne Rückfrage:
- alles im Home des Nutzers und in Distrobox/Podman-Containern
- Apps starten (app_launch), Fenster und Einstellungen des Desktops
- Flatpak-Apps installieren, aktualisieren, entfernen
- systemctl --user (eigene Dienste), lesende Systembefehle

FRAGEN, immer, mit kurzer Begründung was und warum:
- System-Update anstoßen oder Rollback (ujust update, bootc, rpm-ostree)
- Pakete auf Basisebene (rpm-ostree install / override)
- Systemdienste starten, stoppen, aktivieren, maskieren (systemctl ohne --user)
- Änderungen unter /etc, /usr, /boot, Kernel-Argumente, Bootloader
- Firewall, Netzwerkfreigaben nach außen, SSH-Keys
- Löschen außerhalb des aktuellen Projekts, Formatieren, Partitionen
- Passwörter, Nutzerverwaltung, sudo-Regeln, Root-Shells
- Systemweite Sprache, Tastatur, Zeitzone, Rechnername (localectl,
  timedatectl, hostnamectl set-*)

Diese Befehle landen automatisch im Freigabe-Dialog des Nutzers; erkläre
dort in einem Satz, was passiert. Neustart und Herunterfahren führst du nie
selbst aus, du bittest den Nutzer darum. Wenn du unsicher bist, ob etwas in
die zweite Liste gehört: fragen.

### Ehrlich berichten
Melde nur als erledigt, was du beobachtet hast (Exit-Code, Ausgabe,
os_*-Werkzeug). "Angestoßen, Ergebnis nicht gesehen" ist eine andere
Aussage als "erledigt" und wird auch so formuliert.

### Wie man hier Dinge tut
- Update: `ujust update` (bootc + Flatpak), danach Reboot durch den Nutzer.
  Rollback: `sudo bootc rollback` (vorheriges Image beim nächsten Boot).
  Es gibt kein `ujust rollback`; `ujust rebase-helper` wechselt auf
  Upstream-Aurora und ist hier falsch.
- Apps: Flatpak/Flathub, Suche mit `flatpak search`, Start mit app_launch
- Sprache und Tastatur: erst os_locale lesen. Plasma-Tastatur steht in
  kxkbrc (`kwriteconfig6 --notify`, frei, sofort wirksam), Plasma-Sprache
  in plasma-localerc (frei, nach neuer Anmeldung); systemweit `sudo
  localectl set-x11-keymap`, `set-keymap`, `set-locale` (fragt).
  kdeglobals und kwinrc kennen keine Layout-Schlüssel.
- Entwicklung: Distrobox (`distrobox create`), nie auf dem Host bauen
- Hermes selbst wird über das System-Image aktualisiert, nicht mit
  `hermes update`.

### Die Oberfläche von hermes-os
hermes-os bringt eigene Fenster mit, über die der Nutzer mit dir redet:
Kontor am Leisten-Symbol (Meta+H), Freigaben als Kasten und
Benachrichtigung, "Was sehe ich hier?" (Meta+Umschalt+H), Sprechen
(Meta+Leertaste), "Hermes fragen" in KRunner, Bibliothek, Protokoll,
Dashboard, Einrichtungsassistent, Morgenbericht. Sie gehören zu hermes-os,
nicht zu Hermes Agent. Wie man sie öffnet: Skill hermes-os-system.
"""


# ---------------------------------------------------------------------------
# Freigabe-Hook: Befehle, die das laufende System berühren (boundary.py)
# ---------------------------------------------------------------------------

def _pre_tool_call(tool_name: str = "", args: Optional[Dict[str, Any]] = None, **_kw: Any) -> Optional[Dict[str, str]]:
    """Hermes' Vertrag (docs/grenze.md): {'action': 'approve', ...} schickt den
    Aufruf in den menschlichen Freigabe-Dialog, {'action': 'block', ...}
    verweigert ihn. Scheitert die Prüfung, fragt der Hook (fail-closed)."""
    try:
        if not isinstance(args, dict):
            return None
        if tool_name == "terminal":
            text = args.get("command")
        elif tool_name == "process_manage" and args.get("action") in ("write", "submit"):
            text = args.get("data")     # Text, der in eine Hintergrund-Shell getippt wird
        else:
            return None
        hit = boundary.classify_system_command(str(text or ""))
        if not hit:
            return None
        audit.record_flagged(hit, args, **_kw)  # Protokoll (audit.py): nur merken
        return boundary.directive_for(hit)
    except Exception as exc:  # pragma: no cover
        logger.warning("hermes-os pre_tool_call failed closed: %s", exc)
        return boundary.fail_closed_directive(exc)


def register(ctx) -> None:
    """Vom Plugin-Loader einmal aufgerufen."""
    for name, schema, handler, emoji in _TOOLS + _REPORT_TOOLS:
        ctx.register_tool(
            name=name, toolset=TOOLSET, schema=schema, handler=handler,
            check_fn=tools.check_requirements, emoji=emoji,
        )
    for name, schema, handler, emoji in _LIBRARY_TOOLS:
        ctx.register_tool(
            name=name, toolset=TOOLSET, schema=schema, handler=handler,
            check_fn=library.check_requirements, emoji=emoji,
        )
    ctx.register_system_prompt_section("hermes-os.system", SYSTEM_PROMPT_SECTION)
    # Die Bibliothek als Callable: wird bei jeder neuen Sitzung frisch gelesen.
    ctx.register_system_prompt_section("hermes-os.library", library.prompt_section)
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    audit.register_hooks(ctx, classify_system_command)  # Protokoll: Freigaben, Ergebnisse, app_launch
    logger.info("hermes-os plugin: %d tools, prompt sections and approval hook registered",
                len(_TOOLS) + len(_LIBRARY_TOOLS) + len(_REPORT_TOOLS))
