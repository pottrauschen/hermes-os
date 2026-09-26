"""Morgenbericht des hermes-os-Plugins: ``os_report`` und ``desktop_notify``.

``os_report`` fasst in wenigen Sätzen zusammen, was man morgens wissen will:
Update-Stand des Images (dieselbe Logik wie os_updates, aus tools.py),
Fehler im Journal seit dem letzten Bericht samt der Quellen, die neu dazu
gekommen sind, Plattenplatz auf /, /var und /home mit Schwellen,
fehlgeschlagene Dienste (System und Nutzer) und optional anstehende
Flatpak-Updates. Nur lesend, ohne Root. Einzige Schreibstelle ist der eigene
Zustand unter $XDG_STATE_HOME/hermes-os/morgenbericht.json: der Vergleichspunkt
für den nächsten Bericht (nur mit record=true) und der letzte Bericht, den
desktop_notify mit report=true zustellt.

``desktop_notify`` zeigt eine Desktop-Benachrichtigung über notify-send, auf
Wunsch mit dem Knopf „Im Chat besprechen". Wie bei den Freigaben des
Leisten-Symbols wartet notify-send auf die Wahl; die Wartezeit läuft in einer
eigenen transienten User-Unit, nicht im Gateway. Der Knopf ruft
``hermes-os-tray --discuss <datei>``, das Chat-Fenster öffnet sich mit dem
Bericht als Kontext. Ein Update stößt der Bericht nie selbst an; das geht
nur im Chat über die normale Freigabe.

Der tägliche Lauf ist ein Cron-Job des Gateways (ujust hermes-morgenbericht-ein,
docs/morgenbericht.md).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import tools

DISK_WARN_PERCENT = 85         # ab hier steht die Platte im Bericht
DISK_CRIT_PERCENT = 95         # ab hier „fast voll"
DISK_PATHS = ("/", "/var", "/home")
JOURNAL_MAX_ENTRIES = 5000
FIRST_WINDOW_HOURS = 24        # ohne früheren Bericht: so weit zurück
NOTIFY_KEEP_DAYS = 14          # Kontextdateien der Benachrichtigungen
TRAY = "/usr/libexec/hermes-os-tray"
TITLE = "Morgenbericht"
DISCUSS_LABEL = "Im Chat besprechen"

_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


# ---------------------------------------------------------------------------
# Zustand
# ---------------------------------------------------------------------------

def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "hermes-os"


def _state_file() -> Path:
    return state_dir() / "morgenbericht.json"


def load_state() -> Dict[str, Any]:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(data: Dict[str, Any]) -> Optional[str]:
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        return f"Zustand nicht gespeichert: {exc}"
    return None


def _now() -> float:
    return time.time()


def _when(ts: float, now: float) -> str:
    """„seit heute 07:12", „seit gestern 08:30", „seit Mo 21.09. 08:30"."""
    t = _dt.datetime.fromtimestamp(ts)
    today = _dt.datetime.fromtimestamp(now).date()
    hhmm = t.strftime("%H:%M")
    if t.date() == today:
        return f"seit heute {hhmm}"
    if t.date() == today - _dt.timedelta(days=1):
        return f"seit gestern {hhmm}"
    return f"seit {_WEEKDAYS[t.weekday()]} {t.strftime('%d.%m.')} {hhmm}"


def _stamp(ts: float) -> str:
    t = _dt.datetime.fromtimestamp(ts)
    return f"{_WEEKDAYS[t.weekday()]} {t.strftime('%d.%m.%Y %H:%M')}"


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def image_part() -> Tuple[str, List[str]]:
    """(Satz für die Kurzfassung, Zeilen für die Einzelheiten)."""
    st = tools.image_update_state()
    state, new = st.get("state"), st.get("new_version") or ""
    suffix = f" ({new})" if new else ""
    if state == "available":
        sentence = f"Neues Image verfügbar{suffix}."
    elif state == "staged":
        sentence = f"Neues Image liegt bereit, aktiv nach Neustart{suffix}."
    elif state == "current":
        sentence = "System-Image aktuell."
    elif state == "no-image":
        sentence = ""
    else:
        sentence = "Update-Stand unbekannt."
    details = [f"Image: {line}" for line in st.get("lines") or []]
    if state == "available":
        details.append("Einspielen fragt den Nutzer: ujust update, danach Neustart durch den Nutzer.")
    return sentence, details


