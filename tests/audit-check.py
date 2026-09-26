#!/usr/bin/python3
# =============================================================================
# hermes-os -- Protokoll des Plugins prüfen: Schreiben, Lesen, Rotation, Filter
# =============================================================================
# Lädt plugins/hermes_os/audit.py über seinen Pfad (ohne Hermes, ohne Qt) und
# spielt in einem Wegwerf-XDG_STATE_HOME durch, was Gateway und Leisten-Symbol
# schreiben: Freigabe mit Klick im Symbol und Ergebnis, Ablehnung, Guardian,
# Zeitüberschreitung, Cron-Verweigerung, gespeicherte Freigabe, app_launch,
# freie Befehle (kein Eintrag). Dazu Dateirechte, kaputte Zeilen, Rotation mit
# einer Vorgängerdatei, Filter nach Zeitraum und Änderungen, Export-Text,
# Schwärzen von Geheimnissen.
#
# Die Hook-Aufrufe tragen dieselben Schlüsselwörter wie Hermes 0.21.x
# (model_tools._emit_post_tool_call_hook, tools/approval_gateway_wait.py).
#   tests/audit-check.py [--plugin-dir DIR]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7h) führt ihn
# im Image-Build aus, `make lint` ebenso.
# =============================================================================
import argparse
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_RULE = "<terminal> (plugin approval rule)"   # so zeigt Hermes eine Plugin-Freigabe an


