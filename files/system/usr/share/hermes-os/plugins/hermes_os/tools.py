"""Werkzeuge des hermes-os-Plugins.

Alle os_*-Werkzeuge sind lesend und laufen ohne Root: Sie rufen die
Systemkommandos auf, die das Image mitbringt (rpm-ostree, skopeo, systemctl,
flatpak, nmcli, ...), begrenzen die Ausgabe und geben Text zurück, den das
Modell direkt lesen kann. `bootc` selbst verlangt für status/upgrade Root
(prepare_for_write), deshalb liest os_status den Deployment-Zustand über
`rpm-ostree status --json` und os_updates vergleicht Digests mit skopeo.

``app_launch`` ist die einzige schreibende Aktion: Sie startet einen
Desktop-Eintrag über ``gio launch`` in einem eigenen systemd-Scope, damit die
App nicht in der cgroup des Gateways hängt und bei dessen Neustart stirbt.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_TIMEOUT = 20
_MAX_CHARS = 12_000


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _run_raw(argv: List[str], timeout: int = _TIMEOUT, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    """Kommando ausführen; (returncode, stdout, stderr). Fehlendes Kommando -> (127, "", Hinweis)."""
    if shutil.which(argv[0]) is None:
        return 127, "", f"{argv[0]}: nicht installiert"
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "LC_ALL": "C.UTF-8", **(env or {})},
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"{' '.join(argv)}: Timeout nach {timeout}s"
    except OSError as exc:
        return 126, "", f"{' '.join(argv)}: {exc}"
    return proc.returncode, proc.stdout, proc.stderr


def _run(argv: List[str], timeout: int = _TIMEOUT, env: Optional[Dict[str, str]] = None) -> str:
    """Kommando ausführen, stdout (+stderr bei Fehler) als Text, nie eine Exception nach außen."""
    rc, out, err = _run_raw(argv, timeout, env)
    if rc == 127 or rc == 124 or rc == 126:
        return f"[{err}]"
    text = out
    if rc != 0 and err.strip():
        text += f"\n[exit {rc}] {err.strip()}"
    return text.strip()


def _clip(text: str, limit: int = _MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [gekürzt, {len(text) - limit} Zeichen weggelassen]"


def _section(title: str, body: str) -> str:
    return f"### {title}\n{body.strip() or '(leer)'}\n"


def _schema(name: str, description: str, properties: Dict[str, Any], required=None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


def check_requirements() -> bool:
    """Das Plugin ist nur auf einem Linux-Host mit systemd sinnvoll."""
    return shutil.which("systemctl") is not None and Path("/run/systemd/system").exists()


# ---------------------------------------------------------------------------
# Deployments (rpm-ostree, ohne Root)
# ---------------------------------------------------------------------------

def _deployments() -> Tuple[Optional[Dict[str, Any]], str]:
    """Booted/staged/rollback-Deployment aus `rpm-ostree status --json` (D-Bus, kein Root)."""
    rc, out, err = _run_raw(["rpm-ostree", "status", "--json"], timeout=30)
    if rc != 0:
        return None, f"[rpm-ostree status: exit {rc}] {err.strip()}"
    try:
        data = json.loads(out)
    except ValueError as exc:
        return None, f"[rpm-ostree status: JSON unlesbar: {exc}]"
    deps = data.get("deployments") or []
    booted = next((d for d in deps if d.get("booted")), None)
    staged = next((d for d in deps if d.get("staged")), None)
    others = [d for d in deps if not d.get("booted") and not d.get("staged")]
    return {"booted": booted, "staged": staged, "rollback": others[0] if others else None, "count": len(deps)}, out


def _image_ref(dep: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """(docker-Referenz ohne Transportpräfix, Digest) eines Deployments."""
    if not dep:
        return "", ""
    ref = str(dep.get("container-image-reference") or "")
    # ostree-image-signed:docker://ghcr.io/x/y:latest  ->  ghcr.io/x/y:latest
    if "docker://" in ref:
        ref = ref.split("docker://", 1)[1]
    digest = str(dep.get("container-image-reference-digest") or "")
    return ref, digest


def _describe_dep(label: str, dep: Optional[Dict[str, Any]]) -> str:
    if not dep:
        return f"{label}: (keins)"
    ref, digest = _image_ref(dep)
    version = dep.get("version") or "?"
    ts = dep.get("timestamp")
    return f"{label}: {ref or dep.get('origin', '?')}  version={version}  digest={digest[:19] + '…' if digest else '?'}  timestamp={ts}"


# ---------------------------------------------------------------------------
# os_status
# ---------------------------------------------------------------------------

OS_STATUS_SCHEMA = _schema(
    "os_status",
    "Zustand des Systems: welches Image gebootet ist, welches gestaged ist, welches der "
    "Rollback-Stand ist (rpm-ostree/bootc-Deployments), dazu os-release, Kernel, Uptime und "
    "Hermes-Version. Nur lesend, kein Root. Zuerst aufrufen, bevor du über Updates oder "
    "Rollbacks sprichst.",
    {},
)


def handle_os_status(args: Dict[str, Any], **_kw) -> str:
    parts = []
    parts.append(_section("os-release", _run(["sh", "-c", "grep -E '^(PRETTY_NAME|VARIANT_ID|VERSION_ID|IMAGE_ID|IMAGE_VERSION)=' /usr/lib/os-release"])))
    parts.append(_section("kernel / uptime", _run(["uname", "-r"]) + "\n" + _run(["uptime", "-p"])))
    info, raw = _deployments()
    if info is None:
        parts.append(_section("deployments (rpm-ostree status)", raw))
    else:
        lines = [
            _describe_dep("gebootet", info["booted"]),
            _describe_dep("gestaged (aktiv nach Reboot)", info["staged"]),
            _describe_dep("rollback", info["rollback"]),
            f"deployments gesamt: {info['count']}",
        ]
        parts.append(_section("deployments (rpm-ostree status)", "\n".join(lines)))
    stamp = Path("/usr/lib/hermes-agent/.hermes-os-release")
    if stamp.exists():
        try:
            data = dict(line.split("=", 1) for line in stamp.read_text().splitlines() if "=" in line)
            parts.append(_section("hermes", f"release {data.get('ref')}, commit {str(data.get('commit'))[:12]}, "
                                             f"python {data.get('python')}, updates via {data.get('update')}"))
        except Exception as exc:  # pragma: no cover
            parts.append(_section("hermes", f"release stamp unlesbar: {exc}"))
    return _clip("\n".join(parts))


# ---------------------------------------------------------------------------
# os_services
# ---------------------------------------------------------------------------

OS_SERVICES_SCHEMA = _schema(
    "os_services",
    "Systemd-Dienste: laufend, fehlgeschlagen oder alle. scope 'system' (Root-Dienste) "
    "oder 'user' (Dienste der Sitzung, z.B. hermes-gateway). Nur lesend.",
    {
        "scope": {"type": "string", "enum": ["system", "user"], "description": "Standard: system"},
        "state": {"type": "string", "enum": ["running", "failed", "all"], "description": "Standard: running"},
        "filter": {"type": "string", "description": "Optionaler Teilstring des Unit-Namens"},
    },
)


def handle_os_services(args: Dict[str, Any], **_kw) -> str:
    scope = args.get("scope") or "system"
    state = args.get("state") or "running"
    argv = ["systemctl"]
    if scope == "user":
        argv.append("--user")
    argv += ["list-units", "--type=service", "--no-pager", "--no-legend", "--plain"]
    if state != "all":
        argv.append(f"--state={state}")
    out = _run(argv)
    flt = (args.get("filter") or "").strip()
    if flt:
        out = "\n".join(line for line in out.splitlines() if flt in line)
    return _clip(_section(f"systemctl {scope} {state}", out))


# ---------------------------------------------------------------------------
# os_apps
# ---------------------------------------------------------------------------

OS_APPS_SCHEMA = _schema(
    "os_apps",
    "Welche Apps sind installiert und startbar? Liefert Desktop-Einträge (ID, Name) "
    "aus dem System und aus Flatpak. Die ID ist das, was app_launch braucht. "
    "Mit 'query' filtern (z.B. 'thunderbird', 'mail'). Nur lesend.",
    {"query": {"type": "string", "description": "Optionaler Suchbegriff, ohne Groß/Klein"}},
)

_APP_DIRS = (
    "/usr/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    os.path.expanduser("~/.local/share/applications"),
)


def _desktop_entries() -> List[Dict[str, str]]:
    seen: Dict[str, Dict[str, str]] = {}
    for d in _APP_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in sorted(p.glob("*.desktop")):
            app_id = f.stem
            if app_id in seen:
                continue
            name, nodisplay, hidden = app_id, False, False
            try:
                for line in f.read_text(errors="replace").splitlines():
                    if line.startswith("Name=") and name == app_id:
                        name = line[5:].strip()
                    elif line.startswith("NoDisplay=true"):
                        nodisplay = True
                    elif line.startswith("Hidden=true"):
                        hidden = True
                    elif line.startswith("[") and not line.startswith("[Desktop Entry]"):
                        break
            except OSError:
                continue
            if nodisplay or hidden:
                continue
            seen[app_id] = {"id": app_id, "name": name, "source": "flatpak" if "flatpak" in d else "system"}
    return list(seen.values())


def handle_os_apps(args: Dict[str, Any], **_kw) -> str:
    q = (args.get("query") or "").strip().lower()
    entries = _desktop_entries()
    if q:
        entries = [e for e in entries if q in e["id"].lower() or q in e["name"].lower()]
    lines = [f"{e['id']}\t{e['name']}\t({e['source']})" for e in entries]
    body = "\n".join(lines) if lines else "(keine passende App gefunden)"
    return _clip(_section(f"apps ({len(entries)})", "id\tname\tquelle\n" + body))


# ---------------------------------------------------------------------------
# os_hardware
# ---------------------------------------------------------------------------

OS_HARDWARE_SCHEMA = _schema(
    "os_hardware",
    "Hardware-Überblick: CPU, Speicher, Datenträger und Belegung, GPU. Nur lesend.",
    {},
)


def handle_os_hardware(args: Dict[str, Any], **_kw) -> str:
    parts = [
        _section("cpu", _run(["sh", "-c", "lscpu | grep -E '^(Model name|CPU\\(s\\)|Architecture)'"])),
        _section("memory", _run(["free", "-h"])),
        _section("disks", _run(["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS", "--noempty"])),
        _section("filesystem usage", _run(["df", "-h", "/", "/var", "/home"])),
        _section("gpu", _run(["sh", "-c", "lspci | grep -iE 'vga|3d|display'"])),
    ]
    return _clip("\n".join(parts))


# ---------------------------------------------------------------------------
# os_network
# ---------------------------------------------------------------------------

OS_NETWORK_SCHEMA = _schema(
    "os_network",
    "Netzwerkzustand über NetworkManager: Geräte, aktive Verbindungen, Erreichbarkeit. Nur lesend.",
    {},
)


def handle_os_network(args: Dict[str, Any], **_kw) -> str:
    parts = [
        _section("general", _run(["nmcli", "-t", "general", "status"])),
        _section("devices", _run(["nmcli", "device", "status"])),
        _section("active connections", _run(["nmcli", "connection", "show", "--active"])),
    ]
    return _clip("\n".join(parts))


# ---------------------------------------------------------------------------
# os_journal
# ---------------------------------------------------------------------------

OS_JOURNAL_SCHEMA = _schema(
    "os_journal",
    "Journal seit dem letzten Boot, standardmäßig nur Warnungen und Fehler. "
    "Optional auf eine Unit einschränken. Nur lesend, Ausgabe begrenzt.",
    {
        "unit": {"type": "string", "description": "Optionale systemd-Unit, z.B. 'NetworkManager'"},
        "priority": {"type": "string", "enum": ["err", "warning", "info"], "description": "Standard: warning"},
        "lines": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Standard: 80"},
        "user": {"type": "boolean", "description": "true = Journal der Nutzersitzung statt System"},
    },
)


def handle_os_journal(args: Dict[str, Any], **_kw) -> str:
    argv = ["journalctl", "-b", "--no-pager", "-p", args.get("priority") or "warning",
            "-n", str(int(args.get("lines") or 80))]
    if args.get("user"):
        argv.append("--user")
    unit = (args.get("unit") or "").strip()
    if unit:
        argv += ["-u", unit]
    rc, out, err = _run_raw(argv, timeout=30)
    text = out.strip()
    if rc != 0 and err.strip():
        text += f"\n[exit {rc}] {err.strip()}"
    # journalctl meldet fehlenden Zugriff auf das System-Journal nur auf stderr
    # und mit Exit 0; ohne diesen Hinweis sähe ein leeres Ergebnis wie "alles
    # ruhig" aus (Nutzer außerhalb von wheel/adm/systemd-journal).
    if not args.get("user") and "Hint:" in err:
        text += ("\n[Hinweis: kein Zugriff auf das System-Journal, nur eigene Einträge sichtbar. "
                 "Ein Konto in wheel, adm oder systemd-journal sieht alles.]")
    return _clip(_section(" ".join(argv), text))


# ---------------------------------------------------------------------------
# os_updates
# ---------------------------------------------------------------------------

OS_UPDATES_SCHEMA = _schema(
    "os_updates",
    "Stehen Updates an? Vergleicht den Digest des gebooteten Images mit der Registry "
    "(skopeo, kein Root), zeigt ein gestagetes Deployment, Flatpak-Updates und den Zustand "
    "der Auto-Update-Timer. Nur lesend. Das Einspielen selbst ist eine Aktion, die den "
    "Nutzer fragt.",
    {},
)


def _image_update_check() -> str:
    info, raw = _deployments()
    if info is None:
        return raw
    booted = info["booted"]
    ref, booted_digest = _image_ref(booted)
    lines = [_describe_dep("gebootet", booted)]
    if info["staged"]:
        lines.append(_describe_dep("gestaged (aktiv nach Reboot)", info["staged"]))
    if not ref:
        lines.append("Kein Container-Image als Ursprung erkannt, Registry-Vergleich übersprungen.")
        return "\n".join(lines)
    rc, out, err = _run_raw(["skopeo", "inspect", "--no-tags", "--format", "{{.Digest}}", f"docker://{ref}"], timeout=90)
    if rc != 0:
        lines.append(f"Registry nicht abfragbar (skopeo exit {rc}): {err.strip()[:300]}")
        return "\n".join(lines)
    remote = out.strip()
    lines.append(f"registry: {ref}  digest={remote[:19] + '…' if remote else '?'}")
    if remote and booted_digest:
        if remote == booted_digest:
            lines.append("Update verfügbar: nein (Registry-Digest = gebooteter Digest)")
        else:
            staged_digest = _image_ref(info["staged"])[1]
            if staged_digest == remote:
                lines.append("Update verfügbar: bereits gestaged, aktiv nach Reboot")
            else:
                lines.append("Update verfügbar: ja (Registry-Digest weicht ab). Einspielen: ujust update, dann Reboot.")
    return "\n".join(lines)


def _timer_state() -> str:
    timers = ["uupd.timer", "rpm-ostreed-automatic.timer", "bootc-fetch-apply-updates.timer"]
    listed = _run(["systemctl", "list-timers", "--no-pager", "--no-legend", "--all", *timers])
    enabled = _run(["sh", "-c", "for t in " + " ".join(timers) + "; do printf '%s: ' \"$t\"; systemctl is-enabled \"$t\" 2>/dev/null || echo not-found; done"])
    return listed + "\n" + enabled


def handle_os_updates(args: Dict[str, Any], **_kw) -> str:
    parts = [
        _section("system image", _image_update_check()),
        _section("flatpak updates", _run(["flatpak", "remote-ls", "--updates", "--columns=application,version,branch"], timeout=90)),
        _section("auto-update timers", _timer_state()),
    ]
    return _clip("\n".join(parts))


# ---------------------------------------------------------------------------
# app_launch
# ---------------------------------------------------------------------------

APP_LAUNCH_SCHEMA = _schema(
    "app_launch",
    "Startet eine Desktop-App über ihren Desktop-Eintrag (ID aus os_apps, z.B. "
    "'org.mozilla.Thunderbird' oder 'org.kde.konsole'). Entspricht einem Klick im "
    "Startmenü und braucht keine Rückfrage. Optional eine Datei oder URL übergeben.",
    {
        "app_id": {"type": "string", "description": "Desktop-Eintrag ohne .desktop"},
        "target": {"type": "string", "description": "Optionale Datei oder URL, die die App öffnen soll"},
    },
    required=["app_id"],
)


def _find_desktop_file(app_id: str) -> Optional[Path]:
    app_id = app_id.removesuffix(".desktop")
    if "/" in app_id or app_id.startswith("."):
        return None
    for d in _APP_DIRS:
        cand = Path(d) / f"{app_id}.desktop"
        if cand.is_file():
            return cand
    return None


def _launch_argv(desktop: Path, app_id: str, target: str) -> List[str]:
    """gio launch in einem eigenen transienten Scope: Die App gehört dann nicht
    zur cgroup des Gateways und überlebt dessen Neustart. Ohne systemd-run
    (nicht auf Aurora) bleibt der direkte Aufruf."""
    gio = ["gio", "launch", str(desktop)] + ([target] if target else [])
    if shutil.which("systemd-run") is None:
        return gio
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", app_id)[:60]
    unit = f"app-hermes-{safe}-{uuid.uuid4().hex[:8]}.scope"
    return ["systemd-run", "--user", "--scope", "--collect", "--quiet", f"--unit={unit}", "--", *gio]


def handle_app_launch(args: Dict[str, Any], **_kw) -> str:
    app_id = (args.get("app_id") or "").strip()
    target = (args.get("target") or "").strip()
    desktop = _find_desktop_file(app_id)
    if desktop is None:
        near = [e["id"] for e in _desktop_entries() if app_id.lower() in e["id"].lower() or app_id.lower() in e["name"].lower()]
        hint = f" Ähnliche IDs: {', '.join(near[:8])}" if near else ""
        return f"Kein Desktop-Eintrag '{app_id}' gefunden. Erst os_apps mit einem Suchbegriff aufrufen.{hint}"
    argv = _launch_argv(desktop, app_id, target)
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return f"Start von {app_id} fehlgeschlagen: {exc}"
    return f"Gestartet: {app_id} ({desktop}){' mit ' + target if target else ''}. Ob das Fenster erschienen ist, wurde nicht geprüft."
