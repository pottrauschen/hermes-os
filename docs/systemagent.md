# Systemagent: das Leisten-Symbol

Stand: 2026-09-26. Wie Hermes am Desktop sichtbar wird, ohne Terminal und ohne
ein Fenster, das dauernd offen steht: ein Symbol in der Systemleiste, ein
Chat-Fenster mit Sprechblasen und Bildern, Freigaben als Benachrichtigung.
Gebaut, durch Gate und Tests gelaufen, das Fenster offscreen in der Test-VM
gerendert und der Bildweg gegen das echte Gateway geprüft; als Symbol in der
Plasma-Sitzung noch nicht gebootet.

## Was es tut

- **Symbol in der Systemleiste** (StatusNotifierItem über `QSystemTrayIcon`)
  mit vier Zuständen: grau (Gateway aus oder Schlüssel fehlt), blau (bereit),
  orange (arbeitet), gelb (fragt nach einer Freigabe). Der Tooltip nennt den
  Zustand und die Hermes-Version.
- **Klick oder Meta+H** öffnet ein Kirigami-Fenster wie einen Messenger: oben
  Symbol mit Statuspunkt und Zustand, in der Mitte der Verlauf in Sprechblasen
  (eigene rechts in Akzentfarbe, Hermes links mit Symbol, Uhrzeit darunter),
  unten die Eingabe als Karte. Antworten kommen gestreamt, vorher pulsieren
  drei Punkte; Werkzeugaufrufe stehen als kleine Monospace-Zeilen dazwischen,
  Hinweise als Pille in der Mitte. Text lässt sich markieren und kopieren,
  Markdown wird gerendert. Enter sendet, Umschalt+Enter macht eine neue Zeile.
  Ein leerer Verlauf zeigt eine Begrüßung mit anklickbaren Vorschlägen. Escape
  versteckt das Fenster, Schließen ebenso; das Symbol bleibt.
