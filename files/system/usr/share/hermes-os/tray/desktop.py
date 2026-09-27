"""hermes-os -- gemeinsame Helfer für Kürzel und Benachrichtigungen des Leisten-Symbols.

Zwei Wege für globale Kürzel:

- **Desktop-Datei** unter /usr/share/kglobalaccel/ mit `X-KDE-Shortcuts`: kglobalacceld
  startet beim Drücken die gleichnamige Datei aus applications/ (so laufen Meta+H
  für das Fenster und Meta+Umschalt+H für „Was sehe ich hier?"). Nur Drücken, kein
  Loslassen; die zweite Instanz reicht den Befehl über den lokalen Socket weiter.
- **Anmeldung über D-Bus** bei org.kde.kglobalaccel (KF6): die laufende Instanz
  meldet eine Aktion an (doRegister, setShortcutKeys) und bekommt auf dem
  Komponenten-Objekt die Signale globalShortcutPressed und globalShortcutReleased.
  Nur so gibt es ein Loslassen, das Push-to-Talk (tray/voice.py) braucht. Das
  Kürzel erscheint in den Systemeinstellungen unter Tastenkürzel, Komponente
  „Hermes: Sprechen", und lässt sich dort ändern; kglobalacceld merkt sich die
  Wahl in ~/.config/kglobalshortcutsrc und gibt sie beim Anmelden zurück, die
  gespeicherte Wahl gewinnt also. kglobalacceld beobachtet seine Anmelder nicht:
  beim Beenden gibt setInactive das Kürzel frei, und wechselt der Besitzer von
  org.kde.kglobalaccel (KWin neu gestartet), meldet die Instanz sich neu an.
  Den Draht macht dbus_peer.py (Standardbibliothek).

Benachrichtigungen laufen über notify-send: einfache mit `notify`, mit Knöpfen
über `notify_actions` (notify-send -A wartet und schreibt die Wahl auf stdout,
wie bei Freigaben und Morgenbericht). KDE deutet im Text einfaches HTML, deshalb
werden &, < und > maskiert.

Alles hier kommt ohne Qt aus; tests/sehen-hoeren-check.py prüft Tastenfolgen,
Kollisionen, die Anmeldung gegen ein nachgebautes kglobalacceld auf einem
privaten Bus und die Benachrichtigung mit Knöpfen gegen ein nachgebautes
notify-send.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Eigene Komponente bei KGlobalAccel, absichtlich nicht „hermes-os-tray.desktop":
# unter dem Namen führt kglobalacceld die Desktop-Datei (Meta+H) als Dienst-
# Komponente, und die startet nur Programme, sendet aber keine Signale.
COMPONENT = "hermes-os-voice"
COMPONENT_LABEL = "Hermes: Sprechen"  # so heißt sie in den Systemeinstellungen unter Tastenkürzel

KGA_SERVICE = "org.kde.kglobalaccel"
KGA_PATH = "/kglobalaccel"
KGA_IFACE = "org.kde.KGlobalAccel"
KGA_COMPONENT_IFACE = "org.kde.kglobalaccel.Component"
SIGNAL_PRESSED = "globalShortcutPressed"
SIGNAL_RELEASED = "globalShortcutReleased"
# KGlobalAccel::SetShortcutFlag (kglobalshortcutinfo_p.h)
FLAG_SET_PRESENT = 2
FLAG_NO_AUTOLOADING = 4
FLAG_IS_DEFAULT = 8

NOTIFY_MAX_CHARS = 900

# ---- Tastenfolgen im Qt-Format -----------------------------------------------------------
# Qt::KeyboardModifier und Qt::Key, so wie QKeySequence sie als int zusammensetzt
# (Modifikator | Taste); KGlobalAccel überträgt Kürzel als a(ai), eine Liste von
# Tasten je Kürzel.
MODIFIERS = {"shift": 0x02000000, "ctrl": 0x04000000, "control": 0x04000000, "strg": 0x04000000,
             "alt": 0x08000000, "meta": 0x10000000, "super": 0x10000000, "win": 0x10000000}
KEY_NAMES = {
    "space": 0x20, "leertaste": 0x20, "escape": 0x01000000, "esc": 0x01000000, "tab": 0x01000001,
    "backspace": 0x01000003, "return": 0x01000004, "enter": 0x01000005, "insert": 0x01000006,
    "delete": 0x01000007, "del": 0x01000007, "pause": 0x01000008, "print": 0x01000009,
    "home": 0x01000010, "end": 0x01000011, "left": 0x01000012, "up": 0x01000013, "right": 0x01000014,
    "down": 0x01000015, "pageup": 0x01000016, "pgup": 0x01000016, "pagedown": 0x01000017, "pgdown": 0x01000017,
    "menu": 0x01000055, "volumeup": 0x01000072, "volumedown": 0x01000070, "volumemute": 0x01000071,
    "micmute": 0x01000113, "launchmail": 0x010000a0,
}
for _n in range(1, 36):
    KEY_NAMES[f"f{_n}"] = 0x01000030 + _n - 1

# Kürzel, die Plasma 6 (KWin, plasmashell, KRunner, Spectacle, Tastaturlayout)
# ab Werk belegt. Die Liste ist eine Sperre für unsere eigenen Vorschläge, kein
# vollständiges Verzeichnis; kglobalacceld meldet eine echte Kollision beim Anmelden.
PLASMA_DEFAULTS: Dict[str, str] = {
    "Alt+Space": "KRunner", "Alt+F2": "KRunner", "Meta+E": "Dateimanager", "Meta+T": "Terminal",
    "Meta+Q": "Aktivitäten", "Meta+D": "Arbeitsfläche zeigen", "Meta+L": "Bildschirm sperren",
    "Meta+V": "Zwischenablage", "Meta+W": "Übersicht", "Meta+G": "Fensterraster", "Meta+Tab": "Aktivitäten",
    "Meta+Shift+Print": "Spectacle: Bereich", "Meta+Print": "Spectacle: Fenster", "Print": "Spectacle",
    "Meta+Shift+S": "Spectacle: Bereich (neuere Plasma)", "Meta+Alt+K": "Tastaturlayout wechseln",
    "Meta+Ctrl+Space": "Emoji-Auswahl", "Meta+.": "Emoji-Auswahl", "Meta+Shift+V": "Zwischenablage", "Meta+H": "Hermes: Fenster",
    "Meta+PgUp": "Fenster maximieren", "Meta+PgDown": "Fenster minimieren", "Meta+Up": "Fenster maximieren",
    "Meta+Left": "Fenster links", "Meta+Right": "Fenster rechts", "Meta+Down": "Fenster wiederherstellen",
    "Meta+Space": "", "Meta+Shift+H": "",
}
OUR_SHORTCUTS = {"Meta+Space": "Hermes: Push-to-Talk", "Meta+Shift+H": "Hermes: Was sehe ich hier?"}


def normalize_key_text(text: str) -> str:
    """„meta+umschalt+h" -> „Meta+Shift+H", wie KDE es schreibt."""
    parts = [p.strip() for p in str(text or "").split("+") if p.strip()]
    if not parts:
        raise ValueError("leeres Kürzel")
    names = {"umschalt": "Shift", "shift": "Shift", "ctrl": "Ctrl", "strg": "Ctrl", "control": "Ctrl", "alt": "Alt",
             "meta": "Meta", "super": "Meta", "win": "Meta"}
    mods, key = [], ""
    for p in parts:
        low = p.lower()
        if low in names and p is not parts[-1]:
            mods.append(names[low])
        elif low in names and len(parts) == 1:
            raise ValueError(f"Kürzel ohne Taste: {text}")
        else:
            key = p
    if not key:
        raise ValueError(f"Kürzel ohne Taste: {text}")
    order = ["Meta", "Ctrl", "Alt", "Shift"]
    mods = [m for m in order if m in mods]
    klow = key.lower()
    if klow in ("leertaste", "space"):
        key = "Space"
    elif len(key) == 1:
        key = key.upper()
    else:
        key = key[0].upper() + key[1:]
    return "+".join(mods + [key])


def key_sequence_to_qt(text: str) -> int:
    """„Meta+Space" -> Qt-Wert (Modifikatoren | Taste); ValueError bei unbekannten Namen."""
    parts = [p.strip() for p in str(text or "").split("+") if p.strip()]
    if not parts:
        raise ValueError("leeres Kürzel")
    value = 0
    for mod in parts[:-1]:
        if mod.lower() not in MODIFIERS:
            raise ValueError(f"unbekannter Modifikator: {mod}")
        value |= MODIFIERS[mod.lower()]
    key = parts[-1]
    low = key.lower()
    if low in KEY_NAMES:
        value |= KEY_NAMES[low]
    elif len(key) == 1 and (key.isalnum() or key in "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"):
        value |= ord(key.upper())
    else:
        raise ValueError(f"unbekannte Taste: {key}")
    return value