def _journal_source(entry: Dict[str, Any]) -> str:
    unit = str(entry.get("_SYSTEMD_UNIT") or "")
    user_unit = str(entry.get("_SYSTEMD_USER_UNIT") or "")
    if user_unit and (not unit or unit.startswith("user@")):
        return user_unit
    if unit and not unit.startswith("session-"):
        return unit
    ident = str(entry.get("SYSLOG_IDENTIFIER") or "")
    if ident:
        return ident
    if entry.get("_TRANSPORT") == "kernel":
        return "kernel"
    return unit or "unbekannt"


def _journal_message(entry: Dict[str, Any]) -> str:
    msg = entry.get("MESSAGE")
    if isinstance(msg, list):  # journalctl gibt nicht druckbare Texte als Bytes-Liste aus
        try:
            msg = bytes(int(b) & 0xFF for b in msg).decode("utf-8", "replace")
        except (TypeError, ValueError):
            msg = ""
    return " ".join(str(msg or "").split())


def journal_errors(since: float) -> Dict[str, Any]:
    """Fehler (Priorität err und schlimmer) seit `since`, nach Quelle gezählt."""
    argv = ["journalctl", "--since", f"@{int(since)}", "-p", "err", "--no-pager", "-q", "-o", "json",
            "-n", str(JOURNAL_MAX_ENTRIES),
            "--output-fields=MESSAGE,_SYSTEMD_UNIT,_SYSTEMD_USER_UNIT,SYSLOG_IDENTIFIER,_TRANSPORT"]
    rc, out, err = tools._run_raw(argv, timeout=30)
    result: Dict[str, Any] = {"ok": False, "count": 0, "sources": {}, "samples": {}, "limited": False, "error": ""}
    if rc in (124, 126, 127):
        result["error"] = err.strip()
        return result
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        src = _journal_source(entry)
        result["sources"][src] = result["sources"].get(src, 0) + 1
        result["samples"][src] = _journal_message(entry)[:160]  # die jüngste Meldung je Quelle
        result["count"] += 1
    if rc != 0 and not result["count"]:
        result["error"] = f"journalctl exit {rc}: {err.strip()[:200]}"
        return result
    # Ohne wheel/adm/systemd-journal nur eigene Einträge, Hinweis kommt auf stderr (vgl. os_journal)
    result["limited"] = "Hint:" in err
    result["ok"] = True
    return result


def journal_part(since: float, now: float, previous: Optional[Dict[str, int]]) -> Tuple[str, List[str], Dict[str, int]]:
    j = journal_errors(since)
    when = _when(since, now) if previous is not None else f"in den letzten {FIRST_WINDOW_HOURS} Stunden"
    if not j["ok"]:
        return "Journal nicht lesbar.", [f"Journal: {j['error']}"], {}
    sources: Dict[str, int] = j["sources"]
    limited = " (nur eigene Einträge lesbar)" if j["limited"] else ""
    if not j["count"]:
        return f"Keine Fehler im Journal {when}{limited}.", [], sources
    n = j["count"]
    sentence = f"{n} Fehler im Journal {when}"
    new_sources = [s for s in sorted(sources, key=lambda s: (-sources[s], s)) if previous is not None and s not in previous]
    if new_sources:
        new_count = sum(sources[s] for s in new_sources)
        shown = ", ".join(new_sources[:3]) + (f" und {len(new_sources) - 3} weitere" if len(new_sources) > 3 else "")
        sentence += f", davon {new_count} neu: {shown}"
    elif previous is not None:
        sentence += ", keine neue Quelle"
    sentence += f"{limited}."
    details = ["Journal-Fehler nach Quelle:"]
    for src in sorted(sources, key=lambda s: (-sources[s], s))[:15]:
        mark = " (neu)" if src in new_sources else ""
        details.append(f"  {src}: {sources[src]}{mark}, zuletzt etwa: {j['samples'].get(src, '')}")
    if len(sources) > 15:
        details.append(f"  ... und {len(sources) - 15} weitere Quellen")
    if n >= JOURNAL_MAX_ENTRIES:
        details.append(f"  (auf die letzten {JOURNAL_MAX_ENTRIES} Einträge begrenzt)")
    return sentence, details, sources


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)  # pragma: no cover


def _disk_paths() -> List[str]:
    paths = [p for p in DISK_PATHS if os.path.exists(p)] or list(DISK_PATHS)
    if os.path.isdir("/sysroot"):
        paths.append("/sysroot")
    return paths


