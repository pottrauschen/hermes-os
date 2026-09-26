"""Protokoll: was Hermes am System getan hat (docs/protokoll.md).

Eine Datei im Home, nur anhängend: $XDG_STATE_HOME/hermes-os/audit.jsonl
(Vorgabe ~/.local/state), eine JSON-Zeile je Ereignis, Datei 0600, ab
MAX_BYTES eine Vorgängerdatei audit.jsonl.1. Es schreiben zwei Seiten:

- das Plugin im Gateway (und in der CLI) über Hermes' Hooks: Freigabe-Anfrage
  und Entscheidung (pre_approval_request, post_approval_response), Ergebnis
  eines Terminal-Befehls, den der Freigabe-Hook als Systembefehl erkannt hat
  oder der durch den Freigabe-Dialog ging (post_tool_call, auch wenn er
  blockiert wurde), und jeder app_launch;
- das Leisten-Symbol beim Klick auf die Freigabe-Karte oder die
  Benachrichtigung: welche Wahl, über welchen Weg.

Gelesen wird tolerant: kaputte Zeilen fallen weg, Ereignisse mit derselben
Aufruf-Kennung (tool_call_id) werden zu einer Zeile zusammengeführt. Die Seite
„Protokoll“ im Chat-Fenster und der Export bauen darauf auf.

Das Modul hängt wie library.py nicht am Rest des Plugins und braucht kein
Hermes und kein Qt: das Leisten-Symbol lädt es über seinen Dateipfad,
tests/audit-check.py ebenso. Schreiben wirft nie; ein Fehler im Protokoll darf
keinen Befehl aufhalten.
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

VERSION = 1
MAX_BYTES = 5 * 1024 * 1024       # ab hier wird audit.jsonl zu audit.jsonl.1
MAX_COMMAND = 2000                # Zeichen je Befehl in der Datei
MAX_OUTPUT = 800                  # Zeichen der Ausgabe: Anfang und Ende
MAX_ROWS = 5000                   # neueste Zeilen, die die Seite höchstens zeigt
MEMORY = 256                      # offene Aufrufe, die sich das Plugin merkt
TRAY_MATCH_SECONDS = 3600         # Klick im Symbol gehört zu einer Anfrage aus dieser Zeitspanne

PERIODS = ("today", "week", "all")
PERIOD_LABEL = {"today": "Heute", "week": "Letzte 7 Tage", "all": "Alles"}

GROUP_LABEL = {
    "image": "Image und Updates",
    "services": "Systemdienste",
    "network": "Firewall und Netz",
    "users": "Nutzer und Passwörter",
    "boot": "Bootloader und Kernel",
    "ssh": "SSH-Schlüssel",
    "disks": "Datenträger",
    "system-files": "Systemdateien",
    "flatpak-system": "Flatpak systemweit",
    "system-config": "Sprache, Zeit, Rechnername",
    "root-shell": "Root-Shell",
    "hermes": "Hermes-Gefahrenerkennung",
    "app": "App-Start",
}

# Wahl aus post_approval_response (tools/approval*.py in Hermes 0.21.x) und
# die Fälle, die das Protokoll selbst aus dem Ergebnis ableitet.
DECISION_LABEL = {
    "once": "Einmal erlaubt",
    "session": "Für die Sitzung erlaubt",
    "always": "Immer erlaubt",
    "deny": "Abgelehnt",
    "timeout": "Zeitüberschreitung",
    "cancelled": "Zurückgezogen",
    "notify_failed": "Nicht zustellbar",
    "smart_approve": "Vom Guardian erlaubt",
    "smart_deny": "Vom Guardian abgelehnt",
    "smart_escalate": "Guardian fragt nach",
    "cron": "Verweigert",
    "nohuman": "Verweigert",
    "blocked": "Blockiert",
    "preapproved": "Ohne Rückfrage",
    "": "",
}
APPROVING = ("once", "session", "always", "smart_approve", "preapproved")
REFUSING = ("deny", "timeout", "cancelled", "notify_failed", "smart_deny", "cron", "nohuman", "blocked")

STATUS_LABEL = {
    "ok": "Ausgeführt",
    "error": "Mit Fehler beendet",
    "denied": "Nicht ausgeführt",
    "pending": "Wartet",
    "approved": "Erlaubt, Ergebnis fehlt",
    "launched": "Gestartet",
    "failed": "Start fehlgeschlagen",
}

_SECRET_RES = (
    (re.compile(r"(?i)\b(password|passwd|passwort|pass|token|secret|api[_-]?key|apikey)(\s*[=:]\s*|\s+)(\S+)"),
     lambda m: f"{m.group(1)}{m.group(2)}***"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), lambda m: f"{m.group(1)} ***"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}"), lambda m: f"{m.group(1)}-***"),
    (re.compile(r"\b(gh[pousr]_|glpat-|xox[abp]-)[A-Za-z0-9_-]{10,}"), lambda m: f"{m.group(1)}***"),
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+@"), lambda m: f"{m.group(1)}***@"),
)


# ---------------------------------------------------------------------------
# Ablage
# ---------------------------------------------------------------------------

def audit_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "hermes-os" / "audit.jsonl"


def previous_path(path: Optional[Path] = None) -> Path:
    path = Path(path) if path else audit_path()
    return path.with_name(path.name + ".1")


def redact(text: str) -> str:
    """Offensichtliche Geheimnisse (Passwort=, Token, Bearer, sk-…) durch *** ersetzen."""
    for regex, repl in _SECRET_RES:
        text = regex.sub(repl, text)
    return text


def shorten(text: Any, limit: int = MAX_OUTPUT) -> str:
    """Auf limit Zeichen kürzen, Anfang und Ende bleiben (Fehler stehen meist hinten)."""
    text = str(text or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    half = max(1, (limit - 3) // 2)
    return text[:half].rstrip() + "\n…\n" + text[-half:].lstrip()


def append(record: Dict[str, Any], path: Optional[Path] = None, max_bytes: int = MAX_BYTES) -> bool:
    """Ein Ereignis als eine Zeile anhängen. Ein Schreibaufruf je Zeile mit
    O_APPEND, dazu eine Sperrdatei für Rotation und Schreiben, weil Gateway,
    CLI und Leisten-Symbol gleichzeitig schreiben können. Wirft nie."""
    path = Path(path) if path else audit_path()
    try:
        rec = {"v": VERSION, "ts": round(time.time(), 3)}
        rec.update({k: v for k, v in record.items() if v is not None})
        line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_fd = os.open(str(path.with_name(path.name + ".lock")), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            try:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                if os.path.getsize(path) + len(line) > max_bytes:
                    os.replace(path, previous_path(path))
            except FileNotFoundError:
                pass
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, line)
            finally:
                os.close(fd)
        finally:
            os.close(lock_fd)
        return True
    except Exception:
        return False


def read_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Alle Ereignisse, ältere Datei zuerst. Zeilen, die kein JSON-Objekt mit
    Zeitstempel sind, werden übergangen (abgebrochenes Schreiben, Handarbeit)."""
    path = Path(path) if path else audit_path()
    events: List[Dict[str, Any]] = []
    for p in (previous_path(path), path):
        try:
            with open(p, "rb") as f:
                for raw in f:
                    try:
                        ev = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if isinstance(ev, dict) and isinstance(ev.get("ts"), (int, float)) and isinstance(ev.get("kind"), str):
                        events.append(ev)
        except OSError:
            continue
    events.sort(key=lambda e: e["ts"])
    return events


