"""hermes-os -- Sprache der Texte aus der Grenze (boundary.py) und dem Protokoll
(audit.py): Deutsch ab Werk, Englisch, wenn die Sitzung englisch ist.

Gegenstück zu tray/lang.py, aber eigenständig: das Plugin läuft im Gateway mit
der Umgebung der Sitzung, das Leisten-Symbol lädt audit.py über seinen Pfad
(HERMES_OS_AUDIT_PY); keiner der beiden Wege kennt den anderen Ordner. is_english
ist eine Code-Kopie von tray/lang.py, tests/lang-check.py prüft den Gleichlauf.
Der deutsche Text ist der Schlüssel, EN liefert den englischen dazu; Konstanten
bleiben deutsch, übersetzt wird beim Gebrauch. Nur Standardbibliothek, kein Qt.
"""
from __future__ import annotations

import os
from typing import Dict

_LANG_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def is_english(env=None) -> bool:
    """Englisch, wenn HERMES_OS_LANG mit en beginnt; mit de beginnend deutsch.
    Sonst entscheidet der erste nicht leere Wert aus LANGUAGE (nur der Eintrag vor
    dem ersten Doppelpunkt), LC_ALL, LC_MESSAGES und LANG: englisch, wenn er mit en
    beginnt. Liest die Umgebung bei jedem Aufruf, ohne Zwischenspeicher."""
    env = os.environ if env is None else env
    forced = str(env.get("HERMES_OS_LANG") or "").strip().lower()
    if forced.startswith("en"):
        return True
    if forced.startswith("de"):
        return False
    for name in _LANG_VARS:
        value = str(env.get(name) or "").strip()
        if name == "LANGUAGE":
            value = value.split(":", 1)[0].strip()
        if value:
            return value.lower().startswith("en")
    return False


