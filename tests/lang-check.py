#!/usr/bin/python3
# =============================================================================
# hermes-os -- Sprache der Oberfläche prüfen: Deutsch ab Werk, Englisch in
# englischer Sitzung (tray/lang.py, plugins/hermes_os/lang.py, docs/systemagent.md)
# =============================================================================
#   1. Beide lang.py entscheiden gleich: is_english ist Code-Kopie, dazu eine
#      Matrix aus HERMES_OS_LANG, LANGUAGE, LC_ALL, LC_MESSAGES und LANG.
#   2. _() in beiden Sprachen; unbekannter Text bleibt; Platzhalter ({feld}, %1,
#      strftime, Backticks, Tags) in Schlüssel und Übersetzung gleich.
#   3. Abdeckung: jedes qsTr in Main.qml und jedes _("…") in den Modulen ist ein
#      EN-Schlüssel, ebenso die deutschen Konstanten (Zustände, Labels); kein
#      sichtbares Literal in Main.qml ohne qsTr (Heuristik); keine Funktion ruft
#      _() und bindet zugleich _ (sonst UnboundLocalError).
#   4. Python auf Englisch: Grenze (Backticks bleiben), Protokoll, KRunner,
#      Modellknopf, Push-to-Talk, Ausschnitt, Dauer und Datum im Verlauf.
#   5. Qt (SKIP ohne PySide6): die echte Main.qml mit den Stubs aus
#      tray-gui-check.py, ohne Übersetzer deutsch, mit DictTranslator englisch,
#      danach wieder deutsch; keine QML-Warnung; Datum nach setlocale.
#
# Aufruf:
#   tests/lang-check.py [--tray-dir D] [--plugin-dir D] [--tests-dir D] [--tray-bin F]
# Exit 0 = alles sauber. Teil 1 bis 4 laufen überall mit Python 3, auch unter
# Windows; Teil 5 braucht PySide6 und Kirigami (Image-Build, Test-VM).
# =============================================================================
import argparse
import ast
import datetime
import importlib.util
import os
import re
import sys
import symtable
import tempfile
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []
# Keine .pyc schreiben: im Gate lägen sie sonst unter /usr (auch /usr/libexec/__pycache__
# für hermes-os-tray, das hier über einen SourceFileLoader geladen wird)
sys.dont_write_bytecode = True

