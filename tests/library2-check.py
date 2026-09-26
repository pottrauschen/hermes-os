#!/usr/bin/python3
# =============================================================================
# hermes-os -- Bibliothek, Stufe zwei: Spiegel, Index, Suche, MCP-Schalter
# =============================================================================
# Lädt plugins/hermes_os/library.py über seinen Pfad (ohne Hermes, ohne Qt) und
# spielt gegen einen nachgebauten Webserver auf 127.0.0.1 durch: Spiegel einer
# Adresse mit Tiefe, Seitenlimit, robots.txt, Pausen, fremden Hosts und
# Fehlern, Abbruch mit Fortschritt, Ordner und Datei im Index, Volltextsuche
# mit FTS5 (Ausschnitt, Eintrag-Filter, deutsche Schreibweisen, Wortfolge),
# die LIKE-Suche als Rückfall, die Werkzeugtexte, der Prompt-Abschnitt und
# die Schalter für context7 und deepwiki gegen eine Wegwerf-config.yaml.
#
# Ohne Netz nach draußen. Läuft mit jedem Python 3.9+:
#   tests/library2-check.py [--plugin-dir DIR] [--config-template DATEI]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7g) führt ihn
# im Image-Build mit der Venv-Python des Gateways aus, `make lint` ebenso.
# =============================================================================
import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES = {
    "/": """<html><head><title>Handbuch</title></head><body><h1>Übersicht</h1>
<p>Willkommen im Handbuch.</p>
<a href="/a.html">Fenster</a> <a href="/b.html">Dateien</a> <a href="/sub/c.html">Drucken</a>
<a href="/verboten/x.html">Intern</a> <a href="/bild.png">Bild</a> <a href="https://fremd.example/">fremd</a>
<a href="/weiter.html">weiter</a> <a href="/fehlt.html">fehlt</a> <a href="/a.html#oben">nochmal</a></body></html>""",
    "/a.html": """<html><head><title>Fenster</title></head><body><h1>Fenstergröße</h1>
<p>Die Größe der Fenster ändert man mit der Maus. Herr Müller schrieb das Kapitel.</p>
<a href="/tief1.html">tiefer</a></body></html>""",
    "/tief1.html": """<html><head><title>Tiefe eins</title></head><body><p>Zweite Ebene.</p>
<a href="/tief2.html">noch tiefer</a></body></html>""",
    "/tief2.html": "<html><head><title>Tiefe zwei</title></head><body><p>Dritte Ebene.</p></body></html>",
    "/b.html": """<html><head><title>Dateien</title></head><body><h1>Versteckte Dateien</h1>
<p>Mit Alt+Punkt zeigt Dolphin versteckte Dateien. Das Passwort steht nirgends. Das gilt 100% sicher.</p></body></html>""",
    "/sub/c.html": "<html><head><title>Drucken</title></head><body><p>Drucken geht über den Dialog.</p></body></html>",
    "/verboten/x.html": "<html><head><title>Intern</title></head><body><p>Geheimnis.</p></body></html>",
}
ROBOTS = "User-agent: *\nDisallow: /verboten/\nCrawl-delay: 0\n"


