#!/usr/bin/python3
# =============================================================================
# hermes-os -- Bibliothek des Plugins prüfen: Ablage, Zuordnung, Abrufer
# =============================================================================
# Lädt plugins/hermes_os/library.py über seinen Pfad (ohne Hermes, ohne Qt),
# legt Einträge in einem Wegwerf-XDG_CONFIG_HOME an und holt Seiten von einem
# nachgebauten Webserver auf 127.0.0.1: HTML zu Text mit Überschriften und
# Verweisen, Cache, Neuladen, Stückelung, fremde Hosts abgewiesen, Dateien und
# Ordner nur unter Einträgen, Prompt-Abschnitt.
#
# Ohne Netz nach draußen. Läuft mit jedem Python 3.9+:
#   tests/library-check.py [--plugin-dir DIR]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7g) führt ihn
# im Image-Build aus, `make lint` ebenso.
# =============================================================================
import argparse
import importlib.util
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Dolphin-Handbuch</title>
<script>alert('nicht lesen')</script><style>p{color:red}</style></head>
<body><nav><a href="/de/dolphin/index.html">Startseite</a></nav>
<h1>Versteckte Dateien</h1><p>Mit <b>Alt+.</b> zeigt Dolphin versteckte&nbsp;Dateien.</p>
<ul><li>Erstens</li><li>Zweitens</li></ul>
<p>Siehe <a href="kapitel2.html">Kapitel 2</a> und <a href="https://fremd.example/x">fremde Seite</a>.</p>
<img alt="Bildschirmfoto"></body></html>"""


class FakeSite(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        FakeSite.hits.append(self.path)
        if self.path in ("/", "/de/dolphin/", "/de/dolphin/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/de/dolphin/kapitel2.html":
            self._send(200, "<html><title>Kapitel 2</title><body><p>Zweites Kapitel.</p></body></html>", "text/html")
        elif self.path == "/notiz.txt":
            self._send(200, "Nur Text.\n" * 3, "text/plain; charset=utf-8")
        elif self.path == "/bild.png":
            self._send(200, b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png")
        else:
            self._send(404, "weg", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-dir", default=os.environ.get("HERMES_OS_PLUGIN_DIR", "/usr/share/hermes-os/plugins/hermes_os"))
    args = ap.parse_args()
    module_path = os.path.join(args.plugin_dir, "library.py")
    if not os.path.isfile(module_path):
        print(f"FEHL  {module_path} fehlt")
        return 1

    fail = 0

    def check(ok, label, detail=""):
        nonlocal fail
        if ok:
            print(f"OK    {label}")
        else:
            fail = 1
            print(f"FEHL  {label}" + (f": {detail}" if detail else ""))

    tmp = tempfile.mkdtemp(prefix="hermes-lib-")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
    os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
    spec = importlib.util.spec_from_file_location("hermes_os_library", module_path)
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSite)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, name="fake-site", daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        # Ablage: leer, anlegen, Kennungen, Dopplung, Unsinn
        check(lib.load_entries() == [], "leere Bibliothek ohne Datei")
        check("leer" in lib.prompt_section().lower(), "Prompt-Abschnitt sagt, dass die Bibliothek leer ist")
        docs = Path(tmp, "unterlagen")
        docs.mkdir()
        Path(docs, "README.md").write_text("# Handbuch\n\nInhalt.\n", encoding="utf-8")
        Path(docs, ".versteckt").write_text("x", encoding="utf-8")
        Path(docs, "bin.dat").write_bytes(b"\x00\x01\x02" * 10)
        outside = Path(tmp, "fremd.txt")
        outside.write_text("nicht eingetragen", encoding="utf-8")
        e1, err1 = lib.add_entry(base + "/de/dolphin/", "KDE-Handbücher", "deutsch unter de/")
        e2, err2 = lib.add_entry(str(docs), "", "eigene Unterlagen")
        e3, err3 = lib.add_entry(str(Path(docs, "README.md")), "Das Handbuch", "")
        check(e1 and e2 and e3 and not (err1 or err2 or err3),
              "drei Einträge angelegt: Adresse, Ordner, Datei", f"{err1} {err2} {err3}")
        check(e1 and e1["kind"] == "url" and e1["id"] == "127-0-0-1" and e2["kind"] == "folder"
              and e2["title"] == "unterlagen" and e3["kind"] == "file" and e3["id"] == "readme-md",
              "Arten erkannt, Kennung und Titel abgeleitet", f"{e1} {e2} {e3}")
        dup, derr = lib.add_entry(base + "/de/dolphin/")
        bad, berr = lib.add_entry("/gibt/es/nicht")
        ftp, ferr = lib.add_entry("ftp://x/y")
        check(dup is None and "Schon" in derr and bad is None and ftp is None,
              "Dopplung, fehlender Pfad und ftp werden abgewiesen", f"{derr} | {berr} | {ferr}")
        entries = lib.load_entries()
        check(len(entries) == 3 and json.load(open(lib.config_path(), encoding="utf-8"))["version"] == 1,
              "bibliothek.json mit Version und drei Einträgen", str(lib.config_path()))
        listing = lib.handle_library_list({})
        check("127-0-0-1" in listing and "readme-md" in listing and "eigene Unterlagen" in listing,
              "library_list nennt Kennungen und Notizen", listing)
        section = lib.prompt_section()
        check("3 Wissensquellen" in section and "library_fetch" in section and "Fremdtext" in section,
              "Prompt-Abschnitt mit Einträgen und Regeln", section[:200])

        # Abrufen: Kennung, HTML zu Text, Verweise nur vom eigenen Host, Skript weg
        out = lib.handle_library_fetch({"target": "127-0-0-1"})
        check("Dolphin-Handbuch" in out and "# Versteckte Dateien" in out and "Alt+. zeigt Dolphin versteckte Dateien" in out
              and "- Erstens" in out and "[Bild: Bildschirmfoto]" in out and "alert" not in out and "color:red" not in out,
              "HTML zu Text: Titel, Überschrift, Absatz, Liste, Bild-Alt; Skript und Stil weg", out[:400])
        check("kapitel2.html" in out and "fremd.example" not in out and "Fremdtext beginnt" in out
              and "frisch geholt" in out and "Notiz des Nutzers: deutsch unter de/" in out,
              "Verweise nur vom eigenen Host, Fremdtext-Markierung, Notiz", out[-400:])
        hits_before = len(FakeSite.hits)
        out2 = lib.handle_library_fetch({"target": base + "/de/dolphin/"})
        check(len(FakeSite.hits) == hits_before and "aus dem Cache" in out2, "zweiter Abruf kommt aus dem Cache")
        out3 = lib.handle_library_fetch({"target": base + "/de/dolphin/", "refresh": True})
        check(len(FakeSite.hits) == hits_before + 1 and "frisch geholt" in out3, "refresh holt neu")
        out4 = lib.handle_library_fetch({"target": base + "/de/dolphin/kapitel2.html"})
        check("Zweites Kapitel" in out4, "Verweis auf demselben Host lässt sich holen", out4[:200])
        out5 = lib.handle_library_fetch({"target": base + "/notiz.txt"})
        check("keinem Eintrag" in out5, "Adresse außerhalb des Pfadanfangs wird abgewiesen", out5[:200])
        out6 = lib.handle_library_fetch({"target": "https://fremd.example/x"})
        check("keinem Eintrag" in out6, "fremder Host wird abgewiesen", out6[:200])
        piece = lib.handle_library_fetch({"target": "127-0-0-1", "start": 2, "max_chars": 60})
        check("Zeichen 2 bis 62 von" in piece and "weiter mit start=62" in piece, "Stückelung mit start und max_chars", piece[:300])
        try:
            lib.fetch_url(base + "/bild.png")
            check(False, "PNG wird als nicht lesbar gemeldet", "kein Fehler")
        except lib.LibraryError as exc:
            check("Inhaltstyp image/png" in str(exc), "PNG wird als nicht lesbar gemeldet", str(exc))

        # Dateien und Ordner
        out7 = lib.handle_library_fetch({"target": "readme-md"})
        check("# Handbuch" in out7 and "Datei, Eintrag readme-md" in out7, "Datei-Eintrag lesen", out7[:200])
        out8 = lib.handle_library_fetch({"target": "unterlagen"})
        check("README.md" in out8 and "bin.dat" in out8 and ".versteckt" not in out8 and "Ordner" in out8,
              "Ordner-Eintrag liefert die Dateiliste ohne versteckte Einträge", out8[:300])
        out9 = lib.handle_library_fetch({"target": str(Path(docs, "README.md"))})
        check("Inhalt." in out9, "Datei unter einem Ordner per Pfad lesen", out9[:200])
        out10 = lib.handle_library_fetch({"target": str(Path(docs, "bin.dat"))})
        check("Binärdatei" in out10, "Binärdatei wird abgewiesen", out10[:200])
        out11 = lib.handle_library_fetch({"target": str(outside)})
        check("keinem Eintrag" in out11, "Datei außerhalb der Einträge wird abgewiesen", out11[:200])
        out12 = lib.handle_library_fetch({"target": ""})
        check("Ziel fehlt" in out12, "leeres Ziel wird gemeldet", out12)

        # Entfernen
        check(lib.remove_entry("readme-md") and not lib.remove_entry("readme-md") and len(lib.load_entries()) == 2,
              "Eintrag entfernen, zweites Entfernen meldet False")
        out13 = lib.handle_library_fetch({"target": str(Path(docs, "README.md"))})
        check("Inhalt." in out13, "Datei bleibt über den Ordner-Eintrag lesbar", out13[:120])
    finally:
        server.shutdown()
        server.server_close()

    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
