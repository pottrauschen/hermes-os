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
import re
import shlex
from typing import Any, Dict, Optional

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
- Entwicklung: Distrobox (`distrobox create`), nie auf dem Host bauen
- Hermes selbst wird über das System-Image aktualisiert, nicht mit
  `hermes update`.
"""


# ---------------------------------------------------------------------------
# Freigabe-Hook: Befehle, die das laufende System berühren
# ---------------------------------------------------------------------------

# (Gruppe, Regex auf den bereinigten Befehl). Bereinigt heißt: sudo/pkexec/
# env-Präfixe und `sh -c '...'`-Hüllen entfernt, Verkettungen aufgetrennt.
_SYSTEM_PATTERNS = (
    ("image", re.compile(r"^bootc\s+(upgrade|update|switch|rollback|install|edit|usr-overlay)\b")),
    ("image", re.compile(r"^rpm-ostree\s+(install|uninstall|override|kargs|rebase|rollback|deploy|upgrade|update|reset|initramfs|cleanup|cancel)\b")),
    ("image", re.compile(r"^ujust\s+(update|upgrade|update-system|rollback|rebase-helper|rollback-helper|toggle-updates|toggle-devmode)\b")),
    ("services", re.compile(r"^systemctl\s+(?:--\S+\s+)*(start|stop|restart|reload|reload-or-restart|enable|disable|mask|unmask|isolate|set-default|daemon-reload|edit|kill)\b")),
    ("network", re.compile(r"^(firewall-cmd|nft|iptables|ip6tables|ufw)\b")),
    ("users", re.compile(r"^(useradd|usermod|userdel|passwd|chpasswd|gpasswd|groupadd|groupdel|visudo|chsh|chage)\b")),
    ("boot", re.compile(r"^(grubby|grub2-mkconfig|grub2-install|dracut|bootc\s+kargs)\b")),
    ("ssh", re.compile(r"^ssh-keygen\b")),
    ("disks", re.compile(r"^(fdisk|sfdisk|parted|sgdisk|gdisk|wipefs|mkfs(\.\w+)?|mkswap|dd|cryptsetup|lvm|pvcreate|vgcreate|lvcreate)\b")),
    ("system-files", re.compile(r"^(tee|cp|mv|install|ln|rm|rmdir|chmod|chown|chattr|truncate|sed\s+-i\S*|touch|mkdir)\b.*\s/(etc|usr|boot|var/lib|ostree)(/|\s|$)")),
    ("flatpak-system", re.compile(r"^flatpak\s+(?:--\S+\s+)*(install|remove|uninstall|update|override|repair)\b.*\s(--system|-s)\b")),
)

# Root-Shells werden VOR dem Entfernen der Präfixe erkannt, weil `sudo -i`
# oder `sudo bash` sonst als leerer Rest durchrutschen würden.
_ROOT_SHELL_RE = re.compile(r"^(?:sudo|doas|pkexec)\s+(?:-[A-Za-z]+\s+)*(?:-i|-s|su|bash|sh|zsh|fish)\b(?!\s+-c)|^su\b(?!do)")
_PREFIX_RE = re.compile(r"^(?:(?:sudo|doas|pkexec)(?:\s+-[A-Za-z]+(?:\s+\S+)?)*\s+|env\s+(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+|nice\s+(?:-n\s*\S+\s+)?|nohup\s+|time\s+)+")
_SHELL_WRAP_RE = re.compile(r"^(?:ba|z|da)?sh\s+(?:-[a-zA-Z]*)?-?c\s+(.+)$")
_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")


def _strip_prefixes(segment: str) -> str:
    seg = segment.strip()
    for _ in range(4):
        new = _PREFIX_RE.sub("", seg, count=1)
        if new == seg:
            break
        seg = new.strip()
    return seg


def _unwrap_shell(segment: str) -> str:
    """`bash -c 'inner'` -> inner (eine Ebene)."""
    m = _SHELL_WRAP_RE.match(segment)
    if not m:
        return segment
    inner = m.group(1).strip()
    try:
        parts = shlex.split(inner)
        return parts[0] if len(parts) == 1 else inner.strip("'\"")
    except ValueError:
        return inner.strip("'\"")


def _segments(command: str):
    for raw in _SPLIT_RE.split(command):
        seg = _strip_prefixes(raw)
        if not seg:
            continue
        yield seg
        inner = _unwrap_shell(seg)
        if inner != seg:
            for sub in _SPLIT_RE.split(inner):
                sub = _strip_prefixes(sub)
                if sub:
                    yield sub


def classify_system_command(command: str) -> Optional[Dict[str, str]]:
    """Gibt {'group', 'segment'} zurück, wenn der Befehl das laufende System
    berührt, sonst None. Reine Lesebefehle und alles mit --user bleiben frei."""
    if not isinstance(command, str) or not command.strip():
        return None
    for raw in _SPLIT_RE.split(command):
        raw = raw.strip()
        if raw and _ROOT_SHELL_RE.match(raw):
            return {"group": "root-shell", "segment": raw}
    for seg in _segments(command):
        if seg.startswith("systemctl") and re.search(r"(^|\s)--user(\s|$)", seg):
            continue
        for group, pattern in _SYSTEM_PATTERNS:
            if pattern.search(seg):
                return {"group": group, "segment": seg}
    return None


def _pre_tool_call(tool_name: str = "", args: Optional[Dict[str, Any]] = None, **_kw: Any) -> Optional[Dict[str, str]]:
    """Hermes' Vertrag: {'action': 'approve', ...} schickt den Aufruf in den
    menschlichen Freigabe-Dialog (CLI-Prompt, Gateway /approve; ohne Mensch
    fail-closed, in Cron verweigert). Nie werfen, nie blocken."""
    try:
        if tool_name != "terminal" or not isinstance(args, dict):
            return None
        hit = classify_system_command(str(args.get("command") or ""))
        if not hit:
            return None
        return {
            "action": "approve",
            "message": f"hermes-os: `{hit['segment'][:120]}` berührt das laufende System ({hit['group']}). Freigabe nötig.",
            "rule_key": f"hermes-os:{hit['group']}",
        }
    except Exception as exc:  # pragma: no cover
        logger.warning("hermes-os pre_tool_call failed open: %s", exc)
        return None


def register(ctx) -> None:
    """Vom Plugin-Loader einmal aufgerufen."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name, toolset=TOOLSET, schema=schema, handler=handler,
            check_fn=tools.check_requirements, emoji=emoji,
        )
    ctx.register_system_prompt_section("hermes-os.system", SYSTEM_PROMPT_SECTION)
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    logger.info("hermes-os plugin: %d tools, prompt section and approval hook registered", len(_TOOLS))