# ---------------------------------------------------------------------------
# Zusammenführen: Ereignisse -> Zeilen der Seite
# ---------------------------------------------------------------------------

def group_from_pattern(pattern_key: str) -> str:
    """plugin_rule:hermes-os:<gruppe> kommt aus unserem Hook, alles andere aus
    Hermes' eigener Gefahrenerkennung."""
    m = re.match(r"^plugin_rule:hermes-os:([\w-]+)$", str(pattern_key or ""))
    return m.group(1) if m else "hermes"


def _new_row(ev: Dict[str, Any], key: str) -> Dict[str, Any]:
    return {"id": key, "ts": ev["ts"], "kind": "command", "command": "", "group": "", "description": "",
            "raw_command": "", "requested": False, "decision": "", "decided_by": "", "via": "",
            "result": False, "run_status": "", "exit_code": None, "output": "", "error": "",
            "duration_ms": None, "decided_ts": None}


def _fill(row: Dict[str, Any], ev: Dict[str, Any]) -> None:
    kind = ev["kind"]
    for field in ("command", "group", "description", "raw_command"):
        if ev.get(field) and not row[field]:
            row[field] = str(ev[field])
    if kind == "approval.request":
        row["requested"] = True
    elif kind == "approval.decision":
        row["requested"] = True
        row["decision"] = str(ev.get("choice") or "")
        row["decided_by"] = str(ev.get("decided_by") or "")
        row["decided_ts"] = ev["ts"]
    elif kind == "tray.decision":
        row["via"] = "Leisten-Symbol"
        if not row["decision"]:
            row["decision"] = str(ev.get("choice") or "")
            row["decided_ts"] = ev["ts"]
    elif kind in ("command.result", "app.launch"):
        row["result"] = True
        row["run_status"] = str(ev.get("status") or "")
        row["exit_code"] = ev.get("exit_code")
        row["output"] = str(ev.get("output") or "")
        row["error"] = str(ev.get("error") or "")
        row["duration_ms"] = ev.get("duration_ms")
        if kind == "app.launch":
            row["kind"] = "app"
            row["group"] = "app"


