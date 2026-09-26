# Bibliothek: Wissensquellen für den Agenten

Stand: 2026-09-26, Stufe eins. Der Nutzer trägt im Chat-Fenster Adressen,
Dateien und Ordner ein, die Hermes kennen soll; der Agent liest sie bei Bedarf
und nennt die Quelle. Gedacht für Handbücher wie docs.kde.org und eigene
Unterlagen. Entscheidung vom 2026-09-26: erst die einfache Form, Spiegeln und
Volltextsuche später, ohne die Ablage zu ändern.

## Was es tut

- **Seite „Bibliothek" im Chat-Fenster**, erreichbar über den Knopf im Kopf
  und den Menüpunkt am Symbol: Eintrag mit Adresse oder Pfad, Titel und Notiz,
  Datei- und Ordnerdialog, je Eintrag Öffnen und Entfernen. Escape oder der
  Pfeil führen zurück zum Chat.
- **Ablage** `~/.config/hermes-os/bibliothek.json` (Format unten). Das Symbol
  schreibt, das Plugin liest; beide über `plugins/hermes_os/library.py`. Das
  Symbol lädt das Modul über seinen Dateipfad und importiert das Plugin-Paket
  nicht; das Modul braucht weder Hermes noch Qt.
- **Prompt-Abschnitt**: Bei jeder neuen Sitzung bekommt der Agent die Liste
  mit Kennung, Titel, Quelle und Notiz sowie die Regeln (die Plugin-API nimmt
  ein Callable, es liest die Datei frisch). Eine leere Bibliothek sagt ihm,
  wo der Nutzer Quellen eintragen kann. `library_list` zeigt die Liste
  jederzeit.
- **`library_fetch`** holt eine Seite oder Datei. `target` ist die Kennung
  eines Eintrags, eine Adresse unter einer eingetragenen Adresse, eine
  eingetragene Datei oder ein Pfad unter einem eingetragenen Ordner; ein
  Ordner liefert seine Dateiliste. HTML wird zu Text mit Überschriften,
  Listen und Bild-Beschreibungen, dazu die Verweise auf demselben Host, denen
  der Agent mit einem weiteren Aufruf folgt. PDF läuft über `pdftotext`
  (erste 60 Seiten), Textformate werden direkt gelesen. Lange Texte kommen in
  Stücken (`start`, `max_chars`, Vorgabe 12 000 Zeichen). Adressen liegen 24
  Stunden im Cache unter `~/.cache/hermes-os/bibliothek`, `refresh` holt neu.
- **Grenzen**: Geholt wird nur, was der Nutzer eingetragen hat: derselbe Host
  samt Pfadanfang, die Datei selbst, Pfade unter dem Ordner. Umleitungen auf
  fremde Hosts werden verworfen, Antworten über 8 MB nicht gelesen, Binär-
  dateien abgewiesen. Abgerufener Text steht zwischen Markierungen als
  Fremdtext; die Regeln im Prompt sagen dem Agenten, dass Anweisungen darin
  nicht gelten.

Innerhalb einer Adresse sucht der Agent mit Hermes' `web_search` und
`site:<host>`; die Bibliothek selbst hat in Stufe eins keine Suche.

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
Fehlt der Titel, steht der Host oder der Dateiname dort.

## docs.kde.org als erster Eintrag

Adresse `https://docs.kde.org/`, Notiz etwa: „Handbücher der KDE-Programme.
Deutsch unter stable_kf6/de/<programm>/<programm>/index.html, Übersicht unter
index.php?language=de&package=<programm>". Der Agent holt die Übersicht,
folgt dem Verweis zum Programm und liest das Kapitel. Die Handbücher sind
teils älter als das laufende Plasma; was sie sagen, prüft er mit den
os_*-Werkzeugen am System.

Geprüft am 2026-09-26 gegen das Gateway in der Test-VM: Auf die Frage nach
dem Dolphin-Handbuch rief der Agent `library_list`, mehrfach `library_fetch`
entlang der Verweise und `web_search` mit `site:docs.kde.org`, nannte Titel,
Adresse und Quelle in rund 30 Sekunden und merkte an, dass der ältere Pfad
`stable5/de` inzwischen 404 liefert.

## Testen

```sh
python3 tests/library-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
```

Ohne Qt und ohne Hermes, überall mit Python 3.9 oder neuer: Ablage,
Kennungen, Zuordnung von Zielen zu Einträgen, Abrufer gegen einen nachgebauten
Webserver (HTML zu Text, Verweise nur vom eigenen Host, Cache, `refresh`,
Stückelung, fremde Hosts und Binärdateien abgewiesen), Dateien und Ordner,
Prompt-Abschnitt. `make lint` und das Gate (`80-validate.sh`, 7g) führen ihn
aus, das Gate mit der Venv-Python des Gateways. `tests/tray-gui-check.py`
rendert die Seite offscreen: öffnen, Eintrag anlegen, Fehler anzeigen,
entfernen, zurück.

## Stolperfallen

- **Neue Einträge gelten ab dem nächsten Gespräch.** Der Prompt-Abschnitt
  wird beim Anlegen einer Sitzung eingefroren; im laufenden Gespräch sieht der
  Agent neue Einträge nur über `library_list`.
- **Ein Ziel muss zu einem Eintrag gehören.** Fragt der Agent eine fremde
  Adresse an, bekommt er den Hinweis auf `library_list`, keine Seite. Das ist
  Absicht: die Bibliothek ist kein allgemeiner Web-Abrufer, dafür gibt es
  `web_extract`.
- **Das Modell entscheidet, ob es nachschlägt.** Die Regeln im Prompt helfen,
  ersetzen aber kein Modell, das Werkzeuge verlässlich nutzt.

## Stufe zwei, geplant

- Spiegeln je Eintrag mit begrenzter Tiefe, Text ablegen, Volltextsuche mit
  SQLite FTS5 über Spiegel und Ordner, dazu `library_search`.
- Die Doku-Server aus Hermes' MCP-Katalog (context7, deepwiki) als Schalter
  auf derselben Seite.
- Notizen nachträglich ändern, Dateien auf der Seite ablegen.