def disk_usage() -> Tuple[List[Dict[str, Any]], str]:
    """Belegung je Dateisystem, mehrere Pfade auf demselben Dateisystem zusammengefasst.

    Auf bootc ist / ein composefs-Abbild, das immer voll aussieht; gemessen wird
    dann /sysroot, das echte Wurzeldateisystem, unter dem Namen /."""
    paths = _disk_paths()
    rc, out, err = tools._run_raw(["df", "-B1", "--output=source,fstype,size,avail,pcent", *paths])
    if rc in (124, 126, 127):
        return [], err.strip()
    rows = [line.split() for line in out.splitlines()[1:] if line.strip()]
    if len(rows) != len(paths):
        return [], f"df: unerwartete Ausgabe (exit {rc}) {err.strip()[:200]}"
    by_path = dict(zip(paths, rows))
    if "/sysroot" in by_path:
        root = by_path.pop("/sysroot")
        if "/" in by_path and by_path["/"][1] in ("composefs", "overlay", "erofs"):
            by_path["/"] = root
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for path in [p for p in DISK_PATHS if p in by_path]:
        source, fstype, size, avail, pcent = by_path[path][:5]
        try:
            entry = {"size": int(size), "avail": int(avail), "percent": int(pcent.rstrip("%"))}
        except ValueError:
            continue
        g = groups.setdefault((source, size), {**entry, "paths": [], "fstype": fstype})
        g["paths"].append(path)
    return list(groups.values()), ""