def _finish_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Entscheidung, Entscheider und Ergebnis aus den gesammelten Ereignissen."""
    decision = row["decision"]
    if row["kind"] == "app":
        status = "launched" if row["run_status"] == "ok" else "failed"
    elif row["result"] and row["run_status"] == "blocked":
        text = row["error"].lower()
        if not decision or decision in APPROVING:
            if "cron" in text:
                decision = "cron"
            elif "no interactive user" in text or "without a user present" in text:
                decision = "nohuman"
            else:
                decision = "blocked"
        status = "denied"
    elif row["result"]:
        if not decision:
            decision = "preapproved"
        code = row["exit_code"]
        failed = row["run_status"] == "error" or (isinstance(code, int) and not isinstance(code, bool) and code != 0)
        status = "error" if failed else "ok"
    elif decision in REFUSING:
        status = "denied"
    elif decision:
        status = "approved"
    else:
        status = "pending"

    if decision.startswith("smart_"):
        decider = "Guardian"
    elif decision == "cron":
        decider = "Cron-Verweigerung"
    elif decision == "nohuman":
        decider = "niemand erreichbar"
    elif decision in ("once", "session", "always", "deny"):
        decider = "Nutzer"
    elif decision == "preapproved":
        decider = "gespeicherte Freigabe"
    elif decision in ("timeout", "cancelled", "notify_failed"):
        decider = "keine Antwort"
    else:
        decider = ""
    if row["via"] and decider == "Nutzer":
        decider = "Nutzer im Leisten-Symbol"

    code = row["exit_code"]
    result_text = STATUS_LABEL[status]
    if isinstance(code, int) and not isinstance(code, bool) and row["kind"] == "command" and status in ("ok", "error"):
        result_text += f", Exit {code}"
    group = row["group"] or ("app" if row["kind"] == "app" else "hermes")
    when = datetime.datetime.fromtimestamp(row["ts"])
    return {
        "id": row["id"], "ts": row["ts"], "kind": row["kind"],
        "date": when.strftime("%d.%m.%Y"), "time": when.strftime("%H:%M:%S"),
        "command": row["command"] or row["raw_command"] or row["description"],
        "group": group, "groupLabel": GROUP_LABEL.get(group, group),
        "description": row["description"],
        "decision": decision, "decisionLabel": DECISION_LABEL.get(decision, decision),
        "decider": decider, "status": status, "resultText": result_text,
        "exitCode": code if isinstance(code, int) and not isinstance(code, bool) else None,
        "output": row["output"] or row["error"],
        # Änderung heißt: der Befehl ist wirklich gelaufen, erfolgreich oder nicht.
        "changed": row["kind"] == "command" and status in ("ok", "error"),
    }


def build_rows(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ereignisse zu Zeilen, neueste zuerst. Gleiche Aufruf-Kennung heißt
    gleiche Zeile, auch wenn Plugin und Hermes' eigener Detektor nacheinander
    fragen (systemctl restart); die letzte Entscheidung zählt. Ein Klick im
    Leisten-Symbol hängt sich an die jüngste Anfrage mit demselben angezeigten
    Befehl."""
    rows: "collections.OrderedDict[str, Dict[str, Any]]" = collections.OrderedDict()
    loose = 0
    for ev in events:
        kind = ev.get("kind")
        if kind not in ("approval.request", "approval.decision", "command.result", "app.launch", "tray.decision"):
            continue
        if kind == "tray.decision":
            target = None
            for row in reversed(rows.values()):
                if ev["ts"] - row["ts"] > TRAY_MATCH_SECONDS:
                    break
                if row["requested"] and row["ts"] <= ev["ts"] \
                        and (row["raw_command"] == str(ev.get("command") or "") or row["command"] == str(ev.get("command") or "")):
                    target = row
                    break
            if target is not None:
                _fill(target, ev)
                continue
        call = str(ev.get("call") or "")
        if call:
            key = "c:" + call
        else:
            loose += 1
            key = f"e:{loose}"
        row = rows.get(key)
        if row is None:
            row = rows[key] = _new_row(ev, key)
        _fill(row, ev)
    out = [_finish_row(r) for r in rows.values()]
    out.sort(key=lambda r: r["ts"], reverse=True)
    return out[:MAX_ROWS]


