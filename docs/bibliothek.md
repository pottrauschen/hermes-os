# Bibliothek: Wissensquellen für den Agenten

Stand: 2026-09-26, Stufe zwei. Der Nutzer trägt im Chat-Fenster Adressen,
Dateien und Ordner ein, die Hermes kennen soll; der Agent liest sie bei Bedarf
und nennt die Quelle. Gedacht für Handbücher wie docs.kde.org und eigene
Unterlagen. Stufe eins (2026-09-26) war die einfache Form: Ablage, Seite,
`library_list` und `library_fetch`. Stufe zwei (gleicher Tag, eigener Zweig)
legt darüber je Eintrag einen Spiegel im Cache an, einen Volltextindex mit
SQLite FTS5 und `library_search`, die Schalter für die Doku-Server aus Hermes'
MCP-Katalog und die Seite bekommt Ablegen, Suche, Spiegeln und Notizen ändern.
Die Ablage `bibliothek.json` blieb dabei unverändert.

## Was es tut

- **Seite „Bibliothek" im Chat-Fenster**, erreichbar über den Knopf im Kopf
  und den Menüpunkt am Symbol: Eintrag mit Adresse oder Pfad, Titel und Notiz,
  Datei- und Ordnerdialog, ein Feld zum Ablegen (Dateien und Ordner aus dem
  Dateimanager, Adressen aus dem Browser), ein Suchfeld mit Trefferliste, je
  Eintrag der Stand des Spiegels mit Knopf „Spiegeln" oder „Abbrechen", Titel
  und Notiz ändern, Öffnen und Entfernen, unten die Schalter der Doku-Server.
  Escape oder der Pfeil führen zurück zum Chat. Spiegeln und Suchen laufen in
  Arbeitsthreads, der Fortschritt kommt über Signale in die Ereignisschleife.
- **Ablage** `~/.config/hermes-os/bibliothek.json` (Format unten). Das Symbol
  schreibt, das Plugin liest; beide über `plugins/hermes_os/library.py`. Das
  Symbol lädt das Modul über seinen Dateipfad und importiert das Plugin-Paket
  nicht; das Modul braucht weder Hermes noch Qt.
- **Prompt-Abschnitt**: Bei jeder neuen Sitzung bekommt der Agent die Liste
  mit Kennung, Titel, Quelle, Notiz und Stand des Spiegels sowie die Regeln:
  erst `library_search`, dann `library_fetch` mit der Quelle eines Treffers;
  ohne Spiegel `library_fetch` und den Verweisen folgen oder `library_mirror`
  anbieten (die Plugin-API nimmt ein Callable, es liest Datei und Index
  frisch). Eine leere Bibliothek sagt ihm, wo der Nutzer Quellen eintragen
  kann. `library_list` zeigt die Liste samt Stand jederzeit.
- **`library_fetch`** holt eine Seite oder Datei. `target` ist die Kennung
  eines Eintrags, eine Adresse unter einer eingetragenen Adresse, eine
  eingetragene Datei oder ein Pfad unter einem eingetragenen Ordner; ein
  Ordner liefert seine Dateiliste. HTML wird zu Text mit Überschriften,
  Listen und Bild-Beschreibungen, dazu die Verweise auf demselben Host, denen
  der Agent mit einem weiteren Aufruf folgt. PDF läuft über `pdftotext`
  (erste 60 Seiten), Textformate werden direkt gelesen. Lange Texte kommen in
  Stücken (`start`, `max_chars`, Vorgabe 12 000 Zeichen). Adressen liegen 24
  Stunden im Cache unter `~/.cache/hermes-os/bibliothek`, `refresh` holt neu.
- **`library_mirror(entry_id, depth, max_pages, refresh)`** legt den Spiegel
  eines Eintrags an oder erneuert ihn, dasselbe tut der Knopf auf der Seite.
  Eine Adresse wird ab der Startseite Breite zuerst gespiegelt: Verweise auf
  demselben Host unter dem Pfadanfang, bis zur Tiefe (`depth`, Vorgabe 2, 0
  nur die Seite, höchstens 5) und bis zum Seitenlimit (`max_pages`, Werkzeug
  100, Seite 200, höchstens 2000). Höflich: `robots.txt` des Hosts wird
  geholt und beachtet (Disallow und Crawl-delay bis 10 s), zwischen zwei
  Netzabrufen liegt eine halbe Sekunde, Seiten aus dem 24-Stunden-Cache
  kosten keinen Abruf, Verweise auf Bilder, Archive, Skripte und Stile werden
  gar nicht erst geholt, derselbe User-Agent wie beim Abrufer. Dateien und
  Ordner werden indiziert, nicht kopiert: der Text landet im Index, die
  Dateien bleiben, wo sie sind (Ordner: lesbare Textformate und PDF, ohne
  versteckte Einträge, bis zum Limit). Stand je Eintrag: Seitenzahl,
  Zeitpunkt, Fehlerzahl und die ersten Fehler (robots, fremder Host, 404,
  Binärdatei). Ein vollständiger Lauf räumt Seiten aus dem Index, die es nicht
  mehr gibt; ein abgebrochener Lauf lässt stehen, was da ist. Das Werkzeug
  läuft synchron im Aufruf und kann bei vielen Seiten Minuten dauern; die
  Beschreibung sagt dem Agenten, dass er das vorher ankündigt.