def qt_to_key_text(value: int) -> str:
    """Rückweg für die Anzeige („Meta+Space")."""
    mods = []
    for name, bit in (("Meta", 0x10000000), ("Ctrl", 0x04000000), ("Alt", 0x08000000), ("Shift", 0x02000000)):
        if value & bit:
            mods.append(name)
    key = value & ~0x1E000000 & 0xFFFFFFFF
    names = {v: k for k, v in KEY_NAMES.items() if k not in ("leertaste", "esc", "del", "pgup", "pgdown")}
    if key in names:
        text = names[key]
        text = text[0].upper() + text[1:]
    elif 0x20 < key < 0x7F:
        text = chr(key)
    else:
        text = f"0x{key:x}"
    return "+".join(mods + [text])


def flatten_keys(value: Any) -> List[int]:
    """Tasten aus einer a(ai)-Antwort (Liste von Strukturen mit Listen) als flache Liste,
    Nullen (freie Plätze) ausgelassen."""
    out: List[int] = []
    if isinstance(value, bool):
        return out
    if isinstance(value, int):
        if value > 0:
            out.append(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(flatten_keys(item))
    return out


def collision(text: str) -> Optional[str]:
    """Wofür Plasma das Kürzel ab Werk benutzt, oder None, wenn es frei ist."""
    normalized = normalize_key_text(text)
    owner = PLASMA_DEFAULTS.get(normalized)
    return owner or None


# ---- Benachrichtigungen --------------------------------------------------------------
def escape_markup(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def shorten(text: str, limit: int = NOTIFY_MAX_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def notify_argv(title: str, body: str, icon: str = "hermes-os", urgency: str = "normal",
                actions: Sequence[Tuple[str, str]] = (), timeout_ms: Optional[int] = None,
                app: str = "Hermes") -> List[str]:
    argv = ["notify-send", f"--app-name={app}", f"--icon={icon}", f"--urgency={urgency}"]
    if timeout_ms is not None:
        argv.append(f"--expire-time={int(timeout_ms)}")
    for action_id, label in actions:
        argv += ["--action", f"{action_id}={label}"]
    argv += [title, escape_markup(shorten(body))]
    return argv


def notify(title: str, body: str, icon: str = "hermes-os", urgency: str = "normal", popen=subprocess.Popen) -> bool:
    """Benachrichtigung ohne Knöpfe, kehrt sofort zurück; False ohne notify-send."""
    if shutil.which("notify-send") is None:
        return False
    try:
        popen(notify_argv(title, body, icon, urgency), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              start_new_session=True)
    except OSError:
        return False
    return True


def notify_actions(title: str, body: str, actions: Sequence[Tuple[str, str]], on_choice: Callable[[str], None],
                   icon: str = "hermes-os", urgency: str = "normal", timeout_ms: Optional[int] = None,
                   popen=subprocess.Popen) -> Optional[threading.Thread]:
    """Benachrichtigung mit Knöpfen. notify-send wartet, bis die Benachrichtigung
    geschlossen ist, und schreibt die gewählte Aktion auf stdout; on_choice bekommt
    sie (oder "" ohne Wahl) aus einem Arbeitsthread. Das Symbol kann ein Pfad sein
    (Vorschau des Bildschirmausschnitts)."""
    if shutil.which("notify-send") is None:
        return None
    argv = notify_argv(title, body, icon, urgency, actions, timeout_ms)

    def work():
        choice = ""
        try:
            proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            out = proc.communicate()[0]
            choice = (out or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
            choice = choice[0].strip()
        except (OSError, ValueError):
            choice = ""
        if choice not in {a for a, _ in actions}:
            choice = ""
        on_choice(choice)

    thread = threading.Thread(target=work, name="hermes-notify", daemon=True)
    thread.start()
    return thread


# ---- Globales Kürzel mit Drücken und Loslassen über KGlobalAccel ----------------------------
class GlobalShortcut:
    """Eine Aktion bei kglobalacceld anmelden und Drücken/Loslassen als Rückrufe bekommen.

    install() verbindet sich mit dem Sitzungsbus (dbus_peer), meldet die Aktion an,
    setzt das Kürzel (mit SetPresent; ein vom Nutzer geändertes Kürzel aus
    kglobalshortcutsrc gewinnt, weil kglobalacceld die gespeicherte Belegung
    zurückgibt), bittet um die Signale der Komponente und hängt den Socket über
    `attach(make_notifier)` an eine Ereignisschleife. Die Rückrufe laufen im Thread,
    der read_ready() aufruft (im Leisten-Symbol der Qt-Hauptthread)."""

    def __init__(self, component: str, action: str, component_label: str, action_label: str, keys: str,
                 on_pressed: Callable[[], None], on_released: Callable[[], None],
                 bus_address: Optional[str] = None, service: str = KGA_SERVICE):
        self.component = component
        self.action = action
        self.component_label = component_label
        self.action_label = action_label
        self.keys = keys
        self.on_pressed = on_pressed
        self.on_released = on_released
        self._bus_address = bus_address
        self._service = service
        self.conn = None
        self.component_path = ""
        self.active_keys = ""
        self.error = ""
        self.warning = ""
        self._wanted = 0
        self.qt_refs: Any = None

    @property
    def action_id(self) -> List[str]:
        return [self.component, self.action, self.component_label, self.action_label]

    def install(self) -> bool:
        import dbus_peer as dp
        try:
            self._wanted = key_sequence_to_qt(self.keys)
        except ValueError as exc:
            self.error = str(exc)
            return False
        try:
            conn = dp.BusConnection(self._bus_address)
        except (OSError, dp.DBusError, ValueError) as exc:
            self.error = f"kein Sitzungsbus: {exc}"
            return False
        self.conn = conn
        if not self._register():
            self.conn = None
            conn.close()
            return False
        try:
            conn.add_match(f"type='signal',interface='{KGA_COMPONENT_IFACE}',sender='{self._service}'")
            conn.add_match("type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',"
                           f"member='NameOwnerChanged',arg0='{self._service}'")
        except (OSError, dp.DBusError) as exc:
            self.error = f"Signale nicht abonniert: {exc}"
            self.conn = None
            conn.close()
            return False
        conn.subscribe(None, KGA_COMPONENT_IFACE, SIGNAL_PRESSED, self._pressed)
        conn.subscribe(None, KGA_COMPONENT_IFACE, SIGNAL_RELEASED, self._released)
        conn.subscribe(None, "org.freedesktop.DBus", "NameOwnerChanged", self._owner_changed)
        return True

    def _register(self) -> bool:
        """Wie KGlobalAccel::updateGlobalShortcut in KF6: anmelden, Kürzel als vorhanden
        setzen (die gespeicherte Belegung aus kglobalshortcutsrc gewinnt), Komponente
        holen, Vorgabe eintragen. Danach steht in active_keys, was wirklich gilt."""
        import dbus_peer as dp
        conn = self.conn
        try:
            conn.call(self._service, KGA_PATH, KGA_IFACE, "doRegister", "as", (self.action_id,))
            # a(ai): eine Liste von Kürzeln, jedes eine Struktur mit den bis zu vier Tasten
            keys = [([self._wanted],)]
            result = conn.call(self._service, KGA_PATH, KGA_IFACE, "setShortcutKeys", "asa(ai)u",
                               (self.action_id, keys, FLAG_SET_PRESENT))
            path = conn.call(self._service, KGA_PATH, KGA_IFACE, "getComponent", "s", (self.component,))
            conn.call(self._service, KGA_PATH, KGA_IFACE, "setShortcutKeys", "asa(ai)u",
                      (self.action_id, keys, FLAG_IS_DEFAULT))
        except (OSError, dp.DBusError, ValueError) as exc:
            self.error = f"KGlobalAccel nicht erreichbar: {exc}"
            return False
        self.component_path = str(path[0]) if path else ""
        active = flatten_keys(result[0] if result else [])
        self.active_keys = ", ".join(qt_to_key_text(k) for k in active) if active else ""
        if not active:
            self.error = f"{self.keys} wurde von KGlobalAccel nicht angenommen (belegt?)"
            return False
        # Seit Plasma 6.7 speichert kglobalacceld ein belegtes Kürzel trotzdem, und die
        # zuerst angemeldete Aktion gewinnt still; deshalb nachfragen und es sagen.
        self.warning = ""
        try:
            free = conn.call(self._service, KGA_PATH, KGA_IFACE, "globalShortcutAvailable", "(ai)s",
                             ((active[:1],), self.component))
            if free and free[0] is False:
                self.warning = (f"{self.active_keys} ist schon vergeben; in den Systemeinstellungen unter "
                                f"Tastenkürzel, {self.component_label}, ein anderes wählen")
        except (OSError, dp.DBusError, ValueError):
            pass
        return True

    def _owner_changed(self, msg) -> None:
        # (s name, s old_owner, s new_owner): ein neuer Besitzer kennt uns nicht mehr
        body = msg.body or []
        if len(body) >= 3 and body[0] == self._service and body[2]:
            self._register()

    def _mine(self, msg) -> bool:
        body = msg.body or []
        return len(body) >= 2 and body[0] == self.component and body[1] == self.action

    def _pressed(self, msg) -> None:
        if self._mine(msg):
            self.on_pressed()

    def _released(self, msg) -> None:
        if self._mine(msg):
            self.on_released()

    def fileno(self) -> int:
        return self.conn.fileno()

    def read_ready(self) -> bool:
        """Von der Ereignisschleife, wenn der Socket lesbar ist; False, wenn der Bus weg ist."""
        if self.conn is None:
            return False
        try:
            alive = self.conn.read_ready()
        except (OSError, ValueError) as exc:
            self.error = f"D-Bus-Verbindung gestört: {exc}"
            alive = False
        if not alive:
            self.close()
        return alive

    def attach_qt(self) -> None:
        """Socket an die Qt-Ereignisschleife hängen (QSocketNotifier)."""
        from PySide6.QtCore import QSocketNotifier
        notifier = QSocketNotifier(self.fileno(), QSocketNotifier.Type.Read)

        def readable():
            if not self.read_ready():
                notifier.setEnabled(False)

        notifier.activated.connect(readable)
        self.qt_refs = notifier

    def close(self) -> None:
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.call(self._service, KGA_PATH, KGA_IFACE, "setInactive", "as", (self.action_id,))
            except Exception:
                pass
            conn.close()


def self_test() -> List[str]:
    """Netzfreier Selbsttest für `hermes-os-tray --check`."""
    problems: List[str] = []
    try:
        if key_sequence_to_qt("Meta+Space") != 0x10000020 or key_sequence_to_qt("Meta+Shift+H") != 0x12000048:
            problems.append("key_sequence_to_qt: Meta+Space oder Meta+Shift+H falsch")
        if qt_to_key_text(0x10000020) != "Meta+Space" or qt_to_key_text(0x12000048) != "Meta+Shift+H":
            problems.append("qt_to_key_text: Rückweg falsch")
    except ValueError as exc:
        problems.append(f"key_sequence_to_qt: {exc}")
    for text in OUR_SHORTCUTS:
        if collision(text):
            problems.append(f"{text} kollidiert mit {collision(text)}")
    argv = notify_argv("T", "a < b", actions=[("x", "X")])
    if argv[-1] != "a &lt; b" or "--action" not in argv:
        problems.append(f"notify_argv: {argv}")
    return problems


if __name__ == "__main__":
    errs = self_test()
    for e in errs:
        print("FEHL ", e)
    print("OK    desktop Selbsttest" if not errs else "ERGEBNIS: Fehler")
    sys.exit(1 if errs else 0)