- **Bilder mitschicken**: über den Knopf neben dem Textfeld (Dateidialog), mit
  Strg+V aus der Zwischenablage (Screenshot mit Spectacle, dann einfügen) oder
  indem man Dateien ins Fenster zieht. Angehängte Bilder erscheinen als
  Vorschau über dem Textfeld und lassen sich einzeln entfernen; sie gehen auch
  ohne Text ab. Bilder, die Hermes hinterlässt (Screenshots, `image_generate`),
  erscheinen in seiner Blase, ein Klick öffnet sie im Bildbetrachter. Details
  unter [Bilder](#bilder).
- **Freigaben**: Verlangt ein Befehl die Freigabe aus der Grenze (README),
  zeigt das Fenster einen Kasten mit Befehl, Begründung und den Knöpfen, die
  Hermes erlaubt (einmal, für diese Sitzung, immer, ablehnen). Zusätzlich
  kommt eine KDE-Benachrichtigung mit denselben Knöpfen, damit man antworten
  kann, ohne das Fenster zu öffnen. Ohne Antwort läuft der Befehl nach
  `approvals.timeout` (Vorgabe 5 Minuten) nicht.
- **Menü am Symbol**: Hermes öffnen, neues Gespräch, Hermes einrichten,
  Gateway starten, Chat im Terminal, Beenden. „Dashboard öffnen" erscheint,
  sobald Teil 2 aus [einrichtung.md](einrichtung.md) das Startskript
  `/usr/libexec/hermes-os-dashboard` liefert.
- **Autostart** bei jeder Plasma-Sitzung. Beim allerersten Login sagt das
  Symbol „nicht eingerichtet" und bietet den Assistenten an; nach dem
  Speichern schaltet das First-Login-Skript das Gateway ein, und das Symbol
  wird von selbst blau.

Das Mikrofon im Fenster ist ein Platzhalter. Der API-Server hat keinen
Sprachkanal; geplant ist Aufnahme mit QtMultimedia und Transkription über die
Brücke mit Hermes' lokalem Whisper.

## Dateien

| Was | Wo |
|---|---|
| Startprogramm, Python mit PySide6 | `files/system/usr/libexec/hermes-os-tray` |
| Fenster, QML mit Kirigami | `files/system/usr/share/hermes-os/tray/Main.qml` |
| Client für den API-Server, nur Standardbibliothek | `files/system/usr/share/hermes-os/tray/hermes_client.py` |
| Menüeintrag „Hermes", trägt `X-KDE-Shortcuts=Meta+H` | `files/system/usr/share/applications/hermes-os-tray.desktop` |
| Dieselbe Datei für den globalen Kurzbefehl | `files/system/usr/share/kglobalaccel/hermes-os-tray.desktop` |
| Autostart in der Plasma-Sitzung | `files/system/etc/xdg/autostart/hermes-os-tray.desktop` |
| Programmsymbol und die vier Zustände | `files/system/usr/share/icons/hicolor/scalable/{apps,status}/` |
| Client-Test gegen ein nachgebautes Gateway | `tests/tray-client-check.py` |
| Render-Test des Fensters ohne Display | `tests/tray-gui-check.py` |

Wie der Assistent läuft das Symbol mit Fedoras Python und PySide6 aus Aurora,
nicht mit der Hermes-Venv. Es importiert nichts aus Hermes; alles läuft über
HTTP auf localhost.

## Der Kanal: der API-Server des Gateways

Hermes' Gateway (`hermes gateway run`, bei uns `hermes-gateway.service`)
bringt einen API-Server mit, der auf `127.0.0.1:8642` lauscht, sobald in
`~/.hermes/.env` ein `API_SERVER_KEY` mit mindestens 16 Zeichen steht. Das
First-Login-Skript legt ihn an (Zufallswert, 48 Hex-Zeichen, Datei 0600),
sobald ein Anbieter eingerichtet ist, und startet das Gateway bei Bedarf neu.
Jede Anfrage trägt den Schlüssel als Bearer-Token; das Symbol liest ihn bei
jedem Lebenszeichen neu aus `.env`, ein Neustart ist nicht nötig.

Benutzte Endpunkte (Hermes v2026.9.24):

| Endpunkt | Zweck |
|---|---|
| `GET /health` | Lebenszeichen ohne Schlüssel, alle 5 Sekunden |
| `POST /api/sessions` | Gespräch anlegen, 409 wenn es schon existiert |
| `GET /api/sessions/{id}/messages?order=latest&limit=40` | Verlauf beim Start, chronologisch |
| `POST /v1/runs` mit `input` und `session_id` | Nachricht senden, Antwort 202 mit `run_id`; mit Bildern ist `input` eine Nachrichtenliste mit `text`- und `image_url`-Teilen |
| `GET /v1/runs/{id}/events` | Ereignis-Strom (SSE) |
| `POST /v1/runs/{id}/approval` mit `choice` und `request_id` | Freigabe beantworten |
| `POST /v1/runs/{id}/stop` | Run abbrechen |

Der Chat läuft über Runs und nicht über den einfacheren Sessions-Strom
(`/api/sessions/{id}/chat/stream`), weil nur die Runs-API Freigaben nach
außen gibt. Im Ereignis-Strom kommen `message.delta` (Textstücke),
`tool.started` und `tool.completed`, `approval.request` (mit `request_id`,
Befehl, Begründung, `choices`), `approval.responded` und zum Schluss
`run.completed`, `run.failed` oder `run.cancelled`. Das Abschlussereignis
trägt in `output` den vollständigen Antworttext; das Symbol ersetzt damit den
gestreamten Text, falls ein Anbieter keine Deltas liefert.

Das Gespräch heißt `hermes-os-tray` und liegt wie jede Hermes-Session in
`~/.hermes/state.db`; „Neues Gespräch" legt eine Session mit Zeitstempel an
und merkt sich den Namen in `~/.config/hermes-os/tray.json`.

## Bilder

**Hinein.** Beim Senden verkleinert das Symbol jedes angehängte Bild im
Arbeitsthread auf höchstens 1600 Pixel Kantenlänge und kodiert es als PNG
(mit Transparenz) oder JPEG, bis es unter 1,5 MB liegt; höchstens vier Bilder
je Nachricht, der API-Server nimmt 10 MB je Anfrage. Das Bild geht als
`data:image/...`-URL in einem `image_url`-Teil, so wie es auch `/v1/responses`
kennt (`_normalize_multimodal_content` in `gateway/platforms/api_server.py`);
`/v1/runs` reicht den Inhalt der letzten Nachricht so an `run_conversation`
weiter. Kann das gewählte Modell keine Bilder, ersetzt Hermes den Bildteil
selbst durch eine Beschreibung aus `vision_analyze`
(`agent/vision_message_prep.py`); dafür muss ein Vision-Modell erreichbar
sein, bei OpenRouter ist das der Fall. Geprüft am 2026-09-26 gegen das
Gateway in der Test-VM: ein erzeugtes Testbild wurde in gut drei Sekunden
richtig beschrieben.

**Heraus.** Hermes' Werkzeuge legen Dateien als `MEDIA:<pfad>`-Tag in den
Antworttext. Messaging-Plattformen lösen die Tags selbst auf, der
Runs-Endpunkt nicht; `split_media_tags` in `hermes_client.py` löst sie nach
dem Muster von `MEDIA_TAG_CLEANUP_RE` aus dem Text, und das Symbol zeigt die
Dateien, die es lokal findet, in der Blase. Andere Endungen (PDF, Audio)
bleiben als Text stehen.

**Anzeige.** QML-`Image` lädt keine `data:`-URLs, deshalb liegen alle Bilder
als Dateien vor. Bilder aus der Zwischenablage landen als PNG unter
`~/.cache/hermes-os/tray/`, große Bilder bekommen dort eine verkleinerte
Vorschau (`make_preview`), damit der Verlauf keine Fotos in voller Größe im
Speicher hält; Dateien älter als 14 Tage räumt der nächste Start weg. Im
gespeicherten Verlauf ersetzt Hermes Bildteile durch den Platzhalter
`[screenshot]` (`agent/session_persistence.py`); nach einem Neustart des
Symbols sind alte Bilder deshalb nicht mehr zu sehen, das Symbol schreibt
dort „(Bild mitgeschickt)".

## Zustände und Freigaben

| Zustand | Wann | Fenster |
|---|---|---|
| `off` | `/health` antwortet nicht | Hinweis mit „Hermes einrichten" oder „Gateway starten" |
| `nokey` | Gateway läuft, `.env` hat keinen brauchbaren Schlüssel | Hinweis mit „Gateway starten" (ruft das First-Login-Skript, das den Schlüssel anlegt) |
| `ready` | Lebenszeichen und Schlüssel da | Textfeld aktiv |
| `busy` | ein Run läuft | Senden wird zu Stopp |
| `asking` | `approval.request` steht offen | Freigabe-Kasten mit Knöpfen |

Die Benachrichtigung entsteht mit `notify-send --action`, das wartet und die
gewählte Aktion auf stdout schreibt; ihre Laufzeit entspricht
`approvals.timeout`. Beantwortet man im Fenster, wird der wartende
`notify-send` beendet.

**Einschränkung:** Freigaben sieht das Symbol nur für Runs, die es selbst
gestartet hat. Was im Terminal-Chat oder über Messaging-Plattformen ausgelöst
wird, fragt weiter dort. Cron und unbeaufsichtigte Läufe sind in der
Config-Vorlage ohnehin auf `deny`.

## Testen

Ohne Qt, überall mit Python 3.9 oder neuer, auch auf dem Windows-Arbeitsplatz:

```sh
python3 tests/tray-client-check.py --tray-dir files/system/usr/share/hermes-os/tray
```

Startet ein nachgebautes Gateway auf einem freien Port und spielt Lebenszeichen,
Gespräch, Verlauf (auch mit Bildteilen), Senden mit und ohne Bild,
Ereignis-Strom mit Freigabe und Abschluss sowie die MEDIA-Tags durch.
`make lint` führt ihn mit aus.

Ohne Display, mit PySide6 und Kirigami (Image-Build, Test-VM, Aurora-Desktop):

```sh
tests/tray-gui-check.py --qml-dir files/system/usr/share/hermes-os/tray --out /tmp/shots
```

Rendert die Zustände mit einem Stub statt des Gateways, hängt zwei erzeugte
PNGs an, entfernt eines, schickt mit Bild, zeigt Bilder in beiden Blasen,
klickt die Freigabe-Knöpfe und wertet jede QML-Warnung als Fehler. Mit `--out`
entsteht je Schritt ein PNG (off, ready-empty, attachments, typing, streaming,
approval, answered, nokey), gut zum Ansehen nach einer Änderung am Aussehen.
Das Gate (`80-validate.sh`, 7d und 7e) führt beide Tests im Image-Build aus
und prüft dazu `hermes-os-tray --check`, die Desktop-Dateien und das
First-Login-Skript mit einer Wegwerf-`.env`.

Vom Windows-Arbeitsplatz aus läuft der Render-Test per SSH in der Test-VM
(Dateien mit `sed 's/\r$//'` kopieren, siehe `CLAUDE.md`); die PNGs aus
`--out` lassen sich mit `scp` holen und ansehen.

In der Test-VM aus einem Verzeichnis statt aus `/usr`, in die laufende
Sitzung geschoben:

```sh
systemd-run --user --unit hos-tray --collect -p ExitType=cgroup \
  -E HERMES_OS_TRAY_DIR=$HOME/hos/share/hermes-os/tray \
  /usr/bin/python3 $HOME/hos/libexec/hermes-os-tray --show
```

Läuft schon eine Instanz aus `/usr`, bekommt die den `--show`-Befehl; vorher
`pkill -f hermes-os-tray`.

## Stolperfallen

- **Wayland setzt keine Fensterposition.** Das Fenster kann sich nicht selbst
  neben das Symbol legen; KWin merkt sich die letzte Position. Ein Plasma-
  Widget mit echtem Popup wäre der nächste Schritt, wenn das stört.
- **Nur eine Instanz.** Ein lokaler Socket `hermes-os-tray-<uid>` reicht
  „show" an die laufende Instanz weiter; Menüeintrag und Meta+H rufen
  `hermes-os-tray --show`. Bleibt der Socket nach einem Absturz stehen, räumt
  der nächste Start ihn weg.
- **Kurzbefehl**: KGlobalAccel liest Vorgaben aus
  `/usr/share/kglobalaccel/*.desktop` (`X-KDE-Shortcuts`), startet aber die
  gleichnamige Datei unter `applications/`. Beide müssen identisch sein; das
  Gate prüft das. Der Nutzer kann Meta+H in den Systemeinstellungen ändern.
- **Icons über Namen**: Das StatusNotifierItem überträgt Icon-Namen, deshalb
  liegen die Zustände in hicolor. `20-agent-layer.sh` baut den Icon-Cache neu,
  damit ein alter Cache sie nicht verdeckt.
- **`.env` ist die Quelle des Schlüssels.** `hermes setup` und der Assistent
  schreiben dieselbe Datei über Hermes' `save_env_value`; die Zeilen bleiben
  erhalten. Ein Schlüssel unter 16 Zeichen gilt für Hermes als nicht
  vorhanden, das Symbol zeigt dann `nokey`.
- **Gateway ohne API-Server**: Lief das Gateway schon, bevor der Schlüssel in
  `.env` stand, braucht es einen Neustart; das First-Login-Skript macht das
  nur beim Anlegen des Schlüssels.
- **QML-`Image` lädt keine `data:`-URLs** (Status Error), und `sourceSize`
  skaliert kleine Bilder hoch statt nur große zu begrenzen. Deshalb: Bilder
  als Dateien, Vorschauen macht Python (`make_preview`).
- **Delegates hängen nicht im QObject-Baum.** `findChild` aus Python sieht
  Items aus Repeater und ListView nicht; `Main.qml` hat dafür `countNamed`
  und `clickNamed`, die über `children` suchen. PySide verlangt für
  QML-Funktionen alle Parameter, `None` steht für „nicht gesetzt".
- **KDE unterdrückt `console.log`**: `/usr/share/qt6/qtlogging.ini` setzt
  `*.debug=false`; zum Messen in QML `console.info` nehmen.
- **`atYEnd` rechnet den unteren Rand der Liste mit, `positionViewAtEnd`
  nicht.** Wer beides kombiniert, bekommt einen Knopf „nach unten", der nie
  verschwindet; das Fenster prüft stattdessen den Abstand zum Ende.

## Geplant

- Einstellungsfenster „KI-Assistent": Anbieter und Modell (öffnet den
  Assistenten), Gateway, Sprache, die Grenze (`approvals`), erreichbar aus dem
  Symbol und in den Systemeinstellungen über
  `/usr/share/plasma/systemsettings/externalmodules/*.desktop`
  (`X-KDE-System-Settings-Parent-Category`).
- Mikrofon: Aufnahme, Transkription über die Brücke mit dem lokalen Whisper.
- Dashboard-Knopf, sobald Teil 2 gebaut ist.
- Bilder aus Hermes' Antwort schon beim Streamen zeigen (heute erst mit dem
  Abschlussereignis) und Videos oder PDFs aus MEDIA-Tags zum Öffnen anbieten.
- Hübschere Icons; das Symbol im Fensterkopf trägt inzwischen einen
  Statuspunkt in der Farbe des Zustands.