- **Index** `~/.cache/hermes-os/bibliothek/index.sqlite`: Tabelle `pages`
  (Eintrag, Quelle, Titel, Text bis 400 000 Zeichen, dazu eine gefaltete
  Kopie für den Rückfall), `mirrors` (Stand je Eintrag) und darüber
  `pages_fts`, eine externe FTS5-Inhaltstabelle mit dem Tokenizer `unicode61
  remove_diacritics 2`, die nach jedem Spiegel-Lauf neu gebaut wird. Beide
  Interpreter bringen FTS5 mit: das Python 3.13 der Hermes-Venv (uv,
  python-build-standalone, SQLite 3.50 mit `ENABLE_FTS5`, geprüft am
  2026-09-26) für das Plugin und Fedoras Python für das Symbol; das Gate
  meldet beides. **Rückfall**: Fehlt FTS5, meldet `open_index` das beim
  Anlegen der virtuellen Tabelle, und `library_search` sucht mit `LIKE` in der
  gefalteten Spalte (Kleinschreibung, ß zu ss, Umlaute und Akzente ohne
  Zeichen), Ausschnitt um den ersten Treffer, Reihenfolge nach Textlänge; das
  Werkzeug sagt dann „LIKE-Suche" dazu. Der Test erzwingt den Rückfall einmal.
- **`library_search(query, entry_id, limit)`** liefert Treffer mit Titel,
  Quelle (Adresse oder Pfad), Kennung des Eintrags und einem Ausschnitt mit
  markierten Fundstellen, sortiert nach `bm25` (Titel zählt vierfach). Wörter
  werden als Wortanfänge gesucht („Datei" findet „Dateien"), ein Ausdruck in
  Anführungszeichen als Wortfolge, mehrere Wörter mit UND. Deutsche
  Schreibweisen werden ergänzt, weil der Tokenizer nur Umlautpunkte streicht:
  ß und ss, ae/oe/ue und Umlaut (`grosse`, `Größe`, `GROESSE` finden dasselbe,
  `Strasse` findet `Straße`). Sonderzeichen der FTS-Syntax werden entfernt.
  Ohne Spiegel verweist die Antwort auf `library_mirror`, ohne Treffer nennt
  sie, was gespiegelt ist. Auf der Seite sucht dasselbe Suchfeld mit bis zu
  30 Treffern; „Öffnen" zeigt die Quelle im Browser oder Programm.