def period_start(period: str, now: Optional[float] = None) -> float:
    now = time.time() if now is None else now
    if period == "today":
        d = datetime.datetime.fromtimestamp(now)
        return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if period == "week":
        return now - 7 * 86400
    return 0.0


def filter_rows(rows: Iterable[Dict[str, Any]], period: str = "all", changes_only: bool = False,
                now: Optional[float] = None) -> List[Dict[str, Any]]:
    start = period_start(period, now)
    return [r for r in rows if r["ts"] >= start and (r["changed"] or not changes_only)]


def load_rows(period: str = "all", changes_only: bool = False, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return filter_rows(build_rows(read_events(path)), period, changes_only)


def export_text(rows: List[Dict[str, Any]], period: str = "all", changes_only: bool = False,
                now: Optional[float] = None) -> str:
    """Klartext für die Datei aus dem Export-Dialog, älteste Zeile zuerst."""
    stamp = datetime.datetime.fromtimestamp(time.time() if now is None else now).strftime("%d.%m.%Y %H:%M")
    lines = [
        f"Protokoll von Hermes auf {socket.gethostname()}, erstellt am {stamp}",
        f"Zeitraum: {PERIOD_LABEL.get(period, period)}; "
        + ("nur Änderungen am System" if changes_only else "alle Einträge")
        + f"; {len(rows)} " + ("Eintrag" if len(rows) == 1 else "Einträge"),
        "",
    ]
    if not rows:
        lines.append("Keine Einträge.")
    for r in sorted(rows, key=lambda r: r["ts"]):
        head = f"{r['date']} {r['time']}  {r['groupLabel']}"
        if r["decisionLabel"]:
            head += f"  {r['decisionLabel']}" + (f" ({r['decider']})" if r["decider"] else "")
        head += f"  {r['resultText']}"
        lines.append(head)
        lines.append(("  App: " if r["kind"] == "app" else "  $ ") + r["command"])
        if r["output"]:
            for out in r["output"].splitlines():
                lines.append("  | " + out)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_export(target: str, rows: List[Dict[str, Any]], period: str = "all", changes_only: bool = False) -> str:
    """Export schreiben; leerer Text heißt Erfolg, sonst der Fehler fürs Fenster."""
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(export_text(rows, period, changes_only))
        return ""
    except OSError as exc:
        return f"Export fehlgeschlagen: {exc.strerror or exc}"


# ---------------------------------------------------------------------------
# Schreibende Seite: Leisten-Symbol
# ---------------------------------------------------------------------------

def record_tray_decision(command: str, choice: str, request_id: str = "", description: str = "") -> bool:
    """Klick auf die Freigabe-Karte oder die Benachrichtigung."""
    return append({"kind": "tray.decision", "command": redact(shorten(command, MAX_COMMAND)),
                   "description": redact(shorten(description, 300)), "choice": choice,
                   "request_id": request_id or None, "source": "tray"})


# ---------------------------------------------------------------------------
# Schreibende Seite: Hooks im Plugin
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_flagged: "collections.OrderedDict[str, Dict[str, str]]" = collections.OrderedDict()
_approval_calls: "collections.OrderedDict[str, bool]" = collections.OrderedDict()
_classify: Optional[Callable[[str], Optional[Dict[str, str]]]] = None


def _remember(store: "collections.OrderedDict", key: str, value: Any) -> None:
    with _lock:
        store[key] = value
        store.move_to_end(key)
        while len(store) > MEMORY:
            store.popitem(last=False)


def _key(call: str, command: str = "") -> str:
    return ("c:" + call) if call else ("cmd:" + command)


def record_flagged(hit: Optional[Dict[str, str]], args: Any, **kw: Any) -> None:
    """Aus dem pre_tool_call-Hook: diesen Aufruf hat der Freigabe-Hook als
    Systembefehl erkannt. Nur merken, nicht schreiben; der Hook fällt auch bei
    Trockenläufen (Gate, Tests), die Datei entsteht erst mit einer echten
    Anfrage oder einem Ergebnis."""
    try:
        if not hit or not isinstance(args, dict):
            return
        command = str(args.get("command") or "")
        _remember(_flagged, _key(str(kw.get("tool_call_id") or ""), command),
                  {"command": command, "group": str(hit.get("group") or "")})
    except Exception:
        pass


def _flag_for(call: str, command: str = "", pop: bool = False) -> Optional[Dict[str, str]]:
    with _lock:
        for key in (_key(call, command), _key("", command)) if call else (_key("", command),):
            if key in _flagged:
                return _flagged.pop(key) if pop else _flagged[key]
    return None


def _approval_record(kind: str, kw: Dict[str, Any]) -> Dict[str, Any]:
    call = str(kw.get("tool_call_id") or "")
    raw = str(kw.get("command") or "")
    flag = _flag_for(call, raw)
    pattern_key = str(kw.get("pattern_key") or "")
    if call:
        _remember(_approval_calls, call, True)
    return {
        "kind": kind, "call": call or None,
        "session": str(kw.get("session_id") or kw.get("session_key") or "") or None,
        "command": redact(shorten(flag["command"] if flag else raw, MAX_COMMAND)),
        "raw_command": redact(shorten(raw, MAX_COMMAND)),
        "description": redact(shorten(kw.get("description") or "", 300)),
        "group": (flag["group"] if flag else "") or group_from_pattern(pattern_key),
        "pattern_key": pattern_key or None,
        "surface": str(kw.get("surface") or "") or None,
        "coalesced": True if kw.get("coalesced") else None,
        "source": "hook",
    }


def on_pre_approval_request(**kw: Any) -> None:
    try:
        append(_approval_record("approval.request", kw))
    except Exception:
        pass


def on_post_approval_response(**kw: Any) -> None:
    try:
        rec = _approval_record("approval.decision", kw)
        rec["choice"] = str(kw.get("choice") or "")
        rec["decided_by"] = str(kw.get("decided_by") or "") or None
        append(rec)
    except Exception:
        pass


def _terminal_result(result: Any) -> Dict[str, Any]:
    """Hermes' Terminal-Werkzeug antwortet mit JSON {output, exit_code, error}."""
    data: Any = result
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except ValueError:
            return {"output": result}
    if not isinstance(data, dict):
        return {"output": str(result or "")}
    code = data.get("exit_code")
    return {"output": str(data.get("output") or ""), "error": str(data.get("error") or ""),
            "exit_code": code if isinstance(code, int) and not isinstance(code, bool) else None}


def on_post_tool_call(tool_name: str = "", args: Any = None, result: Any = None, **kw: Any) -> None:
    try:
        args = args if isinstance(args, dict) else {}
        call = str(kw.get("tool_call_id") or "")
        status = str(kw.get("status") or "")
        error_message = str(kw.get("error_message") or "")
        blocked = status == "blocked" or kw.get("error_type") in ("plugin_block", "guardrail_block") \
            or error_message.startswith("BLOCKED")
        if tool_name == "app_launch":
            text = str(result or "")
            append({"kind": "app.launch", "call": call or None,
                    "session": str(kw.get("session_id") or "") or None,
                    "command": shorten(str(args.get("app_id") or "")
                                       + (f" {args.get('target')}" if args.get("target") else ""), MAX_COMMAND),
                    "status": "ok" if text.startswith("Gestartet") and not blocked else "error",
                    "output": shorten(text), "duration_ms": kw.get("duration_ms"), "source": "hook"})
            return
        if tool_name != "terminal":
            return
        command = str(args.get("command") or "")
        flag = _flag_for(call, command, pop=True)
        with _lock:
            asked = _approval_calls.pop(call, False) if call else False
        if flag is None and not asked and _classify is not None:
            hit = _classify(command)
            flag = {"command": command, "group": hit["group"]} if hit else None
        if flag is None and not asked:
            return
        parsed = _terminal_result(result)
        if blocked:
            run_status = "blocked"
        elif status == "error" or parsed.get("error"):
            run_status = "error"
        else:
            run_status = "ok"
        append({"kind": "command.result", "call": call or None,
                "session": str(kw.get("session_id") or "") or None,
                "command": redact(shorten(command, MAX_COMMAND)),
                "group": (flag or {}).get("group") or "hermes",
                "status": run_status, "exit_code": parsed.get("exit_code"),
                "output": redact(shorten(parsed.get("output") or "")),
                "error": redact(shorten(parsed.get("error") or error_message, 400)) or None,
                "duration_ms": kw.get("duration_ms"), "source": "hook"})
    except Exception:
        pass


def register_hooks(ctx, classify: Optional[Callable[[str], Optional[Dict[str, str]]]] = None) -> None:
    """Vom Plugin aus register() aufgerufen. classify ist classify_system_command,
    als Rückfall, wenn ein Ergebnis ohne vorherigen Hook-Aufruf ankommt."""
    global _classify
    _classify = classify
    ctx.register_hook("pre_approval_request", on_pre_approval_request)
    ctx.register_hook("post_approval_response", on_post_approval_response)
    ctx.register_hook("post_tool_call", on_post_tool_call)
