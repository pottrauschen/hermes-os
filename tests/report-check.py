#!/usr/bin/python3
# =============================================================================
# hermes-os -- Morgenbericht prüfen: os_report und desktop_notify ohne Hermes
# =============================================================================
# Lädt plugins/hermes_os/tools.py und report.py über ihren Pfad (ohne
# __init__.py, ohne Hermes, ohne Qt) und ersetzt die Kommandoaufrufe durch
# Fixtures: rpm-ostree status --json, skopeo inspect, journalctl -o json, df,
# systemctl --failed (System und Nutzer), flatpak remote-ls. Geprüft werden
# Text der Kurzfassung, Schwellen für den Plattenplatz, composefs-Wurzel, der
# Vergleich mit dem Bericht vom Vortag (neue Quellen, Zeitpunkt), fehlende
# Kommandos, der Zustand unter $XDG_STATE_HOME/hermes-os und desktop_notify
# (Argumente für notify-send und systemd-run, Kontextdatei, Weg zum Fenster).
#
# Ohne Netz, ohne systemd. Läuft mit jedem Python 3.9+:
#   tests/report-check.py [--plugin-dir DIR] [--libexec FILE]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7h) führt ihn
# im Image-Build aus, `make lint` ebenso.
# =============================================================================
import argparse
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PLUGIN = HERE.parent / "files/system/usr/share/hermes-os/plugins/hermes_os"
DEFAULT_LIBEXEC = HERE.parent / "files/system/usr/libexec/hermes-os-morgenbericht"

BOOTED_DIGEST = "sha256:" + "a" * 64
REMOTE_DIGEST = "sha256:" + "b" * 64


def load_plugin(plugin_dir):
    pkg = types.ModuleType("hermes_os")
    pkg.__path__ = [str(plugin_dir)]
    sys.modules["hermes_os"] = pkg
    mods = {}
    for name in ("tools", "report"):
        spec = importlib.util.spec_from_file_location(f"hermes_os.{name}", Path(plugin_dir) / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"hermes_os.{name}"] = mod
        spec.loader.exec_module(mod)
        setattr(pkg, name, mod)
        mods[name] = mod
    return mods["tools"], mods["report"]


def deployments(staged=False):
    deps = [{"booted": True, "container-image-reference": "ostree-image-signed:docker://ghcr.io/pottrauschen/hermes-os:latest",
             "container-image-reference-digest": BOOTED_DIGEST, "version": "44.20260920", "timestamp": 1}]
    if staged:
        deps.insert(0, {"staged": True, "container-image-reference": deps[0]["container-image-reference"],
                        "container-image-reference-digest": REMOTE_DIGEST, "version": "44.20260926"})
    deps.append({"container-image-reference": deps[-1]["container-image-reference"],
                 "container-image-reference-digest": "sha256:" + "c" * 64, "version": "44.20260913"})
    return json.dumps({"deployments": deps})


def jline(unit=None, ident=None, msg="kaputt", user_unit=None):
    e = {"MESSAGE": msg, "PRIORITY": "3"}
    if unit:
        e["_SYSTEMD_UNIT"] = unit
    if user_unit:
        e["_SYSTEMD_USER_UNIT"] = user_unit
    if ident:
        e["SYSLOG_IDENTIFIER"] = ident
    return json.dumps(e)


DF_HEADER = "Filesystem     Type  1B-blocks  Avail Use%"