- **Doku-Server (MCP)**: Hermes 0.21.5 hat einen Katalog
  (`optional-mcps/<name>/manifest.yaml` im Hermes-Repo, `hermes mcp install
  <name>`); context7 (`https://mcp.context7.com/mcp`, Dokumentation und
  Codebeispiele zu Bibliotheken) und deepwiki (`https://mcp.deepwiki.com/mcp`,
  Fragen zu öffentlichen GitHub-Projekten) sind darin, beide anonym, beide
  Streamable HTTP. Die Installation über die CLI ist interaktiv (Werkzeug-
  auswahl in curses), deshalb schreibt der Schalter denselben Eintrag selbst:
  `mcp_servers.<name>` mit `url` und `enabled: true` in `~/.hermes/config.yaml`.
  Geändert wird nur der Block des Servers, zeilenweise, damit die Kommentare
  der Datei stehen bleiben; PyYAML prüft das Ergebnis vor dem Schreiben, wo es
  da ist. Ausschalten entfernt einen Block, der nur aus `url` und `enabled`
  besteht; einen Block mit eigenen Schlüsseln (etwa `headers` mit einem
  API-Key) setzt es nur auf `enabled: false`, Einschalten dreht das zurück.
  Ein `mcp_servers` in Flow-Schreibweise fasst der Schalter nicht an. **Kein
  Neustart nötig**, anders als im Plan: das Gateway beobachtet `config.yaml`
  und verbindet oder trennt Server innerhalb etwa einer Minute
  (`gateway/run_profile_reconcile.py`, Doku `mcp.md`, „Reloading"); der
  API-Server, an dem das Chat-Fenster hängt, nimmt alle eingeschalteten Server
  mit, solange `platform_toolsets.api_server` nichts anderes sagt. Ein
  laufendes Gespräch sieht die neuen Werkzeuge ab dem nächsten neuen Gespräch.
  Die Werkzeuge heißen `mcp__context7__<tool>` und `mcp__deepwiki__<tool>`.
- **Grenzen**: Geholt wird nur, was der Nutzer eingetragen hat: derselbe Host
  samt Pfadanfang, die Datei selbst, Pfade unter dem Ordner. Umleitungen auf
  fremde Hosts werden verworfen, Antworten über 8 MB nicht gelesen, Binär-
  dateien abgewiesen. Abgerufener Text steht zwischen Markierungen als
  Fremdtext; die Regeln im Prompt sagen dem Agenten, dass Anweisungen darin
  nicht gelten. Der Index ist eine Kopie des Textes im Cache des Nutzers,
  nicht mehr; wer einen Eintrag entfernt, entfernt seinen Spiegel mit.

## Format

```json
{
  "version": 1,
  "entries": [
    {"id": "docs-kde-org", "kind": "url", "source": "https://docs.kde.org/",
     "title": "KDE-Handbücher", "note": "deutsch unter stable5/de",
     "added": "2026-09-26T18:30:00"}
  ]
}
```

`kind` ist `url`, `file` oder `folder`. Die Kennung entsteht aus dem Host
oder dem Dateinamen (`docs-kde-org`, `handbuch-pdf`), bei Dopplung mit `-2`.
Fehlt der Titel, steht der Host oder der Dateiname dort. Der Stand der Spiegel
steht nicht hier, sondern in `index.sqlite` (Tabelle `mirrors`: `status`
`running`, `done`, `error` oder `cancelled`, `pages`, `started`, `finished`,
`depth`, `page_limit`, `error_count`, `errors` als JSON-Liste).

Der Eintrag, den der Schalter in `~/.hermes/config.yaml` anlegt:

```yaml
mcp_servers:
  context7:
    url: "https://mcp.context7.com/mcp"
    enabled: true
```

## docs.kde.org als erster Eintrag

Adresse `https://docs.kde.org/`, Notiz etwa: „Handbücher der KDE-Programme.
Deutsch unter stable_kf6/de/<programm>/<programm>/index.html, Übersicht unter
index.php?language=de&package=<programm>". Der Agent holt die Übersicht,
folgt dem Verweis zum Programm und liest das Kapitel. Die Handbücher sind
teils älter als das laufende Plasma; was sie sagen, prüft er mit den
os_*-Werkzeugen am System.

Geprüft am 2026-09-26 gegen das Gateway in der Test-VM (Stufe eins): Auf die
Frage nach dem Dolphin-Handbuch rief der Agent `library_list`, mehrfach
`library_fetch` entlang der Verweise und `web_search` mit `site:docs.kde.org`,
nannte Titel, Adresse und Quelle in rund 30 Sekunden und merkte an, dass der
ältere Pfad `stable5/de` inzwischen 404 liefert.

Für die Suche lohnt ein engerer Eintrag als die Startseite: die Übersicht
verweist auf hunderte Programme, ein Spiegel mit Tiefe 2 und 200 Seiten bleibt
in der Übersicht hängen. Besser `https://docs.kde.org/stable_kf6/de/dolphin/`
als eigener Eintrag, dann liegt das ganze Handbuch im Index.

## Testen

```sh
python3 tests/library-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
python3 tests/library2-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os \
    --config-template files/system/usr/share/hermes-os/config.yaml.default
```

Ohne Qt und ohne Hermes, überall mit Python 3.9 oder neuer. Stufe eins:
Ablage, Kennungen, Zuordnung von Zielen zu Einträgen, Abrufer gegen einen
nachgebauten Webserver (HTML zu Text, Verweise nur vom eigenen Host, Cache,
`refresh`, Stückelung, fremde Hosts und Binärdateien abgewiesen), Dateien und
Ordner, Prompt-Abschnitt. Stufe zwei: Spiegel gegen einen nachgebauten Server
mit `robots.txt` (Tiefe, Seitenlimit, Disallow, Bild-Verweise, Umleitung auf
fremden Host, 404, Fortschritt, Abbruch, zweiter Lauf aus dem Cache, `refresh`),
Ordner und Datei im Index, Suche mit FTS5 (Ausschnitt, deutsche Schreibweisen,
Wortfolge, Eintrag-Filter, Limit, Sonderzeichen), der erzwungene LIKE-Rückfall,
Werkzeugtexte, Prompt-Abschnitt, Entfernen räumt den Index, und die Schalter
gegen eine Kopie der Config-Vorlage (ein, dazu, aus, leeres Mapping, eigener
Block mit `headers`, Flow-Schreibweise abgewiesen, fehlende Datei angelegt,
Rechte 0600 bleiben, PyYAML-Gegenprobe). `make lint` und das Gate
(`80-validate.sh`, 7g) führen beide aus, das Gate mit der Venv-Python des
Gateways und einer Meldung, ob deren SQLite und Fedoras Python FTS5 haben.
`tests/tray-gui-check.py` rendert die Seite offscreen: öffnen, Eintrag anlegen,
Fehler anzeigen, entfernen, Ablegen, Spiegeln mit Fortschritt und Abbrechen-
Knopf, Suche mit Trefferliste und Öffnen, Titel und Notiz ändern, Schalter der
Doku-Server, zurück.

## Stolperfallen

- **Neue Einträge gelten ab dem nächsten Gespräch.** Der Prompt-Abschnitt
  wird beim Anlegen einer Sitzung eingefroren; im laufenden Gespräch sieht der
  Agent neue Einträge nur über `library_list`. Ein neuer Spiegel dagegen ist
  sofort durchsuchbar, `library_search` liest den Index bei jedem Aufruf.
- **Ein Ziel muss zu einem Eintrag gehören.** Fragt der Agent eine fremde
  Adresse an, bekommt er den Hinweis auf `library_list`, keine Seite. Das ist
  Absicht: die Bibliothek ist kein allgemeiner Web-Abrufer, dafür gibt es
  `web_extract`.
- **Das Modell entscheidet, ob es nachschlägt.** Die Regeln im Prompt helfen,
  ersetzen aber kein Modell, das Werkzeuge verlässlich nutzt.
- **Ein Spiegel ist so gut wie sein Startpunkt.** Tiefe und Seitenlimit
  zählen ab der eingetragenen Adresse; wer die Startseite eines großen
  Doku-Servers einträgt, bekommt Übersichten, keine Kapitel. Engere Einträge
  je Handbuch sind der bessere Weg.
- **`library_mirror` blockiert das Gespräch.** Bis zu 100 Seiten mit halber
  Sekunde Pause sind eine Minute, plus Abrufzeit. Für große Spiegel ist der
  Knopf auf der Seite der richtige Ort: er läuft im Hintergrund, zeigt den
  Fortschritt und lässt sich abbrechen.
- **Zwei Interpreter, ein Index.** Das Symbol schreibt mit Fedoras Python,
  das Plugin liest mit dem Python der Venv, beide über dieselbe SQLite-Datei
  im WAL-Modus (daneben liegen `index.sqlite-wal` und `-shm`). Läuft ein
  Spiegel, liest die Suche den Stand vom letzten Commit. Ein Interpreter ohne
  FTS5 kann den Index trotzdem lesen, nur eben mit der LIKE-Suche.
- **Der Tokenizer kennt kein ß.** `remove_diacritics` macht aus ö ein o,
  aber aus ß kein ss; deshalb ergänzt `fts_query` die Schreibweisen. Wer
  andere Sprachen mit eigenen Regeln braucht, erweitert `_term_variants`.
- **Die Schalter schreiben in die Datei des Nutzers.** `config.yaml` gehört
  Hermes und dem Nutzer; der Schalter ändert nur den Block seines Servers und
  legt die Datei mit einem Kommentarkopf an, wenn sie fehlt. Hermes selbst
  schreibt die Datei mit einem ruamel-Roundtrip (`utils.atomic_roundtrip_yaml_save`),
  Kommentare überleben beides.
- **Offen: Prüfung in der Test-VM.** Der Umlauf Schalter, Gateway verbindet
  context7 innerhalb einer Minute, Agent nutzt `mcp__context7__*`, ist im
  Quellcode belegt, aber noch nicht in VM 112 beobachtet; ebenso die Seite mit
  echtem Ablegen aus Dolphin und Firefox und ein Spiegel von docs.kde.org.

## Nächste Stufe, offen

- Spiegel von selbst erneuern (Alter je Eintrag, Lauf im Hintergrund über
  einen Timer des Gateways oder das Symbol).
- Weitere Server aus dem Katalog als Schalter, sobald der Bedarf da ist; die
  Liste `MCP_CATALOG` in `library.py` ist der einzige Ort dafür.
- Treffer der Seite direkt ins Gespräch übernehmen („Im Chat besprechen" wie
  beim Morgenbericht).