EN: Dict[str, str] = {
    # ---- boundary.py: was ein Befehl tut (Freigabe-Karte, Benachrichtigung) ------------
    "würde den Rechner neu starten oder ausschalten": "would restart or power off the computer",
    "würde den Rechner in den Ruhezustand schicken": "would put the computer to sleep",
    "öffnet eine Root-Shell": "opens a root shell",
    "läuft mit Root-Rechten": "runs with root privileges",
    "ändert das System-Image": "changes the system image",
    "steuert Systemdienste": "controls system services",
    "ändert Firewall oder Netzwerk": "changes the firewall or network",
    "ändert Nutzer oder Passwörter": "changes users or passwords",
    "ändert Bootloader oder Kernel-Argumente": "changes the bootloader or kernel arguments",
    "erzeugt oder verteilt SSH-Schlüssel": "creates or distributes SSH keys",
    "berührt Datenträger oder Partitionen": "touches disks or partitions",
    "schreibt in Systempfade (/etc, /usr, /boot, /var/lib, /ostree)":
        "writes to system paths (/etc, /usr, /boot, /var/lib, /ostree)",
    "ändert die systemweite Flatpak-Installation": "changes the system-wide Flatpak installation",
    "ändert systemweite Einstellungen": "changes system-wide settings",
    "beendet Sitzungen": "ends sessions",
    "lädt oder entfernt Kernel-Module": "loads or removes kernel modules",
    "ändert SELinux": "changes SELinux",
    "startet ein ujust-Rezept mit möglicher Systemwirkung": "runs a ujust recipe that may affect the system",
    "ist zu tief verschachtelt, um ihn zu prüfen": "is nested too deeply to check",
    "spielt Firmware ein": "installs firmware",
    "berührt das laufende System": "touches the running system",
    # Die Backticks um den Befehl bleiben: tray/hermes_client.approval_command liest ihn daraus
    "hermes-os: `{seg}` {what} ({group}). Freigabe nötig.":
        "hermes-os: `{seg}` {what} ({group}). Approval required.",
    "hermes-os: `{seg}` {what} ({group}). Das führt der Agent nie selbst aus. "
    "Bitte den Nutzer, es selbst zu tun.":
        "hermes-os: `{seg}` {what} ({group}). The agent never runs this itself. Ask the user to do it.",
    "hermes-os: Die Grenzprüfung ist fehlgeschlagen ({error}). "
    "Freigabe nötig, weil nicht feststeht, ob der Befehl das System berührt.":
        "hermes-os: The boundary check failed ({error}). "
        "Approval required because it is unclear whether the command touches the system.",

    # ---- audit.py: Zeitraum, Gruppen, Entscheidungen, Ergebnis --------------------------
    "Heute": "Today",
    "Letzte 7 Tage": "Last 7 days",
    "Alles": "All",
    "Image und Updates": "Image and updates",
    "Systemdienste": "System services",
    "Firewall und Netz": "Firewall and network",
    "Nutzer und Passwörter": "Users and passwords",
    "Bootloader und Kernel": "Bootloader and kernel",
    "SSH-Schlüssel": "SSH keys",
    "Datenträger": "Disks",
    "Systemdateien": "System files",
    "Flatpak systemweit": "Flatpak system-wide",
    "Sprache, Zeit, Rechnername": "Language, time, hostname",
    "Root-Shell": "Root shell",
    "Neustart und Ausschalten": "Restart and power off",
    "Ruhezustand": "Sleep",
    "Mit Root-Rechten": "With root privileges",
    "Sitzungen": "Sessions",
    "Kernel-Module": "Kernel modules",
    "Firmware": "Firmware",
    "SELinux": "SELinux",
    "ujust-Rezept": "ujust recipe",
    "Zu tief verschachtelt": "Nested too deeply",
    "Grenzprüfung gescheitert": "Boundary check failed",
    "Hermes-Gefahrenerkennung": "Hermes danger detection",
    "App-Start": "App launch",
    "Einmal erlaubt": "Allowed once",
    "Für die Sitzung erlaubt": "Allowed for the session",
    "Immer erlaubt": "Always allowed",
    "Abgelehnt": "Denied",
    "Zeitüberschreitung": "Timed out",
    "Zurückgezogen": "Withdrawn",
    "Nicht zustellbar": "Not deliverable",
    "Vom Guardian erlaubt": "Allowed by Guardian",
    "Vom Guardian abgelehnt": "Denied by Guardian",
    "Guardian fragt nach": "Guardian asks",
    "Verweigert": "Refused",
    "Blockiert": "Blocked",
    "Ohne Rückfrage": "Without asking",
    "Ausgeführt": "Executed",
    "Mit Fehler beendet": "Ended with error",
    "Nicht ausgeführt": "Not executed",
    "Wartet": "Waiting",
    "Erlaubt, Ergebnis fehlt": "Allowed, result missing",
    "Gestartet": "Launched",
    "Start fehlgeschlagen": "Launch failed",
    # Wer entschieden hat
    "Guardian": "Guardian",
    "Cron-Verweigerung": "cron refusal",
    "niemand erreichbar": "no one reachable",
    "Nutzer": "user",
    "Nutzer im Leisten-Symbol": "user in tray icon",
    "gespeicherte Freigabe": "saved approval",
    "keine Antwort": "no answer",
    ", Exit {code}": ", exit {code}",
    # Datum der Zeile; muss zu qsTr("dd.MM.yyyy") in tray/Main.qml passen
    "%d.%m.%Y": "%Y-%m-%d",
    # ---- audit.py: Export -----------------------------------------------------------------
    "%d.%m.%Y %H:%M": "%Y-%m-%d %H:%M",
    "Protokoll von Hermes auf {host}, erstellt am {stamp}": "Hermes log on {host}, created {stamp}",
    "Zeitraum: {period}; ": "Period: {period}; ",
    "nur Änderungen am System": "only changes to the system",
    "alle Einträge": "all entries",
    "1 Eintrag": "1 entry",
    "{count} Einträge": "{count} entries",
    "Keine Einträge.": "No entries.",
    "  App: ": "  App: ",
    # „failed“ muss drinstehen: die Seite Protokoll färbt die Meldung daran rot
    "Export fehlgeschlagen: {err}": "Export failed: {err}",
}


def _(text: str) -> str:
    """Text in der Sprache der Sitzung: englisch aus EN, sonst der deutsche Quelltext.
    Unbekannte Texte bleiben, wie sie sind."""
    if is_english():
        return EN.get(text, text)
    return text