class Fake:
    """Ersetzt tools._run_raw: je Kommando eine Antwort, Aufrufe werden mitgeschrieben."""

    def __init__(self):
        self.calls = []
        self.missing = set()
        self.staged = False
        self.remote = REMOTE_DIGEST
        self.journal = [jline("NetworkManager.service"), jline("NetworkManager.service"), jline(ident="kernel", msg="usb 1-1: error")]
        self.journal_err = ""
        self.df = {"/": ("composefs", 100), "/var": ("/dev/vda3", 92), "/home": ("/dev/vda3", 92), "/sysroot": ("/dev/vda3", 92)}
        self.failed_system = ""
        self.failed_user = ""
        self.flatpak = "org.mozilla.firefox\t140.0\tstable\norg.kde.okular\t25.08\tstable\n"

    def __call__(self, argv, timeout=20, env=None):
        self.calls.append(list(argv))
        cmd = argv[0]
        if cmd in self.missing:
            return 127, "", f"{cmd}: nicht installiert"
        if cmd == "rpm-ostree":
            return 0, deployments(self.staged), ""
        if cmd == "skopeo":
            return 0, json.dumps({"Digest": self.remote, "Labels": {"org.opencontainers.image.version": "44.20260926"}}), ""
        if cmd == "journalctl":
            return 0, "\n".join(self.journal) + "\n", self.journal_err
        if cmd == "df":
            if "-P" in argv and any(x.startswith("--output") for x in argv):
                return 1, "", "df: options -P and --output are mutually exclusive"  # wie GNU df
            rows = [DF_HEADER]
            for p in [a for a in argv[1:] if a.startswith("/")]:
                src, pct = self.df[p]
                fstype = "composefs" if src == "composefs" else "btrfs"
                size = 100 * 1024 ** 3
                rows.append(f"{src} {fstype} {size} {size * (100 - pct) // 100} {pct}%")
            return 0, "\n".join(rows) + "\n", ""
        if cmd == "systemctl":
            return 0, (self.failed_user if "--user" in argv else self.failed_system), ""
        if cmd == "flatpak":
            return 0, self.flatpak, ""
        if cmd in ("notify-send", "systemd-run"):
            return 0, "", ""
        return 127, "", f"{cmd}: unbekannt im Test"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-dir", default=str(DEFAULT_PLUGIN))
    ap.add_argument("--libexec", default=str(DEFAULT_LIBEXEC))
    a = ap.parse_args()

    tools, report = load_plugin(a.plugin_dir)
    fail = 0

    def check(ok, label, detail=""):
        nonlocal fail
        print(("OK    " if ok else "FEHL  ") + label + ("" if ok or not detail else f"\n      {detail}"))
        if not ok:
            fail += 1

    tmp = tempfile.mkdtemp(prefix="report-check-")
    os.environ["XDG_STATE_HOME"] = tmp
    fake = Fake()
    tools._run_raw = fake
    report._disk_paths = lambda: ["/", "/var", "/home", "/sysroot"]
    day1 = dt.datetime(2026, 9, 25, 8, 30).timestamp()
    day2 = dt.datetime(2026, 9, 26, 8, 30).timestamp()
    clock = {"now": day1}
    report._now = lambda: clock["now"]

    # ---- 1. Erster Bericht: kein Vergleich, Update verfügbar, /var und /home voll
    r = report.build_report(record=True)
    s = r["summary"]
    check(s.startswith("Neues Image verfügbar (44.20260926)."), "Update verfügbar mit Version aus dem Label", s)
    check("3 Fehler im Journal in den letzten 24 Stunden." in s, "erster Bericht: Fehler der letzten 24 Stunden, ohne „neu“", s)
    check("/var und /home bei 92 %." in s, "gleiches Dateisystem zusammengefasst, Schwelle 85 % gerissen", s)
    check("/ " not in s.replace("/var", "").replace("/home", "") and "composefs" not in s,
          "composefs-Wurzel nicht gemeldet, / über /sysroot gemessen", s)
    check("Kein fehlgeschlagener Dienst." in s, "keine fehlgeschlagenen Dienste", s)
    check("2 Flatpak-Updates verfügbar." in s, "Flatpak-Updates gezählt", s)
    since_arg = next(c for c in fake.calls if c[0] == "journalctl")[2]
    check(since_arg == f"@{int(day1 - 24 * 3600)}", "journalctl --since 24 Stunden zurück", since_arg)
    check("Einzelheiten:" in r["text"] and "NetworkManager.service: 2" in r["text"] and "kernel: 1" in r["text"],
          "Einzelheiten nennen die Quellen mit Anzahl", r["text"])
    check("ujust update" in r["text"], "Einzelheiten nennen den Weg zum Update (fragt den Nutzer)")
    state = json.loads((Path(tmp) / "hermes-os" / "morgenbericht.json").read_text(encoding="utf-8"))
    check(state.get("baseline", {}).get("time") == day1 and state["baseline"]["sources"] == {"NetworkManager.service": 2, "kernel": 1},
          "record=true speichert Zeitpunkt und Quellen unter $XDG_STATE_HOME/hermes-os", str(state.get("baseline")))
    check(state.get("latest", {}).get("summary") == s, "letzter Bericht gespeichert für desktop_notify")

    # ---- 2. Nächster Morgen: Vergleich mit dem Vortag
    clock["now"] = day2
    fake.calls.clear()
    fake.journal = [jline("NetworkManager.service"), jline("bluetooth.service", msg="Failed to set mode"),
                    jline(unit="user@1000.service", user_unit="pipewire.service")]
    fake.df = {"/": ("/dev/vda3", 40), "/var": ("/dev/vda3", 40), "/home": ("/dev/vdb1", 92), "/sysroot": ("/dev/vda3", 40)}
    fake.flatpak = ""
    r2 = report.build_report(record=True)
    s2 = r2["summary"]
    since_arg = next(c for c in fake.calls if c[0] == "journalctl")[2]
    check(since_arg == f"@{int(day1)}", "journalctl --since ab dem letzten Bericht", since_arg)
    check("3 Fehler im Journal seit gestern 08:30, davon 2 neu: bluetooth.service, pipewire.service." in s2,
          "Vergleich zum Vortag: neue Quellen benannt, Nutzer-Unit statt user@", s2)
    check("/home bei 92 %." in s2 and "/var" not in s2, "nur das volle Dateisystem erscheint", s2)
    check("Flatpak" not in s2, "ohne Flatpak-Updates kein Satz dazu", s2)
    check(s2.startswith("Neues Image verfügbar"), "Update weiter verfügbar")

    # ---- 3. Dritter Lauf ohne record: keine neue Quelle, Vergleichspunkt bleibt
    clock["now"] = day2 + 3600
    fake.journal = [jline("bluetooth.service")]
    s3 = report.build_report(record=False)["summary"]
    check("1 Fehler im Journal seit heute 08:30, keine neue Quelle." in s3, "bekannte Quelle ist nicht neu", s3)
    state = json.loads((Path(tmp) / "hermes-os" / "morgenbericht.json").read_text(encoding="utf-8"))
    check(state["baseline"]["time"] == day2, "record=false lässt den Vergleichspunkt stehen")

    # ---- 4. Schwellen und Dienste
    fake.journal = []
    for pct, want in ((84, "Plattenplatz ok (höchstens 84 %)."), (85, "/home bei 85 %."), (95, "/home fast voll (95 %).")):
        fake.df["/home"] = ("/dev/vdb1", pct)
        got = report.build_report()["summary"]
        check(want in got, f"Schwelle {pct} %: {want}", got)
    check("Keine Fehler im Journal seit heute 08:30." in got, "leeres Journal", got)
    fake.failed_system = "bluetooth.service loaded failed failed Bluetooth service\n"
    fake.failed_user = "● syncthing.service loaded failed failed Syncthing\n"
    got = report.build_report()["summary"]
    check("Fehlgeschlagen: 2 Dienste, bluetooth.service (System) und syncthing.service (Nutzer)." in got,
          "fehlgeschlagene Dienste aus System und Sitzung", got)
    fake.failed_system = fake.failed_user = ""

    # ---- 5. Image-Zustände
    fake.remote = BOOTED_DIGEST
    fake.calls.clear()
    got = report.build_report(flatpak=False)["summary"]
    check(got.startswith("System-Image aktuell."), "Registry = gebootet: aktuell", got)
    check(not any(c[0] == "flatpak" for c in fake.calls), "flatpak=false fragt Flatpak nicht")
    fake.staged, fake.remote = True, REMOTE_DIGEST
    got = report.build_report()["summary"]
    check(got.startswith("Neues Image liegt bereit, aktiv nach Neustart (44.20260926)."), "gestagetes Image", got)
    fake.staged = False
    out = tools.handle_os_updates({})
    check("Update verfügbar: ja" in out and "version=44.20260926" in out, "os_updates nutzt dieselbe Logik", out[:400])

    # ---- 6. Eingeschränktes Journal und fehlende Kommandos
    fake.journal = [jline("a.service")]
    fake.journal_err = "Hint: You are currently not seeing messages from other users and the system."
    got = report.build_report()["summary"]
    check("(nur eigene Einträge lesbar)." in got, "Hinweis bei fehlendem Zugriff aufs System-Journal", got)
    fake.journal_err = ""
    fake.missing = {"rpm-ostree", "skopeo", "journalctl", "df", "systemctl", "flatpak"}
    try:
        got = report.build_report()["summary"]
        check(got == "Update-Stand unbekannt. Journal nicht lesbar. Plattenplatz nicht lesbar. Dienste nicht lesbar.",
              "fehlende Kommandos: kurzer Bericht, keine Ausnahme", got)
    except Exception as exc:  # noqa: BLE001
        check(False, "fehlende Kommandos: keine Ausnahme", repr(exc))
    fake.missing = set()
    out = report.handle_os_report({"flatpak": False})
    check(out.startswith("Morgenbericht, ") and "Kurzfassung:" in out, "os_report liefert Text fürs Modell", out[:200])

    # ---- 7. desktop_notify
    shutil_which = report.shutil.which
    report.shutil.which = lambda name: f"/usr/bin/{name}"
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
    fake.calls.clear()
    res = report.handle_desktop_notify({"report": True})
    call = fake.calls[-1] if fake.calls else []
    check(call[:3] == ["systemd-run", "--user", "--collect"], "Benachrichtigung wartet in eigener User-Unit", str(call))
    check("chat=Im Chat besprechen" in call and "default=Öffnen" in call, "Knopf „Im Chat besprechen“ und Klick", str(call))
    latest = report.load_state()["latest"]
    check(call[-2:] == ["Morgenbericht", latest["summary"]], "Titel und Kurzfassung aus dem letzten Bericht", str(call[-2:]))
    ctx_file = call[call.index("hermes-os-notify") + 1] if "hermes-os-notify" in call else ""
    check(ctx_file.startswith(str(Path(tmp) / "hermes-os" / "notify")) and Path(ctx_file).read_text(encoding="utf-8") == latest["text"],
          "Kontextdatei unter $XDG_STATE_HOME/hermes-os/notify mit dem ganzen Bericht", ctx_file)
    script = call[call.index("-c") + 1] if "-c" in call else ""
    check("/usr/libexec/hermes-os-tray --discuss" in script and "notify-send" in script,
          "Knopf öffnet das Fenster über hermes-os-tray --discuss", script)
    check("nicht geprüft" in res, "ehrliche Rückmeldung: Anzeige nicht geprüft", res)
    # Wartet notify-send und die Wahl ist chat, ruft das Skript den Tray; mit einem Ersatz für beide geprüft
    bindir = Path(tmp) / "bin"
    bindir.mkdir()
    (bindir / "notify-send").write_text("#!/bin/sh\necho chat\n", encoding="utf-8")
    (bindir / "notify-send").chmod(0o755)
    log = Path(tmp) / "tray.log"
    fake_tray = bindir / "tray"
    fake_tray.write_text(f"#!/bin/sh\necho \"$@\" > {log}\n", encoding="utf-8")
    fake_tray.chmod(0o755)
    sh_script = script.replace("/usr/libexec/hermes-os-tray", str(fake_tray))
    subprocess.run(["sh", "-c", sh_script, "hermes-os-notify", ctx_file, "-a", "x", "--", "T", "B"],
                   env={**os.environ, "PATH": f"{bindir}:{os.environ.get('PATH', '')}"}, check=False, timeout=20)
    check(log.exists() and log.read_text(encoding="utf-8").strip() == f"--discuss {ctx_file}",
          "Wahl „chat“ startet den Tray mit der Kontextdatei", log.read_text(encoding="utf-8") if log.exists() else "kein Aufruf")
    fake.calls.clear()
    res = report.handle_desktop_notify({"title": "Hermes", "body": "Fertig.", "discuss": False})
    check(fake.calls and fake.calls[-1][0] == "notify-send" and "-A" not in fake.calls[-1] and res.startswith("Benachrichtigung gezeigt"),
          "ohne Knopf: notify-send direkt, ohne Aktion", str(fake.calls))
    check(report.handle_desktop_notify({"body": ""}).startswith("Kein Text"), "leerer Text abgewiesen")
    os.environ.pop("DBUS_SESSION_BUS_ADDRESS")
    os.environ["XDG_RUNTIME_DIR"] = str(Path(tmp) / "kein-runtime")
    check(report.handle_desktop_notify({"body": "x"}).startswith("Keine Desktop-Sitzung"), "ohne Session-Bus ehrlich abgelehnt")
    report.shutil.which = shutil_which
    (Path(tmp) / "hermes-os" / "morgenbericht.json").unlink()
    check(report.handle_desktop_notify({"report": True}).startswith("Kein Bericht"), "report=true ohne Bericht abgelehnt")

    # ---- 8. Einstieg des Cron-Jobs
    if Path(a.libexec).is_file():
        p = subprocess.run([sys.executable, a.libexec, "--check"], capture_output=True, text=True, timeout=30,
                           env={**os.environ, "HERMES_OS_PLUGIN_DIR": a.plugin_dir})
        check(p.returncode == 0 and "OK" in p.stdout, "hermes-os-morgenbericht --check lädt das Plugin", p.stdout + p.stderr)
    else:
        print(f"WARN  {a.libexec} fehlt, Einstieg nicht geprüft")

    shutil.rmtree(tmp, ignore_errors=True)
    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