class FakeSite(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype, extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        FakeSite.hits.append(self.path)
        if self.path == "/robots.txt":
            self._send(200, ROBOTS, "text/plain")
        elif self.path in PAGES:
            self._send(200, PAGES[self.path], "text/html; charset=utf-8")
        elif self.path == "/bild.png":
            self._send(200, b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png")
        elif self.path == "/weiter.html":
            port = self.server.server_address[1]
            self._send(302, "", "text/plain", {"Location": f"http://localhost:{port}/a.html"})
        else:
            self._send(404, "weg", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-dir", default=os.environ.get("HERMES_OS_PLUGIN_DIR", "/usr/share/hermes-os/plugins/hermes_os"))
    ap.add_argument("--config-template", default=os.environ.get("HERMES_OS_CONFIG_TEMPLATE", "/usr/share/hermes-os/config.yaml.default"))
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

    tmp = tempfile.mkdtemp(prefix="hermes-lib2-")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
    os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
    os.environ["HERMES_HOME"] = os.path.join(tmp, "hermes")
    spec = importlib.util.spec_from_file_location("hermes_os_library", module_path)
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSite)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, name="fake-site", daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        has_fts = lib.fts_available()
        print(f"      SQLite {sqlite3.sqlite_version}, FTS5 {'vorhanden' if has_fts else 'fehlt, LIKE-Suche'}")

        # Einträge: Adresse, Ordner, Datei
        docs = Path(tmp, "unterlagen")
        Path(docs, "tief").mkdir(parents=True)
        Path(docs, "README.md").write_text("# Handbuch\n\nDie Straße zum Erfolg führt über die Bibliothek.\n", encoding="utf-8")
        Path(docs, "tief", "notiz.txt").write_text("Notiz: Drucker einrichten mit CUPS.\n", encoding="utf-8")
        Path(docs, "bin.dat").write_bytes(b"\x00\x01" * 10)
        Path(docs, ".versteckt.md").write_text("geheim", encoding="utf-8")
        single = Path(tmp, "einzel.txt")
        single.write_text("Einzelne Datei über Tastaturkürzel.\n", encoding="utf-8")
        e_url, _ = lib.add_entry(base + "/", "Handbuch", "Testseite")
        e_dir, _ = lib.add_entry(str(docs), "Unterlagen", "")
        e_file, _ = lib.add_entry(str(single), "", "")
        check(e_url and e_dir and e_file, "drei Einträge angelegt", f"{e_url} {e_dir} {e_file}")
        check(lib.mirror_status_all() == {} and lib.describe_mirror(None).startswith("Kein Spiegel"),
              "ohne Index: kein Stand, describe_mirror sagt es")
        out0 = lib.handle_library_search({"query": "Fenster"})
        check("kein Spiegel" in out0 and "library_mirror" in out0, "Suche ohne Index verweist auf library_mirror", out0)

        # Titel und Notiz ändern
        upd, uerr = lib.update_entry(e_file["id"], title="Einzelne Datei", note="nur eine Datei")
        check(upd and not uerr and lib.load_entries()[2]["title"] == "Einzelne Datei"
              and lib.load_entries()[2]["note"] == "nur eine Datei", "update_entry ändert Titel und Notiz", uerr)
        upd2, uerr2 = lib.update_entry(e_file["id"], title="   ")
        check(upd2 and upd2["title"] == "einzel.txt", "leerer Titel fällt auf den Dateinamen zurück", str(upd2))
        _, uerr3 = lib.update_entry("gibt-es-nicht", note="x")
        check("Kein Eintrag" in uerr3, "update_entry meldet unbekannte Kennung", uerr3)

        # Spiegel der Adresse: Tiefe 2, robots.txt, fremder Host, Binärdatei, 404
        FakeSite.hits.clear()
        progress = []
        status = lib.mirror_entry(e_url, depth=2, max_pages=50, delay=0, progress=progress.append)
        fetched = set(FakeSite.hits)
        check(status["status"] == "done" and status["pages"] == 5,
              "Spiegel: Startseite, drei Verweise, Tiefe-eins-Seite gelesen (5 Seiten)", json.dumps(status, ensure_ascii=False))
        check("/robots.txt" in fetched and "/verboten/x.html" not in fetched,
              "robots.txt geholt und Disallow beachtet", str(sorted(fetched)))
        check("/tief1.html" in fetched and "/tief2.html" not in fetched, "Tiefe 2 endet vor der dritten Ebene", str(sorted(fetched)))
        check("/bild.png" not in fetched, "Bild-Verweis wird gar nicht erst geholt", str(sorted(fetched)))
        errs = " | ".join(status["errors"])
        check(status["error_count"] == 3 and "robots.txt" in errs and "fremden Host" in errs and "HTTP 404" in errs,
              "drei Fehler gemerkt: robots, Umleitung auf fremden Host, 404", errs)
        check(progress and progress[0]["status"] == "running" and progress[-1]["status"] == "done"
              and any(p["current"] for p in progress),
              "Fortschritt: erst running mit aktueller Seite, am Ende done", str(progress[:2]))
        saved = lib.mirror_status(e_url["id"])
        check(saved and saved["status"] == "done" and saved["pages"] == 5 and saved["depth"] == 2
              and saved["page_limit"] == 50 and saved["error_count"] == 3 and saved["finished"],
              "Stand in der Tabelle mirrors: Seiten, Tiefe, Limit, Fehler, Zeitpunkt", str(saved))
        line = lib.describe_mirror(saved)
        check(line.startswith("Spiegel: 5 Seiten, Stand ") and "3 Fehler" in line, "describe_mirror nennt Seiten, Zeit, Fehler", line)
        con = lib.open_index()
        sources = sorted(r[0] for r in con.execute("SELECT source FROM pages WHERE entry_id = ?", (e_url["id"],)))
        con.close()
        check(sources == [base + "/", base + "/a.html", base + "/b.html", base + "/sub/c.html", base + "/tief1.html"],
              "Seiten liegen mit ihrer Adresse im Index, Anker abgeschnitten", str(sources))

        # Seitenlimit, Abbruch, zweiter Lauf aus dem Cache
        status2 = lib.mirror_entry(e_url, depth=2, max_pages=2, delay=0)
        check(status2["status"] == "done" and status2["pages"] == 2, "Seitenlimit 2 hält an", str(status2))
        con = lib.open_index()
        left = con.execute("SELECT count(*) FROM pages WHERE entry_id = ?", (e_url["id"],)).fetchone()[0]
        con.close()
        check(left == 2, "vollständiger Lauf räumt nicht mehr gesehene Seiten weg", str(left))
        seen = []

        def cancel():
            return len(seen) >= 2

        status3 = lib.mirror_entry(e_url, depth=2, max_pages=50, delay=0, progress=lambda s: seen.append(s["pages"]) if s["pages"] else None,
                                   cancel=cancel)
        check(status3["status"] == "cancelled" and 1 <= status3["pages"] <= 3 and "abgebrochen" in lib.describe_mirror(status3),
              "Abbruch über cancel() endet mit Stand cancelled", str(status3))
        FakeSite.hits.clear()
        status4 = lib.mirror_entry(e_url, depth=2, max_pages=50, delay=0)
        check(status4["pages"] == 5 and set(FakeSite.hits) <= {"/robots.txt", "/fehlt.html"},
              "erneuter Lauf kommt aus dem 24-Stunden-Cache (nur robots.txt und die 404-Seite frisch)", str(FakeSite.hits))
        FakeSite.hits.clear()
        status5 = lib.mirror_entry(e_url, depth=0, max_pages=50, delay=0, refresh=True)
        check(status5["pages"] == 1 and "/" in FakeSite.hits and "/a.html" not in FakeSite.hits,
              "Tiefe 0 und refresh: nur die Startseite, frisch geholt", str(FakeSite.hits))
        lib.mirror_entry(e_url, depth=2, max_pages=50, delay=0)

        # Ordner und Datei
        sd = lib.mirror_entry(e_dir, delay=0)
        check(sd["status"] == "done" and sd["pages"] == 2 and sd["error_count"] == 0,
              "Ordner: zwei Textdateien indiziert, Binär- und versteckte Datei übergangen", str(sd))
        sf = lib.mirror_entry(e_file, delay=0)
        check(sf["status"] == "done" and sf["pages"] == 1, "Datei indiziert", str(sf))
        sd2 = lib.mirror_entry(e_dir, max_pages=1, delay=0)
        check(sd2["pages"] == 1 and sd2["error_count"] == 1 and "mehr als 1" in sd2["errors"][0],
              "Ordner mit Limit meldet, was außen vor bleibt", str(sd2))
        lib.mirror_entry(e_dir, delay=0)
        bad = lib.mirror_entry({"id": "kaputt", "kind": "file", "source": str(Path(tmp, "fehlt.txt")), "title": "x"}, delay=0)
        check(bad["status"] == "error" and "fehlgeschlagen" in lib.describe_mirror(bad), "fehlende Datei: Stand error", str(bad))
        lib.drop_mirror("kaputt")

        # Suche
        hits, mode = lib.search_index("Fenster")
        check(mode == ("fts5" if has_fts else "like") and hits and hits[0]["entry_id"] == e_url["id"]
              and hits[0]["source"] == base + "/a.html" and "Fenster" in hits[0]["snippet"],
              "Suche findet die Fensterseite mit Ausschnitt", f"{mode} {hits[:2]}")
        check(("[Fenster" in hits[0]["snippet"]) if has_fts else True, "FTS5 markiert den Treffer im Ausschnitt", str(hits[:1]))
        hits_g, _ = lib.search_index("grosse")
        hits_g2, _ = lib.search_index("Größe")
        hits_g3, _ = lib.search_index("GROESSE")
        hits_m, _ = lib.search_index("muller")
        check(all(h and h[0]["source"] == base + "/a.html" for h in (hits_g, hits_g2, hits_g3, hits_m)),
              "deutsche Schreibweisen: grosse, Größe, GROESSE, muller finden Größe und Müller",
              f"{len(hits_g)} {len(hits_g2)} {len(hits_g3)} {len(hits_m)}")
        hits_p, _ = lib.search_index('"versteckte Dateien"')
        hits_p2, _ = lib.search_index('"Dateien versteckte"')
        check(hits_p and hits_p[0]["source"] == base + "/b.html" and (not hits_p2 if has_fts else True),
              "Wortfolge in Anführungszeichen", f"{hits_p[:1]} {hits_p2[:1]}")
        hits_d, _ = lib.search_index("Drucker", entry_id=e_dir["id"])
        hits_d2, _ = lib.search_index("Drucken", entry_id=e_dir["id"])
        check(hits_d and hits_d[0]["source"].endswith("notiz.txt") and not hits_d2,
              "Filter auf einen Eintrag: Ordner findet die Notiz, nicht die Webseite", f"{hits_d} {hits_d2}")
        hits_s, _ = lib.search_index("Strasse")
        check(hits_s and hits_s[0]["source"].endswith("README.md"), "ß und ss: Strasse findet Straße", str(hits_s))
        hits_l, _ = lib.search_index("Handbuch", limit=1)
        check(len(hits_l) == 1, "limit begrenzt die Treffer", str(hits_l))
        hits_n, _ = lib.search_index("gibtesnicht")
        hits_e, _ = lib.search_index("")
        check(hits_n == [] and hits_e == [], "keine Treffer und leere Anfrage liefern leere Listen")
        hits_q, _ = lib.search_index('Fenster "(:*^')
        check(hits_q and hits_q[0]["source"] == base + "/a.html", "Sonderzeichen der FTS-Syntax stören nicht", str(hits_q))

        # LIKE-Rückfall erzwingen
        state = dict(lib._FTS_STATE)
        lib._FTS_STATE["available"] = False
        try:
            hits_f, mode_f = lib.search_index("GRÖSSE müller")
            hits_f2, _ = lib.search_index("Strasse")
            hits_f3, _ = lib.search_index("Drucker", entry_id=e_dir["id"])
            check(mode_f == "like" and hits_f and hits_f[0]["source"] == base + "/a.html" and "Größe" in hits_f[0]["snippet"]
                  and hits_f2 and hits_f2[0]["source"].endswith("README.md") and hits_f3 and hits_f3[0]["source"].endswith("notiz.txt"),
                  "LIKE-Rückfall: gefaltete Suche mit Umlaut, ß und Eintrag-Filter, Ausschnitt aus dem Original",
                  f"{mode_f} {hits_f[:1]} {hits_f2[:1]} {hits_f3[:1]}")
            out_like = lib.handle_library_search({"query": "Fenster"})
            check("LIKE-Suche" in out_like, "Werkzeugtext nennt den Rückfall", out_like[:200])
            hits_pct, _ = lib.search_index("100%")
            hits_us, _ = lib.search_index("1__%")
            check(hits_pct and hits_pct[0]["source"] == base + "/b.html" and not hits_us,
                  "LIKE-Rückfall: Prozent und Unterstrich sind Zeichen, keine Platzhalter", f"{hits_pct[:1]} {hits_us[:1]}")
        finally:
            lib._FTS_STATE.update(state)

        # Werkzeugtexte und Prompt
        out1 = lib.handle_library_search({"query": "Fenster Maus"})
        check(out1.startswith("1 Treffer") and "Quelle: " + base + "/a.html" in out1 and f"Handbuch, {e_url['id']}" in out1
              and "library_fetch" in out1, "library_search: Treffer mit Titel, Eintrag, Quelle, Ausschnitt", out1)
        out2 = lib.handle_library_search({"query": "gibtesnicht"})
        check("Keine Treffer" in out2 and "Gespiegelt sind" in out2 and e_url["id"] in out2, "library_search ohne Treffer nennt die Spiegel", out2)
        out3 = lib.handle_library_search({"query": "x", "entry_id": "falsch"})
        check("Kein Eintrag" in out3, "library_search mit falscher Kennung", out3)
        out4 = lib.handle_library_mirror({"entry_id": e_url["id"], "depth": 1, "max_pages": 3})
        check(out4.startswith("Handbuch (") and "Spiegel: 3 Seiten" in out4 and "library_search" in out4,
              "library_mirror: Stand und Hinweis auf die Suche", out4)
        out5 = lib.handle_library_mirror({"entry_id": "falsch"})
        check("Kein Eintrag" in out5, "library_mirror mit falscher Kennung", out5)
        listing = lib.handle_library_list({})
        check("Spiegel: 3 Seiten" in listing and "Spiegel: 2 Seiten" in listing and "library_search" in listing,
              "library_list zeigt den Stand je Eintrag", listing)
        section = lib.prompt_section()
        check("erst library_search" in section and "Spiegel: 3 Seiten" in section and "library_mirror" in section,
              "Prompt-Abschnitt: erst suchen, dann lesen, Stand je Eintrag", section[-500:])
        check(lib.remove_entry(e_file["id"]) and lib.mirror_status(e_file["id"]) is None
              and not lib.search_index("Tastaturkürzel")[0], "Entfernen nimmt den Spiegel mit aus dem Index")
        fetched_hit = lib.handle_library_fetch({"target": hits[0]["source"]})
        check("Fremdtext beginnt" in fetched_hit and "Größe der Fenster" in fetched_hit, "Quelle eines Treffers lässt sich mit library_fetch lesen")

        # MCP-Schalter gegen eine Wegwerf-config.yaml
        cfg = Path(tmp, "hermes", "config.yaml")
        cfg.parent.mkdir(parents=True)
        template = Path(args.config_template)
        if not template.is_file():
            template = HERE.parent / "files/system/usr/share/hermes-os/config.yaml.default"
        original = template.read_text(encoding="utf-8") if template.is_file() else "approvals:\n  mode: smart\n"
        cfg.write_text(original, encoding="utf-8")
        os.chmod(cfg, 0o600)
        check(lib.hermes_config_path() == cfg and lib.mcp_status() == {"context7": False, "deepwiki": False}
              and [c["id"] for c in lib.mcp_catalog()] == ["context7", "deepwiki"],
              "Katalog mit context7 und deepwiki, beide aus", str(lib.mcp_status()))
        ok1, msg1 = lib.mcp_set("context7", True)
        text1 = cfg.read_text(encoding="utf-8")
        check(ok1 and "eingetragen" in msg1 and "Minute" in msg1 and text1.startswith(original)
              and "mcp_servers:\n  context7:\n    url: \"https://mcp.context7.com/mcp\"\n    enabled: true\n" in text1
              and lib.mcp_status() == {"context7": True, "deepwiki": False} and oct(cfg.stat().st_mode & 0o777) == "0o600",
              "context7 ein: Block angehängt, Kommentare und Rechte bleiben", f"{ok1} {msg1} {text1[-300:]}")
        ok2, msg2 = lib.mcp_set("deepwiki", True)
        check(ok2 and lib.mcp_status() == {"context7": True, "deepwiki": True}
              and "  deepwiki:\n    url: \"https://mcp.deepwiki.com/mcp\"\n    enabled: true\n" in cfg.read_text(encoding="utf-8"),
              "deepwiki dazu", f"{ok2} {msg2}")
        ok2b, msg2b = lib.mcp_set("deepwiki", True)
        check(not ok2b and "schon" in msg2b, "zweites Einschalten ändert nichts", msg2b)
        try:
            import yaml
            data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
            check(data["mcp_servers"] == {"context7": {"url": "https://mcp.context7.com/mcp", "enabled": True},
                                          "deepwiki": {"url": "https://mcp.deepwiki.com/mcp", "enabled": True}}
                  and data["approvals"]["mode"] == "smart", "PyYAML liest das Ergebnis wie erwartet", str(data.get("mcp_servers")))
        except ImportError:
            print("      (PyYAML fehlt hier, Gegenprobe übersprungen)")
        ok3, msg3 = lib.mcp_set("context7", False)
        text3 = cfg.read_text(encoding="utf-8")
        check(ok3 and "ausgetragen" in msg3 and "context7" not in text3 and "deepwiki" in text3
              and lib.mcp_status() == {"context7": False, "deepwiki": True}, "context7 aus: Block weg, deepwiki bleibt", text3[-300:])
        ok4, _ = lib.mcp_set("deepwiki", False)
        text4 = cfg.read_text(encoding="utf-8")
        check(ok4 and "mcp_servers: {}" in text4 and "deepwiki" not in text4 and text4.startswith(original),
              "letzter Server aus: mcp_servers bleibt als leeres Mapping", text4[-200:])
        ok5, _ = lib.mcp_set("deepwiki", True)
        check(ok5 and lib.mcp_status()["deepwiki"] and "mcp_servers:\n  deepwiki:" in cfg.read_text(encoding="utf-8"),
              "wieder ein über das leere Mapping", cfg.read_text(encoding="utf-8")[-200:])
        ok5b, msg5b = lib.mcp_set("deepwiki", False)
        check(ok5b and not lib.mcp_status()["deepwiki"], "und wieder aus", msg5b)
        # Eigener Eintrag des Nutzers mit weiteren Schlüsseln: aus heißt enabled: false, ein dreht es zurück
        cfg.write_text(original + "\nmcp_servers:\n  context7:\n    url: https://mcp.context7.com/mcp\n"
                       "    headers:\n      Authorization: Bearer ${CONTEXT7_API_KEY}\n  eigener:\n    command: npx\n"
                       "    args: [x]\n", encoding="utf-8")
        check(lib.mcp_status() == {"context7": True, "deepwiki": False}, "Eintrag ohne enabled gilt als an")
        ok6, _ = lib.mcp_set("context7", False)
        text6 = cfg.read_text(encoding="utf-8")
        check(ok6 and "  context7:\n    enabled: false\n    url:" in text6 and "CONTEXT7_API_KEY" in text6 and "eigener:" in text6
              and lib.mcp_status()["context7"] is False, "eigener Eintrag mit headers wird nur abgeschaltet", text6[-300:])
        ok7, _ = lib.mcp_set("context7", True)
        text7 = cfg.read_text(encoding="utf-8")
        check(ok7 and "  context7:\n    enabled: true\n    url:" in text7 and lib.mcp_status()["context7"], "und wieder eingeschaltet", text7[-300:])
        ok8, msg8 = lib.mcp_set("nope", True)
        check(not ok8 and "Unbekannt" in msg8, "unbekannter Server wird abgewiesen", msg8)
        cfg.write_text("mcp_servers: {context7: {url: x}}\n", encoding="utf-8")
        ok9, msg9 = lib.mcp_set("deepwiki", True)
        check(not ok9 and "von Hand" in msg9 and cfg.read_text(encoding="utf-8") == "mcp_servers: {context7: {url: x}}\n",
              "Flow-Schreibweise wird nicht angefasst", msg9)
        cfg.unlink()
        ok10, _ = lib.mcp_set("context7", True)
        check(ok10 and cfg.read_text(encoding="utf-8").startswith("# ---- Doku-Server (MCP)") and lib.mcp_status()["context7"],
              "fehlende config.yaml wird angelegt", cfg.read_text(encoding="utf-8")[:100])
    finally:
        server.shutdown()
        server.server_close()

    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