def classify(command):
    """Kleiner Ersatz für classify_system_command, nur für den Rückfall."""
    return {"group": "services", "segment": command} if "systemctl restart" in command else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-dir", default="/usr/share/hermes-os/plugins/hermes_os")
    args = ap.parse_args()
    module_path = os.path.join(args.plugin_dir, "audit.py")
    if not os.path.isfile(module_path):
        print(f"FEHL  {module_path} fehlt")
        return 1
    fail = 0

    def step(label, ok, detail=""):
        nonlocal fail
        if ok:
            print(f"OK    {label}")
        else:
            fail = 1
            print(f"FEHL  {label}" + (f": {detail}" if detail else ""))

    tmp = tempfile.mkdtemp(prefix="hermes-audit-")
    os.environ["XDG_STATE_HOME"] = tmp
    spec = importlib.util.spec_from_file_location("hermes_os_audit", module_path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)

    class Ctx:
        hooks = {}

        def register_hook(self, name, cb):
            self.hooks[name] = cb

    ctx = Ctx()
    audit.register_hooks(ctx, classify)
    step("Hooks registriert", sorted(ctx.hooks) == ["post_approval_response", "post_tool_call", "pre_approval_request"],
         str(sorted(ctx.hooks)))
    path = audit.audit_path()
    step("Ablage unter XDG_STATE_HOME", str(path) == os.path.join(tmp, "hermes-os", "audit.jsonl"), str(path))

    # 1. Plugin-Freigabe: Hook erkennt, Nutzer klickt im Symbol, Befehl läuft
    cmd = "sudo systemctl restart sshd"
    audit.record_flagged({"group": "services", "segment": "systemctl restart sshd"}, {"command": cmd},
                         tool_call_id="call-1", session_id="s1")
    step("Erkennen allein schreibt nichts (Trockenlauf im Gate)", not path.exists())
    base = dict(command=PLUGIN_RULE, description="hermes-os: `systemctl restart sshd` berührt das laufende System",
                pattern_key="plugin_rule:hermes-os:services", pattern_keys=["plugin_rule:hermes-os:services"],
                session_key="s1", surface="gateway", tool_call_id="call-1", turn_id="t1")
    ctx.hooks["pre_approval_request"](**base)
    audit.record_tray_decision(PLUGIN_RULE, "once", "req-1")
    ctx.hooks["post_approval_response"](**base, choice="once")
    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": cmd},
                                result=json.dumps({"output": "ok\n", "exit_code": 0, "error": None}),
                                tool_call_id="call-1", session_id="s1", duration_ms=420, status="ok")
    step("Datei 0600", stat.S_IMODE(os.stat(path).st_mode) == 0o600, oct(stat.S_IMODE(os.stat(path).st_mode)))
    rows = audit.load_rows()
    r = rows[0] if rows else {}
    step("Freigabe, Klick und Ergebnis in einer Zeile", len(rows) == 1, f"{len(rows)} Zeilen")
    step("echter Befehl statt Platzhalter", r.get("command") == cmd, r.get("command"))
    step("Gruppe, Entscheidung, Entscheider",
         r.get("group") == "services" and r.get("groupLabel") == "Systemdienste" and r.get("decision") == "once"
         and r.get("decider") == "Nutzer im Leisten-Symbol", f"{r.get('group')} {r.get('decision')} {r.get('decider')}")
    step("Ergebnis mit Exit-Code", r.get("status") == "ok" and r.get("exitCode") == 0
         and r.get("resultText") == "Ausgeführt, Exit 0" and r.get("changed") is True, r.get("resultText"))

    # 1b. Plugin und Hermes' Detektor fragen nacheinander für denselben Aufruf
    #     (so in Hermes 0.21.5 bei systemctl restart), zwei Klicks im Symbol
    audit.record_flagged({"group": "services"}, {"command": "sudo systemctl restart cups"}, tool_call_id="call-1b")
    plug = dict(base, tool_call_id="call-1b")
    ctx.hooks["pre_approval_request"](**plug)
    audit.record_tray_decision(PLUGIN_RULE, "once", "req-2")
    ctx.hooks["post_approval_response"](**plug, choice="once")
    own = dict(command="sudo systemctl restart cups", description="stop/restart system service",
               pattern_key="stop/restart system service", pattern_keys=["stop/restart system service"],
               session_key="s1", surface="gateway", tool_call_id="call-1b")
    ctx.hooks["pre_approval_request"](**own)
    audit.record_tray_decision("sudo systemctl restart cups", "deny", "req-3")
    ctx.hooks["post_approval_response"](**own, choice="deny")
    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": "sudo systemctl restart cups"},
                                result=json.dumps({"error": "BLOCKED: User denied"}), tool_call_id="call-1b",
                                status="blocked", error_message="BLOCKED: User denied")
    rows = audit.load_rows()
    two = [r for r in rows if r["command"] == "sudo systemctl restart cups"]
    step("zwei Anfragen, zwei Klicks, eine Zeile, letzte Entscheidung zählt",
         len(rows) == 2 and len(two) == 1 and two[0]["decision"] == "deny" and two[0]["status"] == "denied"
         and two[0]["decider"] == "Nutzer im Leisten-Symbol", str([(r["command"], r["decision"]) for r in rows]))

    # 2. Ablehnung, 3. Guardian, 4. Zeitüberschreitung (Hermes' eigener Detektor, ohne Plugin-Treffer)
    for call, choice, extra in (("call-2", "deny", {}), ("call-3", "smart_deny", {"decided_by": "aux_llm"}),
                                ("call-4", "timeout", {})):
        kw = dict(command="rm -rf /etc/foo", description="recursive delete", pattern_key="recursive delete",
                  pattern_keys=["recursive delete"], session_key="s1", surface="gateway", tool_call_id=call)
        ctx.hooks["pre_approval_request"](**kw)
        ctx.hooks["post_approval_response"](**kw, choice=choice, **extra)
        ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": "rm -rf /etc/foo"},
                                    result=json.dumps({"error": "BLOCKED: denied"}), tool_call_id=call,
                                    status="blocked", error_type="plugin_block", error_message="BLOCKED: denied")
    rows = {r["id"]: r for r in audit.load_rows()}
    step("Ablehnung: nicht ausgeführt, Nutzer",
         rows["c:call-2"]["status"] == "denied" and rows["c:call-2"]["decider"] == "Nutzer"
         and not rows["c:call-2"]["changed"] and rows["c:call-2"]["group"] == "hermes", str(rows["c:call-2"]))
    step("Guardian", rows["c:call-3"]["decider"] == "Guardian"
         and rows["c:call-3"]["decisionLabel"] == "Vom Guardian abgelehnt", str(rows["c:call-3"]))
    step("Zeitüberschreitung", rows["c:call-4"]["decision"] == "timeout"
         and rows["c:call-4"]["status"] == "denied", str(rows["c:call-4"]))

    # 5. Cron: kein Freigabe-Hook, nur das blockierte Ergebnis
    audit.record_flagged({"group": "image"}, {"command": "sudo bootc upgrade"}, tool_call_id="call-5")
    msg = ("BLOCKED: Tool 'terminal' requires approval (…) but cron jobs run without a user present to approve it. "
           "Find an alternative approach. To allow flagged actions in cron jobs, set approvals.cron_mode: approve")
    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": "sudo bootc upgrade"},
                                result=json.dumps({"error": msg}), tool_call_id="call-5",
                                status="blocked", error_type="plugin_block", error_message=msg)
    # 6. gespeicherte Freigabe (session/always): Ergebnis ohne Freigabe-Hook, Exit 1
    audit.record_flagged({"group": "services"}, {"command": "sudo systemctl restart foo"}, tool_call_id="call-6")
    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": "sudo systemctl restart foo"},
                                result=json.dumps({"output": "Failed to restart foo.service: Unit not found.",
                                                   "exit_code": 5}), tool_call_id="call-6", status="ok")
    # 7. Rückfall ohne vorherigen pre_tool_call (andere Aufruf-Kennung) über classify
    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": "systemctl restart bar"},
                                result=json.dumps({"output": "", "exit_code": 0}), tool_call_id="call-7")
    # 8. freier Befehl: kein Eintrag
    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": "ls -la ~"},
                                result=json.dumps({"output": "x", "exit_code": 0}), tool_call_id="call-8")
    # 9. app_launch
    ctx.hooks["post_tool_call"](tool_name="app_launch", args={"app_id": "org.mozilla.firefox"},
                                result="Gestartet: org.mozilla.firefox (/usr/share/applications/x.desktop).",
                                tool_call_id="call-9", duration_ms=30)
    rows = {r["id"]: r for r in audit.load_rows()}
    step("Cron-Verweigerung", rows["c:call-5"]["decider"] == "Cron-Verweigerung"
         and rows["c:call-5"]["status"] == "denied" and rows["c:call-5"]["group"] == "image", str(rows["c:call-5"]))
    step("gespeicherte Freigabe mit Fehler-Exit",
         rows["c:call-6"]["decision"] == "preapproved" and rows["c:call-6"]["status"] == "error"
         and rows["c:call-6"]["exitCode"] == 5 and rows["c:call-6"]["changed"], str(rows["c:call-6"]))
    step("Rückfall über classify", "c:call-7" in rows and rows["c:call-7"]["group"] == "services")
    step("freier Befehl bleibt draußen", "c:call-8" not in rows)
    step("app_launch", rows.get("c:call-9", {}).get("kind") == "app" and rows["c:call-9"]["status"] == "launched"
         and rows["c:call-9"]["command"] == "org.mozilla.firefox" and not rows["c:call-9"]["changed"],
         str(rows.get("c:call-9")))

    # Kaputte Zeilen: abgebrochenes Schreiben, Unsinn, JSON ohne Zeitstempel
    with open(path, "ab") as f:
        f.write(b'{"v":1,"ts":17\n\xff\xfe kaputt\n[1,2]\n{"kind":"app.launch"}\n')
    before = len(audit.load_rows())
    ok = audit.append({"kind": "app.launch", "call": "call-10", "command": "org.kde.dolphin", "status": "ok"})
    step("kaputte Zeilen werden übergangen, danach geht es weiter", ok and len(audit.load_rows()) == before + 1,
         f"{before} -> {len(audit.load_rows())}")

    # Filter: Änderungen und Zeitraum
    changed = audit.load_rows(changes_only=True)
    step("Filter nur Änderungen", sorted(r["id"] for r in changed) == ["c:call-1", "c:call-6", "c:call-7"],
         str([r["id"] for r in changed]))
    old = {"kind": "command.result", "call": "alt", "command": "sudo bootc upgrade", "group": "image",
           "status": "ok", "exit_code": 0}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"v": 1, "ts": time.time() - 3 * 86400, **old}) + "\n")
        f.write(json.dumps({"v": 1, "ts": time.time() - 30 * 86400, **dict(old, call="uralt")}) + "\n")
    ids = lambda period: {r["id"] for r in audit.load_rows(period)}  # noqa: E731
    step("Zeitraum heute / 7 Tage / alles",
         "c:alt" not in ids("today") and "c:alt" in ids("week") and "c:uralt" not in ids("week")
         and "c:uralt" in ids("all"), "")
    rows = audit.load_rows()
    step("neueste zuerst", [r["ts"] for r in rows] == sorted((r["ts"] for r in rows), reverse=True))

    # Export
    text = audit.export_text(audit.load_rows("all", True), "all", True)
    step("Export-Text", text.startswith("Protokoll von Hermes auf ") and "nur Änderungen am System" in text
         and f"$ {cmd}" in text and "Einmal erlaubt (Nutzer im Leisten-Symbol)  Ausgeführt, Exit 0" in text
         and "  | Failed to restart foo.service" in text and "org.mozilla.firefox" not in text, text[:600])
    target = os.path.join(tmp, "export.txt")
    err = audit.write_export(target, audit.load_rows(), "today", False)
    step("Export in Datei", err == "" and "Zeitraum: Heute; alle Einträge" in open(target, encoding="utf-8").read(), err)
    err = audit.write_export(os.path.join(tmp, "fehlt", "x.txt"), [], "all", False)
    step("Export-Fehler lesbar", err.startswith("Export fehlgeschlagen"), err)

    # Schwärzen und Kürzen
    audit.record_flagged({"group": "users"}, {"command": "echo 'nutzer:Geheim1' | sudo chpasswd --password=Geheim1"},
                         tool_call_id="call-11")
    ctx.hooks["post_tool_call"](tool_name="terminal",
                                args={"command": "echo x | sudo chpasswd password=Geheim1"},
                                result=json.dumps({"output": "Authorization: Bearer abcdefghijklmnop\n" + "z" * 5000,
                                                   "exit_code": 0}), tool_call_id="call-11")
    raw = path.read_bytes().decode("utf-8", "replace")
    row = {r["id"]: r for r in audit.load_rows()}["c:call-11"]
    step("Geheimnisse geschwärzt", "Geheim1" not in raw and "abcdefghijklmnop" not in raw, "")
    step("Ausgabe gekürzt", len(row["output"]) <= audit.MAX_OUTPUT + 3 and "…" in row["output"], str(len(row["output"])))

    # Rotation: ab MAX_BYTES wird die Datei zur Vorgängerdatei, eine davon bleibt
    small = Path(tmp) / "rot" / "audit.jsonl"
    for i in range(60):
        audit.append({"kind": "app.launch", "call": f"r{i}", "command": "x" * 50, "status": "ok"}, small, max_bytes=2000)
    prev = audit.previous_path(small)
    files = sorted(p.name for p in small.parent.iterdir() if not p.name.endswith(".lock"))
    step("Rotation mit einer Vorgängerdatei", files == ["audit.jsonl", "audit.jsonl.1"]
         and small.stat().st_size <= 2000 and prev.stat().st_size <= 2000, str(files))
    got = [e["call"] for e in audit.read_events(small)]
    step("nach Rotation lesbar, lückenlos bis zur Grenze", got == [f"r{i}" for i in range(60 - len(got), 60)]
         and len(got) >= 15, f"{len(got)} Ereignisse")
    step("Vorgängerdatei 0600", stat.S_IMODE(prev.stat().st_mode) == 0o600)

    # Schreiben wirft nie, auch wenn der Ort nicht beschreibbar ist
    blocker = Path(tmp) / "datei"
    blocker.write_text("x")
    step("Schreibfehler bleibt still", audit.append({"kind": "app.launch"}, blocker / "audit.jsonl") is False)

    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