# Nichts aus der Umgebung des Aufrufers: jede Prüfung setzt die Sprache selbst
for _var in ("HERMES_OS_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    os.environ.pop(_var, None)


def check(ok, label, detail=""):
    if ok:
        print(f"OK    {label}")
    else:
        FAILS.append(label)
        print(f"FEHL  {label}" + (f": {detail}" if detail else ""))


def lang_set(value):
    os.environ["HERMES_OS_LANG"] = value


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_script(name, path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def read(path):
    return Path(path).read_text(encoding="utf-8")


# ---- Teil 1: gleiche Entscheidung ------------------------------------------------------
MATRIX = [
    ({}, False),
    ({"LANG": "en_US.UTF-8"}, True),
    ({"LANG": "de_DE.UTF-8", "HERMES_OS_LANG": "en"}, True),
    ({"LANG": "en_US.UTF-8", "HERMES_OS_LANG": "de"}, False),
    ({"LANGUAGE": "en_US:de"}, True),
    ({"LANGUAGE": "de", "LANG": "en_US.UTF-8"}, False),
    ({"LC_ALL": "C.UTF-8", "LANG": "en_US.UTF-8"}, False),
    ({"LC_MESSAGES": "en_GB.UTF-8", "LANG": "de_DE.UTF-8"}, True),
    ({"HERMES_OS_LANG": "EN_us", "LANG": "de_DE.UTF-8"}, True),
    ({"HERMES_OS_LANG": "fr", "LANG": "en_US.UTF-8"}, True),
    ({"LANGUAGE": "", "LC_ALL": "", "LANG": "en_US.UTF-8"}, True),
    ({"LANGUAGE": ":en", "LANG": "de_DE.UTF-8"}, False),
]


def top_level_dump(path, name):
    for node in ast.parse(read(path)).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.dump(node)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return ast.dump(node)
    return None


def part_environment(tray_lang, plugin_lang, tray_path, plugin_path):
    print("== 1. Umgebung: beide lang.py entscheiden gleich ==")
    for name in ("is_english", "_LANG_VARS", "_"):
        a, b = top_level_dump(tray_path, name), top_level_dump(plugin_path, name)
        check(a is not None and a == b, f"{name} ist in tray/lang.py und plugins/hermes_os/lang.py derselbe Code")
    for env, want in MATRIX:
        got = (tray_lang.is_english(env), plugin_lang.is_english(env))
        check(got == (want, want), f"is_english({env}) -> {'en' if want else 'de'}", f"Symbol/Plugin: {got}")
    lang_set("en")
    live_en = (tray_lang.is_english(), plugin_lang.is_english())
    lang_set("de")
    live_de = (tray_lang.is_english(), plugin_lang.is_english())
    check(live_en == (True, True) and live_de == (False, False), "is_english() liest os.environ bei jedem Aufruf")


# ---- Teil 2: _() und Platzhalter ---------------------------------------------------------
def part_translate(tray_lang, plugin_lang):
    print("== 2. _() in beiden Sprachen, Platzhalter ==")
    lang_set("en")
    check(tray_lang._("Senden") == "Send" and tray_lang._("Hermes ist bereit") == "Hermes is ready",
          "Symbol englisch: Senden -> Send, Hermes ist bereit -> Hermes is ready")
    check(plugin_lang._("Abgelehnt") == "Denied" and plugin_lang._("%d.%m.%Y") == "%Y-%m-%d",
          "Plugin englisch: Abgelehnt -> Denied, Datum %Y-%m-%d")
    check(tray_lang._("gibt es nicht 42") == "gibt es nicht 42" and plugin_lang._("") == "",
          "unbekannter Text bleibt, wie er ist")
    lang_set("de")
    check(tray_lang._("Senden") == "Senden" and plugin_lang._("Abgelehnt") == "Abgelehnt",
          "deutsch: _() liefert den Quelltext")
    problems = tray_lang.self_test()
    check(not problems, "tray/lang.self_test ohne Befund (Platzhalter, leere Übersetzungen, Matrix)", "; ".join(problems[:5]))
    problems = tray_lang.check_table(plugin_lang.EN)
    check(not problems, "Plugin-Wörterbuch: Platzhalter gleich, keine leere Übersetzung", "; ".join(problems[:5]))
    shared = {k: (tray_lang.EN[k], plugin_lang.EN[k]) for k in set(tray_lang.EN) & set(plugin_lang.EN)
              if tray_lang.EN[k] != plugin_lang.EN[k]}
    check(not shared, "Schlüssel in beiden Wörterbüchern haben dieselbe Übersetzung", str(shared))
    check(tray_lang.EN.get("fehlgeschlagen") == "failed" and tray_lang.EN.get("nicht verfügbar") == "not available",
          "Schlüsselwörter für die rote Meldung im Protokoll: failed, not available")


# ---- Teil 3: Abdeckung ------------------------------------------------------------------
STR_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
VISIBLE_PROP = re.compile(r'^\s*(?:[\w.]+\.)?(text|placeholderText|title|explanation|label)\s*:|\{\s*text\s*:')
CONTINUATION = ("+", "?", ":", ".", "||", "&&")
ALLOWED_LITERALS = {"Hermes", "Hermes · ", " · ", "  ▾", " "}
IDENTIFIER = re.compile(r"^[a-z][A-Za-z0-9_.-]*$")


def js_unescape(s):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def strip_qml_comments(text):
    """// und /* */ außerhalb von Zeichenketten durch Leerzeichen ersetzen (Zeilen bleiben)."""
    out, i, n, quote = [], 0, len(text), None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote or c == "\n":
                quote = None
            i += 1
        elif c in "\"'":
            quote = c
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def qstr_calls(text):
    """Alle qsTr-Aufrufe: (Zeile, Anfang, Ende, Schlüssel); Schlüssel None, wenn das
    Argument keine Kette aus Literalen mit + ist."""
    out = []
    for m in re.finditer(r"\bqsTr\(", text):
        i, parts, ok = m.end(), [], True
        while True:
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            sm = STR_RE.match(text, i)
            if not sm:
                ok = False
                break
            parts.append(js_unescape(sm.group(1)))
            i = sm.end()
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if text.startswith("+", i):
                i += 1
                continue
            if not text.startswith(")", i):
                ok = False
            break
        out.append((text.count("\n", 0, m.start()) + 1, m.start(), i + 1, "".join(parts) if ok else None))
    return out


def forgotten_literals(text):
    """Heuristik: Literale mit Buchstaben in sichtbaren Eigenschaften, die nicht in
    qsTr stehen. Erlaubt sind Namen wie Hermes und Kennungen (ready, recording)."""
    blank = list(text)
    for _line, start, end, _key in qstr_calls(text):
        for k in range(start, min(end, len(blank))):
            if blank[k] != "\n":
                blank[k] = " "
    lines = "".join(blank).split("\n")
    hits = []
    i = 0
    while i < len(lines):
        if VISIBLE_PROP.search(lines[i]):
            stmt, first = [lines[i]], i + 1
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith(CONTINUATION):
                stmt.append(lines[j])
                j += 1
            for lit in STR_RE.findall("\n".join(stmt)):
                lit = js_unescape(lit)
                if re.search(r"[A-Za-zÄÖÜäöüß]", lit) and lit not in ALLOWED_LITERALS and not IDENTIFIER.match(lit):
                    hits.append((first, lit))
            i = j
        else:
            i += 1
    return hits


def py_underscore_calls(path):
    """(Zeile, Text) je _("…"); Text None bei einem f-String (nie übersetzbar)."""
    out = []
    for node in ast.walk(ast.parse(read(path))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append((node.lineno, arg.value))
            elif isinstance(arg, ast.JoinedStr):
                out.append((node.lineno, None))
    return out


def underscore_shadowing(path):
    """Funktionen, die _ binden und _() rufen, oder _ aus einer umgebenden Funktion
    nehmen: dort wirft _() UnboundLocalError oder ruft den Wegwerfwert."""
    bad = []

    def walk(table):
        kind = getattr(table.get_type(), "value", table.get_type())
        if kind == "function":
            try:
                sym = table.lookup("_")
            except KeyError:
                sym = None
            if sym is not None and ((sym.is_local() and sym.is_referenced()) or sym.is_free()):
                bad.append(f"{table.get_name()} (Zeile {table.get_lineno()})")
        for child in table.get_children():
            walk(child)

    walk(symtable.symtable(read(path), str(path), "exec"))
    # Auf Modulebene darf _ nur einmal gesetzt werden (Import, def oder _ = ...), nicht als Schleifen- oder Tupelziel
    for node in ast.parse(read(path)).body:
        for sub in ast.walk(node) if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else ():
            if isinstance(sub, (ast.For, ast.comprehension)) or (isinstance(sub, ast.Assign) and any(
                    isinstance(t, (ast.Tuple, ast.List)) for t in sub.targets)):
                targets = [sub.target] if isinstance(sub, (ast.For, ast.comprehension)) else sub.targets
                for t in targets:
                    if any(isinstance(x, ast.Name) and x.id == "_" for x in ast.walk(t)):
                        bad.append(f"Modulebene Zeile {getattr(sub, 'lineno', '?')}")
    return bad


def assigned_constants(path, func, name):
    """Literale, die in func der Variablen name zugewiesen werden (Entscheider im Protokoll)."""
    for node in ast.walk(ast.parse(read(path))):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return [n.value.value for n in ast.walk(node) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
                    and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
    return []


def part_coverage(tray_lang, plugin_lang, a):
    print("== 3. Abdeckung: Main.qml, Module, Konstanten ==")
    qml = strip_qml_comments(read(Path(a.tray_dir) / "Main.qml"))
    calls = qstr_calls(qml)
    keys = [k for _l, _s, _e, k in calls if k is not None]
    dynamic = [ln for ln, _s, _e, k in calls if k is None]
    check(len(keys) >= 50, f"Main.qml: {len(keys)} qsTr-Aufrufe gefunden")
    check(not dynamic, "Main.qml: jedes qsTr hat ein Literal (oder mit + verkettete Literale)", f"Zeilen {dynamic}")
    missing = sorted({k for k in keys if k not in tray_lang.EN})
    check(not missing, "Main.qml: jeder qsTr-Text ist ein EN-Schlüssel in tray/lang.py", repr(missing[:8]))
    forgotten = forgotten_literals(qml)
    check(not forgotten, "Main.qml: kein sichtbares Literal ohne qsTr", repr(forgotten[:8]))

    tray_files = [Path(a.tray_bin)] + [Path(a.tray_dir) / f for f in
                                        ("model_choice.py", "voice.py", "screenshot.py", "runner.py", "lang.py")]
    plugin_files = [Path(a.plugin_dir) / f for f in ("boundary.py", "audit.py", "lang.py")]
    for files, table, where in ((tray_files, tray_lang.EN, "tray/lang.py"), (plugin_files, plugin_lang.EN, "plugins/hermes_os/lang.py")):
        for path in files:
            calls = py_underscore_calls(path)
            fstrings = [ln for ln, t in calls if t is None]
            missing = sorted({t for _ln, t in calls if t is not None and t not in table})
            check(not fstrings and not missing,
                  f"{path.name}: {len(calls)} _()-Texte, alle Schlüssel in {where}, kein f-String in _()",
                  f"f-Strings in Zeilen {fstrings}; fehlt: {missing[:6]!r}")
            bad = underscore_shadowing(path)
            check(not bad, f"{path.name}: keine Funktion bindet _ und ruft _()", ", ".join(bad))


def part_constants(tray_lang, plugin_lang, mods):
    tray, mc, voice, screenshot, runner, boundary, audit = mods
    wanted = {
        "hermes-os-tray STATE_TEXT": (tray.STATE_TEXT.values(), tray_lang.EN),
        "hermes-os-tray CHOICE_LABEL": (tray.CHOICE_LABEL.values(), tray_lang.EN),
        "model_choice EFFORTS": ([label for _v, label in mc.EFFORTS] + ["Vorgabe"], tray_lang.EN),
        "voice STATE_TEXT": ([t for t in voice.STATE_TEXT.values() if t], tray_lang.EN),
        "screenshot DEFAULT_QUESTION, NOTIFY_TITLE, DISCUSS_LABEL":
            ((screenshot.DEFAULT_QUESTION, screenshot.NOTIFY_TITLE, screenshot.DISCUSS_LABEL), tray_lang.EN),
        "runner ACTIONS": ([t for _i, t, _icon in runner.ACTIONS], tray_lang.EN),
        "boundary _GROUP_TEXT": (list(boundary._GROUP_TEXT.values()) + ["berührt das laufende System"], plugin_lang.EN),
        "audit PERIOD_LABEL, GROUP_LABEL, DECISION_LABEL, STATUS_LABEL":
            ([t for d in (audit.PERIOD_LABEL, audit.GROUP_LABEL, audit.DECISION_LABEL, audit.STATUS_LABEL)
              for t in d.values() if t], plugin_lang.EN),
        "audit Entscheider": (assigned_constants(Path(audit.__file__), "_finish_row", "decider"), plugin_lang.EN),
    }
    for label, (values, table) in wanted.items():
        values = [v for v in values if v]
        missing = [v for v in values if v not in table]
        check(values and not missing, f"{label}: {len(values)} deutsche Texte, alle mit EN-Eintrag", repr(missing[:5]))


# ---- Teil 4: Python auf Englisch ----------------------------------------------------------
def part_python(mods, hc, pkg):
    tray, mc, voice, screenshot, runner, boundary, audit = mods
    print("== 4. Python auf Englisch (und zurück) ==")
    lang_set("en")
    d = boundary.pre_tool_call_directive("terminal", {"command": "ujust update"}) or {}
    msg = d.get("message", "")
    check(msg == "hermes-os: `ujust update` changes the system image (image). Approval required.",
          "Grenze englisch: Meldung für ujust update, Backticks um den Befehl", repr(msg))
    shown = hc.approval_command("<terminal> (plugin approval rule)", msg)
    check(shown == "ujust update", "Freigabe-Karte liest den Befehl auch aus der englischen Meldung", repr(shown))
    block = (boundary.pre_tool_call_directive("terminal", {"command": "sudo reboot"}) or {}).get("message", "")
    check(block.startswith("hermes-os: `sudo reboot` would restart or power off the computer (power).")
          and block.endswith("The agent never runs this itself. Ask the user to do it."), "Grenze englisch: block", repr(block))
    fc = boundary.fail_closed_directive(RuntimeError("x"))["message"]
    check(fc.startswith("hermes-os: The boundary check failed (RuntimeError). Approval required"), "Grenze englisch: fail-closed", fc)
    if pkg is not None:
        pmsg = (pkg.boundary.pre_tool_call_directive("terminal", {"command": "ujust update"}) or {}).get("message", "")
        check(pkg.boundary._.__module__.endswith(".lang") and pmsg == msg,
              "im Plugin-Paket kommt _ über den relativen Import aus hermes_os.lang", f"{pkg.boundary._.__module__}: {pmsg!r}")

    now = time.time()
    events = [
        {"ts": now - 30, "kind": "approval.request", "call": "c1", "command": "sudo systemctl restart sshd",
         "raw_command": "<terminal> (plugin approval rule)", "group": "services"},
        {"ts": now - 29, "kind": "tray.decision", "command": "sudo systemctl restart sshd", "choice": "deny"},
        {"ts": now - 28, "kind": "approval.decision", "call": "c1", "choice": "deny", "group": "services",
         "command": "sudo systemctl restart sshd"},
        {"ts": now - 20, "kind": "approval.decision", "call": "c2", "choice": "once", "group": "image",
         "command": "sudo bootc upgrade"},
        {"ts": now - 19, "kind": "command.result", "call": "c2", "command": "sudo bootc upgrade", "group": "image",
         "status": "ok", "exit_code": 0},
        {"ts": now - 10, "kind": "approval.decision", "call": "c3", "choice": "smart_deny", "group": "hermes",
         "command": "rm -rf /etc/foo"},
    ]

    def row_line(r):
        # wie Main.qml die Zeile zusammensetzt
        return " · ".join(t for t in (r["decisionLabel"] + (f" ({r['decider']})" if r["decider"] else ""),
                                      r["resultText"]) if t)

    rows = {r["id"]: r for r in audit.build_rows(events)}
    got = [row_line(rows.get(k, {"decisionLabel": "", "decider": "", "resultText": "?"})) for k in ("c:c1", "c:c2", "c:c3")]
    check(got == ["Denied (user in tray icon) · Not executed", "Allowed once (user) · Executed, exit 0",
                  "Denied by Guardian (Guardian) · Not executed"], "Protokoll englisch: Entscheidung, Entscheider, Ergebnis", repr(got))
    en_date = datetime.datetime.fromtimestamp(now - 19).strftime("%Y-%m-%d")
    check(rows["c:c2"]["date"] == en_date and rows["c:c1"]["groupLabel"] == "System services",
          "Protokoll englisch: Datum %Y-%m-%d, Gruppe", f"{rows['c:c2']['date']} {rows['c:c1']['groupLabel']}")
    text = audit.export_text(list(rows.values()), "today", False)
    check(text.startswith("Hermes log on ") and "Period: Today; all entries; 3 entries" in text,
          "Protokoll englisch: Kopf des Exports", text.splitlines()[:2])
    err = audit.write_export(os.path.join(tempfile.mkdtemp(prefix="lang-check-"), "fehlt", "x.txt"), [], "all")
    check("failed" in err, "Protokoll englisch: Exportfehler enthält „failed“ (rote Meldung)", err)

    m = runner.build_matches("hermes Wie spät ist es?")
    check(m and m[0][1] == "Ask Hermes: Wie spät ist es?" and m[0][5]["subtext"] == "Enter: ask in the Kontor",
          "KRunner englisch: Treffer und Untertitel", repr(m[:1]))
    acts = runner.Runner(lambda q: None, lambda q: None).actions()
    check(acts == [(runner.ACTION_LOOKUP, "Look up only", "system-search")] and runner.ACTIONS[0][1] == "Nur nachschlagen",
          "KRunner englisch: Aktion „Look up only“, Konstante bleibt deutsch", repr(acts))

    check(mc.button_text({"model": "openai/gpt-5.6", "effort": ""}, []) == "gpt-5.6 · Default"
          and mc.effort_label("xhigh") == "very thorough" and mc.model_label("", []) == "no model",
          "Modellknopf englisch: gpt-5.6 · Default, very thorough, no model (model_choice über den Pfad geladen)")

    notes = []

    class Actions:
        def start_recording(self):
            return False, ""

        def notify(self, title, body):
            notes.append((title, body))

        def state_changed(self, state):
            pass

    voice.PushToTalk(Actions()).press()
    check(notes == [("Hermes cannot listen", "Recording is not possible.")], "Push-to-Talk englisch: Benachrichtigung", repr(notes))
    spoken = voice.speech_text("Vorher ```x = 1``` nachher")
    check("Code block skipped." in spoken, "Vorlesen englisch: Codeblock", spoken)
    r = voice.Worker(python=os.path.join(tempfile.gettempdir(), "gibt-es-nicht", "python"), script="x").request("transcribe", 2)
    check(not r.get("ok") and r.get("error", "").startswith("Speech helper does not start"), "Sprachhelfer englisch: Startfehler", repr(r))

    asked, shown_notes = [], []
    flow = screenshot.LookFlow(tempfile.gettempdir(), lambda p: ("ok", p), lambda p: "", lambda: None,
                               lambda *x: (True, ""), lambda: True, lambda p, q: asked.append(q),
                               lambda *x: None, lambda t, b: shown_notes.append(t), lambda *x: None)
    flow.run("", to_window=True)
    check(asked and asked[0].startswith("What am I looking at here?"), "Ausschnitt englisch: Standardfrage im Eingabefeld", repr(asked))
    status, detail = screenshot.capture_region(os.path.join(tempfile.gettempdir(), "x.png"), which=lambda n: None)
    check((status, detail) == ("error", "Spectacle is not installed."), "Ausschnitt englisch: Spectacle fehlt", detail)

    stamp = datetime.datetime(2020, 10, 3, 18, 31).timestamp()
    check(tray.tool_duration(0.3) == "0.3 s" and tray.tool_duration(65) == "1 min 5 s" and tray.tool_duration(None) == "done",
          "Verlauf englisch: Dauer 0.3 s, 1 min 5 s, done", f"{tray.tool_duration(0.3)} {tray.tool_duration(None)}")
    check(tray.format_time(stamp) == "Oct 03 18:31", "Verlauf englisch: Datum „Oct 03 18:31“", tray.format_time(stamp))

    lang_set("de")
    d = boundary.pre_tool_call_directive("terminal", {"command": "ujust update"}) or {}
    check(d.get("message") == "hermes-os: `ujust update` ändert das System-Image (image). Freigabe nötig.",
          "Grenze deutsch: Meldung wie bisher", repr(d.get("message")))
    rows = {r["id"]: r for r in audit.build_rows(events)}
    check(row_line(rows["c:c1"]) == "Abgelehnt (Nutzer im Leisten-Symbol) · Nicht ausgeführt"
          and row_line(rows["c:c2"]) == "Einmal erlaubt (Nutzer) · Ausgeführt, Exit 0"
          and rows["c:c2"]["date"] == datetime.datetime.fromtimestamp(now - 19).strftime("%d.%m.%Y"),
          "Protokoll deutsch: wie bisher", f"{row_line(rows['c:c1'])} | {rows['c:c2']['date']}")
    check(runner.build_matches("h: x")[0][1] == "Hermes fragen: x" and mc.button_text({"model": "a", "effort": "high"}, [])
          == "a · gründlich", "KRunner und Modellknopf deutsch: wie bisher")
    check(tray.tool_duration(0.3) == "0,3 s" and tray.tool_duration(None) == "fertig" and tray.format_time(stamp) == "03.10. 18:31",
          "Verlauf deutsch: 0,3 s, fertig, 03.10. 18:31")


# ---- Teil 5: Übersetzer an der echten Main.qml --------------------------------------------
def part_qt(tray_lang, audit, tray, a):
    print("== 5. Qt: Übersetzer an der echten Main.qml ==")
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print("SKIP  PySide6 fehlt: Main.qml und Übersetzer nicht geprüft (läuft im Image-Build und in der VM)")
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Deutsche Locale für setlocale in QGuiApplication, Oberfläche per HERMES_OS_LANG
    os.environ["LANG"] = "de_DE.UTF-8"
    os.environ.pop("LC_TIME", None)
    tgc = load("tray_gui_check_for_lang", Path(a.tests_dir) / "tray-gui-check.py")
    from PySide6.QtCore import QDeadlineTimer, QObject, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    warnings = []

    def handler(mode, ctx, msg):
        if any(s in msg for s in tgc.IGNORE):
            return
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) and ".qml" in msg:
            warnings.append(msg)

    qInstallMessageHandler(handler)
    QQuickStyle.setStyle("org.kde.desktop")
    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    tgc.use_tray_dir(a.tray_dir)
    backend, voice, look = tgc.StubBackend(), tgc.StubVoice(), tgc.StubLook()
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", backend)
    ctx.setContextProperty("voice", voice)
    ctx.setContextProperty("look", look)
    engine.load(os.path.join(a.tray_dir, "Main.qml"))
    if not engine.rootObjects():
        check(False, "Main.qml lädt", "; ".join(warnings[:3]))
        return
    root = engine.rootObjects()[0]

    def settle(ms=300):
        deadline = QDeadlineTimer(ms)
        while not deadline.hasExpired():
            app.processEvents()
            app.sendPostedEvents()

    def prop(name, key):
        obj = root.findChild(QObject, name) or root.findNamed(name, None)
        return obj.property(key) if obj is not None else f"<{name} fehlt>"

    def texts():
        pills = root.property("suggestions")
        pills = pills.toVariant() if hasattr(pills, "toVariant") else pills   # QML-Array kommt als QJSValue
        return {
            "title": root.property("title"),
            "send": prop("sendButton", "text"),
            "placeholder": prop("inputField", "placeholderText"),
            "once": prop("approveOnce", "text"),
            "heading": prop("approvalTitle", "text"),
            "count": prop("auditCount", "text"),
            "today": prop("auditList", "today"),
            "pill": list(pills or [])[:1],
        }

    backend.set_state("ready", configured=True)
    settle()
    de_today = datetime.date.today().strftime("%d.%m.%Y")
    got = texts()
    check(got["title"] == "Hermes-Kontor" and got["send"] == "Senden" and got["placeholder"] == "Frag Hermes …"
          and got["once"] == "Einmal erlauben" and got["count"] == "0 Einträge" and got["today"] == de_today,
          "ohne Übersetzer deutsch: Hermes-Kontor, Senden, Frag Hermes …, 0 Einträge, heute dd.MM.yyyy", repr(got))

    lang_set("en")
    translator = tray_lang.DictTranslator(app)
    check(not translator.isEmpty() and translator.translate("Main", "gibt es nicht") is None
          and translator.translate("Main", "Senden") == "Send", "DictTranslator: nicht leer, unbekannt heißt None")
    installed = app.installTranslator(translator)
    # Unbekanntes muss beim Quelltext bleiben: "" würde Qt-eigene Menüs (Cut, Copy, Paste) leeren
    check(bool(type(app).translate("QFileDialog", "Open")) and type(app).translate("Main", "Senden") == "Send",
          "mit Übersetzer: Qt-eigene Texte bleiben erhalten, bekannte werden übersetzt",
          repr(type(app).translate("QFileDialog", "Open")))
    engine.retranslate()
    settle()
    got = texts()
    en_today = audit.build_rows([{"ts": time.time(), "kind": "approval.request", "call": "t"}])[0]["date"]
    check(installed and got["title"] == "Hermes Kontor" and got["send"] == "Send" and got["placeholder"] == "Ask Hermes …"
          and got["once"] == "Allow once" and got["heading"] == "Hermes asks for approval" and got["count"] == "0 entries"
          and got["pill"] == ["Which image is booted?"],
          "mit Übersetzer englisch: Hermes Kontor, Send, Ask Hermes …, Allow once, Hermes asks for approval, 0 entries",
          repr(got))
    check(got["today"] == en_today, "englisch: heute im Protokoll wie das Datum aus audit.py", f"{got['today']} / {en_today}")
    stamp = datetime.datetime(2020, 10, 3, 18, 31).timestamp()
    check(tray.format_time(stamp) == "Oct 03 18:31", "englisch nach setlocale (QGuiApplication, LANG=de_DE): Oct 03 18:31",
          tray.format_time(stamp))

    app.removeTranslator(translator)
    engine.retranslate()
    settle()
    lang_set("de")
    got = texts()
    check(got["title"] == "Hermes-Kontor" and got["send"] == "Senden" and got["today"] == de_today,
          "Übersetzer entfernt: wieder deutsch", repr(got))
    check(not warnings, "keine QML-Warnung", "; ".join(warnings[:5]))
    root.close()


def main():
    tray_default = REPO / "files/system/usr/share/hermes-os/tray"
    ap = argparse.ArgumentParser()
    ap.add_argument("--tray-dir", default=str(tray_default))
    ap.add_argument("--plugin-dir", default=str(REPO / "files/system/usr/share/hermes-os/plugins/hermes_os"))
    ap.add_argument("--tests-dir", default=str(HERE))
    ap.add_argument("--tray-bin", default="", help="hermes-os-tray; Vorgabe: libexec neben dem tray-Ordner")
    a = ap.parse_args()
    if not a.tray_bin:
        a.tray_bin = str(Path(a.tray_dir).resolve().parent.parent.parent / "libexec" / "hermes-os-tray")
    tray_path, plugin_path = Path(a.tray_dir) / "lang.py", Path(a.plugin_dir) / "lang.py"
    tray_lang = load("lang_check_tray_lang", tray_path)
    plugin_lang = load("lang_check_plugin_lang", plugin_path)

    part_environment(tray_lang, plugin_lang, tray_path, plugin_path)
    part_translate(tray_lang, plugin_lang)

    # Über den Pfad wie in den Tests der Module: model_choice, boundary und audit müssen
    # lang.py ohne sys.path finden
    mc = load("lang_check_model_choice", Path(a.tray_dir) / "model_choice.py")
    boundary = load("lang_check_boundary", Path(a.plugin_dir) / "boundary.py")
    audit = load("lang_check_audit", Path(a.plugin_dir) / "audit.py")
    os.environ.update(HERMES_OS_TRAY_DIR=a.tray_dir, HERMES_OS_AUDIT_PY=str(Path(a.plugin_dir) / "audit.py"),
                      HERMES_OS_LIBRARY_PY=str(Path(a.plugin_dir) / "library.py"))
    tray = load_script("lang_check_hermes_os_tray", a.tray_bin)     # legt tray/ auf sys.path, main() läuft nicht
    import hermes_client as hc
    import runner
    import screenshot
    import voice
    try:
        sys.path.insert(0, str(Path(a.plugin_dir).parent))
        import hermes_os as pkg
    except Exception as exc:  # noqa: BLE001
        check(False, "Plugin-Paket hermes_os lädt", str(exc))
        pkg = None
    mods = (tray, mc, voice, screenshot, runner, boundary, audit)

    part_coverage(tray_lang, plugin_lang, a)
    part_constants(tray_lang, plugin_lang, mods)
    part_python(mods, hc, pkg)
    part_qt(tray_lang, audit, tray, a)

    print()
    print("ERGEBNIS: " + ("ok" if not FAILS else f"Fehler ({len(FAILS)}), siehe FEHL"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