def _join(items: List[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " und " + items[-1]


def disk_part() -> Tuple[str, List[str]]:
    groups, error = disk_usage()
    if not groups:
        return "Plattenplatz nicht lesbar.", [f"Platten: {error}"]
    details = ["Platten:"]
    warn = []
    for g in groups:
        details.append(f"  {_join(g['paths'])}: {g['percent']} % belegt, {_human_bytes(g['avail'])} frei ({g['fstype']})")
        if g["percent"] >= DISK_CRIT_PERCENT:
            warn.append(f"{_join(g['paths'])} fast voll ({g['percent']} %)")
        elif g["percent"] >= DISK_WARN_PERCENT:
            warn.append(f"{_join(g['paths'])} bei {g['percent']} %")
    if warn:
        return _join(warn) + ".", details
    return f"Plattenplatz ok (höchstens {max(g['percent'] for g in groups)} %).", details


def failed_units(user: bool) -> Tuple[Optional[List[str]], str]:
    argv = ["systemctl"] + (["--user"] if user else []) + ["list-units", "--failed", "--no-legend", "--plain", "--no-pager"]
    rc, out, err = tools._run_raw(argv)
    if rc != 0:
        return None, (err.strip() or f"exit {rc}")[:200]
    # --plain lässt das Markierungszeichen weg; ältere systemd setzen trotzdem „●"
    lines = [line.strip().lstrip("●*").strip() for line in out.splitlines()]
    return [line.split()[0] for line in lines if line and not line.startswith("0 ")], ""


def services_part() -> Tuple[str, List[str]]:
    system, e1 = failed_units(False)
    user, e2 = failed_units(True)
    details = []
    if system is None:
        details.append(f"Systemdienste nicht lesbar: {e1}")
    if user is None:
        details.append(f"Nutzerdienste nicht lesbar: {e2}")
    failed = [f"{u} (System)" for u in system or []] + [f"{u} (Nutzer)" for u in user or []]
    if failed:
        word = "Dienst" if len(failed) == 1 else "Dienste"
        return f"Fehlgeschlagen: {len(failed)} {word}, {_join(failed[:5])}" + (" und weitere" if len(failed) > 5 else "") + ".", details
    if system is None and user is None:
        return "Dienste nicht lesbar.", details
    return "Kein fehlgeschlagener Dienst.", details


_APP_ID_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2,}$")


def flatpak_part() -> Tuple[str, List[str]]:
    rc, out, err = tools._run_raw(tools.FLATPAK_UPDATES_ARGV, timeout=90)
    if rc == 127:
        return "", []
    if rc != 0:
        return "", [f"Flatpak-Updates nicht prüfbar: {err.strip()[:200] or f'exit {rc}'}"]
    ids = [line.split()[0] for line in out.splitlines() if line.strip() and _APP_ID_RE.match(line.split()[0])]
    if not ids:
        return "", ["Flatpak: keine Updates."]
    details = [f"Flatpak-Updates: {', '.join(ids[:20])}" + (f" und {len(ids) - 20} weitere" if len(ids) > 20 else "")]
    word = "Flatpak-Update" if len(ids) == 1 else "Flatpak-Updates"
    return f"{len(ids)} {word} verfügbar.", details


# ---------------------------------------------------------------------------
# os_report
# ---------------------------------------------------------------------------

OS_REPORT_SCHEMA = tools._schema(
    "os_report",
    "Morgenbericht: kurze deutsche Zusammenfassung des Systemzustands in wenigen Sätzen. "
    "Update-Stand des Images, Fehler im Journal seit dem letzten Bericht (mit neu "
    "hinzugekommenen Quellen), Plattenplatz auf /, /var und /home, fehlgeschlagene Dienste "
    "(System und Nutzer), optional Flatpak-Updates. Nur lesend, kein Root. Die Kurzfassung "
    "ist fertig formuliert und für eine Benachrichtigung gedacht (desktop_notify mit "
    "report=true); die Einzelheiten sind für Rückfragen. Nur der tägliche Cron-Lauf setzt "
    "record=true, damit der nächste Bericht mit diesem vergleicht.",
    {
        "record": {"type": "boolean",
                   "description": "Diesen Stand als Vergleichspunkt für den nächsten Bericht speichern. "
                                  "Standard false; nur der tägliche Lauf setzt true."},
        "flatpak": {"type": "boolean", "description": "Flatpak-Updates prüfen (braucht Netz). Standard true."},
    },
)


def build_report(record: bool = False, flatpak: bool = True) -> Dict[str, Any]:
    """Bericht bauen: {"summary", "text", "time"}; mit record den Vergleichspunkt setzen."""
    now = _now()
    state = load_state()
    baseline = state.get("baseline") if isinstance(state.get("baseline"), dict) else None
    previous_sources: Optional[Dict[str, int]] = None
    since = now - FIRST_WINDOW_HOURS * 3600
    if baseline:
        try:
            since = float(baseline["time"])
            previous_sources = {str(k): int(v) for k, v in (baseline.get("sources") or {}).items()}
        except (KeyError, TypeError, ValueError):
            previous_sources = None
    sentences: List[str] = []
    details: List[str] = []
    s, d = image_part()
    sentences.append(s); details += d
    s, d, sources = journal_part(since, now, previous_sources)
    sentences.append(s); details += d
    s, d = disk_part()
    sentences.append(s); details += d
    s, d = services_part()
    sentences.append(s); details += d
    if flatpak:
        s, d = flatpak_part()
        sentences.append(s); details += d
    summary = " ".join(x for x in sentences if x)
    text = (f"{TITLE}, {_stamp(now)}\n\nKurzfassung:\n{summary}\n\nEinzelheiten:\n" + "\n".join(details)).strip()
    report = {"time": now, "summary": summary, "text": text}
    new_state = dict(state)
    new_state["latest"] = report
    if record:
        new_state["baseline"] = {"time": now, "sources": sources}
    err = _save_state(new_state)
    if err:
        report["text"] += f"\n[{err}]"
    return report


def handle_os_report(args: Dict[str, Any], **_kw) -> str:
    args = args or {}
    report = build_report(record=bool(args.get("record", False)), flatpak=args.get("flatpak", True) is not False)
    return tools._clip(report["text"])


# ---------------------------------------------------------------------------
# desktop_notify
# ---------------------------------------------------------------------------

DESKTOP_NOTIFY_SCHEMA = tools._schema(
    "desktop_notify",
    "Zeigt eine Desktop-Benachrichtigung in der Plasma-Sitzung, auf Wunsch mit dem Knopf "
    "„Im Chat besprechen“, der das Hermes-Fenster mit dem Text als Kontext öffnet. Harmlos, "
    "ändert nichts am System. report=true stellt den letzten os_report zu (Titel, Kurzfassung, "
    "Einzelheiten als Kontext) und ist der Weg für den Morgenbericht.",
    {
        "title": {"type": "string", "description": "Überschrift, kurz. Bei report=true: Morgenbericht"},
        "body": {"type": "string", "description": "Text, ein bis drei Sätze. Bei report=true: die Kurzfassung"},
        "report": {"type": "boolean", "description": "Den letzten os_report zustellen statt title/body"},
        "discuss": {"type": "boolean", "description": "Knopf „Im Chat besprechen“ anbieten. Standard true"},
        "urgency": {"type": "string", "enum": ["low", "normal", "critical"], "description": "Standard: normal"},
    },
)


def _session_reachable() -> bool:
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return True
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.exists(os.path.join(runtime, "bus"))


def _prune_notify_dir(directory: Path, now: float) -> None:
    try:
        for f in directory.glob("*.txt"):
            if now - f.stat().st_mtime > NOTIFY_KEEP_DAYS * 86400:
                f.unlink()
    except OSError:
        pass


def notify_argv(title: str, body: str, urgency: str, discuss: bool) -> List[str]:
    argv = ["notify-send", "-a", "hermes-os", "-i", "hermes-os", "-u", urgency]
    if discuss:
        # "default" ist der Klick auf die Benachrichtigung selbst
        argv += ["-A", f"chat={DISCUSS_LABEL}", "-A", "default=Öffnen"]
    return argv + ["--", title, body]


# Wartet auf die Wahl und öffnet dann das Fenster über den Weg des Leisten-Symbols.
# $1 ist die Kontextdatei, der Rest die Argumente für notify-send.
_WAIT_SCRIPT = ('ctx="$1"; shift; choice="$(notify-send "$@")"; '
                'case "$choice" in chat|default) exec ' + shlex.quote(TRAY) + ' --discuss "$ctx" ;; esac')


def discuss_argv(context_file: str, notify: List[str]) -> List[str]:
    """Die Wartezeit läuft als eigene transiente User-Unit: Sie hängt dann nicht in der
    cgroup des Gateways und überlebt dessen Neustart (wie app_launch)."""
    inner = ["sh", "-c", _WAIT_SCRIPT, "hermes-os-notify", context_file, *notify[1:]]
    if shutil.which("systemd-run") is None:
        return inner
    unit = f"hermes-os-notify-{uuid.uuid4().hex[:8]}"
    return ["systemd-run", "--user", "--collect", "--quiet", f"--unit={unit}", "--", *inner]


def handle_desktop_notify(args: Dict[str, Any], **_kw) -> str:
    args = args or {}
    urgency = args.get("urgency") if args.get("urgency") in ("low", "normal", "critical") else "normal"
    discuss = args.get("discuss", True) is not False
    if args.get("report"):
        latest = load_state().get("latest") or {}
        if not latest.get("summary"):
            return "Kein Bericht vorhanden. Erst os_report aufrufen."
        title = str(args.get("title") or TITLE)
        body, context = str(latest["summary"]), str(latest.get("text") or latest["summary"])
    else:
        title = str(args.get("title") or "Hermes").strip()
        body = str(args.get("body") or "").strip()
        context = f"{title}\n\n{body}"
        if not body:
            return "Kein Text angegeben (body)."
    title, body = title[:120], body[:1000]
    if shutil.which("notify-send") is None:
        return "notify-send ist nicht installiert, keine Benachrichtigung gezeigt."
    if not _session_reachable():
        return "Keine Desktop-Sitzung erreichbar (kein Session-Bus), keine Benachrichtigung gezeigt."
    notify = notify_argv(title, body, urgency, discuss)
    if not discuss:
        rc, _out, err = tools._run_raw(notify, timeout=15)
        if rc != 0:
            return f"Benachrichtigung fehlgeschlagen: {err.strip()[:300] or f'exit {rc}'}"
        return f"Benachrichtigung gezeigt: {title}"
    now = _now()
    directory = state_dir() / "notify"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _prune_notify_dir(directory, now)
        context_file = directory / (_dt.datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6] + ".txt")
        context_file.write_text(context, encoding="utf-8")
    except OSError as exc:
        return f"Kontextdatei nicht angelegt: {exc}"
    argv = discuss_argv(str(context_file), notify)
    try:
        if argv[0] == "systemd-run":
            rc, _out, err = tools._run_raw(argv, timeout=15)
            if rc != 0:
                return f"Benachrichtigung nicht gestartet (systemd-run exit {rc}): {err.strip()[:300]}"
        else:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return f"Benachrichtigung nicht gestartet: {exc}"
    return (f"Benachrichtigung an die Sitzung übergeben: {title}, mit Knopf „{DISCUSS_LABEL}“. "
            "Ob sie am Bildschirm erschienen ist, wurde nicht geprüft.")
