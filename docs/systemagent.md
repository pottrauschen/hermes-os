# Systemagent: das Leisten-Symbol

Stand: 2026-09-30. Wie Hermes am Desktop sichtbar wird, ohne Terminal und ohne
ein Fenster, das dauernd offen steht: ein Symbol in der Systemleiste, das
Kontor (das Chat-Fenster, Titel „Hermes-Kontor“) mit Sprechblasen und
Bildern, Freigaben als Benachrichtigung.
Gebaut, durch Gate und Tests gelaufen, das Fenster offscreen in der Test-VM
gerendert und der Bildweg gegen das echte Gateway geprüft. Seit dem 26. und
27.09. sind Symbol und Kontor in der Plasma-Sitzung von VM 112 im täglichen
Gebrauch; Freigabe-Kasten und -Benachrichtigung liefen dort am 27.09. in einer
Einzelprüfung.

## Was es tut

- **Symbol in der Systemleiste** (StatusNotifierItem über `QSystemTrayIcon`)
  mit vier Zuständen: grau (Gateway aus oder Schlüssel fehlt), blau (bereit),
  orange (arbeitet), gelb (fragt nach einer Freigabe). Der Tooltip nennt den
  Zustand und die Hermes-Version.
- **Klick oder Meta+H** öffnet ein Kirigami-Fenster wie einen Messenger: oben
  das Hermes-Symbol als Gegenüber, unten rechts daran ein Punkt in der Farbe
  des Zustands, daneben der Zustand als Text („Hermes ist bereit“), rechts die
  Knöpfe Bibliothek, Protokoll, Neu und Einrichten (im breiten Fenster mit
  Namen, im schmalen als Symbole mit Erklärung). Verlauf und Eingabe stehen in
  einer Lesespalte von höchstens 36 Rastereinheiten (gut 70 Zeichen), im
  breiten Fenster mittig. Eigene Nachrichten stehen rechts in einer Blase in
  gedämpfter Akzentfarbe (höchstens 80 % der Spalte), Antworten von Hermes
  links in einer grauen Blase (85 %), Fehler in einer roten; die Ecke zum
  Absender hin ist spitzer. Bilder erscheinen als kleine Karte über der
  Nachricht. Unter jeder Nachricht steht klein und blass, wer wann geschrieben
  hat („Hermes · 18:31“, bei eigenen nur die Uhrzeit), bei älteren Tagen mit
  Datum. Text im Verlauf ist eine Stufe größer als die Bedienelemente
  (Systemschrift mal 1,1, die Schriftart bleibt die des Systems). Antworten
  setzt `tray/chat_text.py` aus dem Markdown: Luft unter jedem Absatz, etwas
  mehr Zeilenhöhe, Listen schmal eingerückt; das Textfeld von Kirigami kann
  beides nicht. Antworten kommen gestreamt.
  Solange Hermes arbeitet und gerade nichts schreibt, pulsieren am Ende des
  Verlaufs drei Punkte in einer kleinen Blase von Hermes: gleich nach dem
  Senden und zwischen zwei Werkzeugschritten (Eigenschaft `waiting` des
  Backends). Jeder
  Werkzeugaufruf ist ein Kärtchen („✓ os_status · 0,3 s“), das beim Start
  erscheint und am Ende Dauer oder Fehler bekommt; Text danach beginnt eine
  neue Blase unter den Kärtchen. Hinweise des Systems
  („Freigabe: Einmal erlaubt“) stehen zwischen zwei feinen Linien. Vor jeder
  neuen Frage ist mehr Luft als zwischen den Teilen einer Antwort. Text lässt
  sich markieren und kopieren, Markdown wird gerendert. Enter sendet,
  Umschalt+Enter macht eine neue Zeile (steht in der Erklärung am runden
  Senden-Knopf). Ein leerer Verlauf zeigt die Begrüßung als erste Blase von
  Hermes und rechts unten, wo die eigene Nachricht hinkäme, drei Vorschläge
  als Pillen; ein Klick schickt den Vorschlag ab. Escape versteckt das
  Fenster, Schließen ebenso; das Symbol bleibt.
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
- **Bibliothek**: Der Knopf im Kopf und der Menüpunkt am Symbol öffnen eine
  Seite, auf der Adressen, Dateien und Ordner eingetragen werden (auch per
  Ablegen), die Hermes bei Bedarf liest; dazu Spiegeln mit Fortschritt, eine
  Suche in den Spiegeln und die Schalter der Doku-Server; Details in
  [bibliothek.md](bibliothek.md).
- **Protokoll**: Der Knopf mit der Uhr im Kopf und der Menüpunkt am Symbol
  öffnen eine Seite mit allem, was Hermes am System getan hat: Freigaben mit
  Entscheidung, Systembefehle mit Ergebnis, App-Starts; Details in
  [protokoll.md](protokoll.md). Ein Klick auf eine Freigabe landet dort auch.
- **Sehen und Hören**: Meta+Umschalt+H wählt einen Bildschirmausschnitt und
  fragt Hermes, was darauf zu sehen ist; Meta+Leertaste halten nimmt eine Frage
  auf, der erkannte Text geht ins Fenster, die Antwort wird vorgelesen. Der
  Kamera-Knopf neben dem Textfeld hängt einen Ausschnitt an, der Mikrofon-Knopf
  schaltet die Aufnahme ein und aus; während Hermes zuhört oder spricht, zeigt
  das Symbol einen eigenen Zustand (rot mit Mikrofon, blau mit Lautsprecher).
  Details in [sehen-hoeren.md](sehen-hoeren.md).
- **Menü am Symbol**: Kontor öffnen, neues Gespräch, Bibliothek, Protokoll, Was
  sehe ich hier?, Mit Hermes sprechen, Dashboard öffnen, Hermes einrichten,
  Gateway starten, Chat im Terminal, Beenden. „Dashboard öffnen" startet das
  Fenster `/usr/libexec/hermes-os-dashboard` ([dashboard.md](dashboard.md)) und
  erscheint nur, wenn es ausführbar ist.
- **Autostart** bei jeder Plasma-Sitzung. Beim allerersten Login sagt das
  Symbol „nicht eingerichtet" und bietet den Assistenten an; nach dem
  Speichern schaltet das First-Login-Skript das Gateway ein, und das Symbol
  wird von selbst blau.

## Dateien

| Was | Wo |
|---|---|
| Startprogramm, Python mit PySide6 | `files/system/usr/libexec/hermes-os-tray` |
| Fenster, QML mit Kirigami | `files/system/usr/share/hermes-os/tray/Main.qml` |
| Client für den API-Server, nur Standardbibliothek | `files/system/usr/share/hermes-os/tray/hermes_client.py` |
| Antworten als HTML mit Absatzabständen für den Verlauf (QTextDocument) | `files/system/usr/share/hermes-os/tray/chat_text.py` |
| Kürzel und Benachrichtigungen mit Knöpfen, KGlobalAccel über D-Bus | `files/system/usr/share/hermes-os/tray/desktop.py` |
| Sprache der Oberfläche: `is_english`, Wörterbuch `EN`, `DictTranslator` für `Main.qml` | `files/system/usr/share/hermes-os/tray/lang.py`, für Grenze und Protokoll `plugins/hermes_os/lang.py` |
| „Was sehe ich hier?“ und Push-to-Talk, Sprachhelfer in der Hermes-Venv | `files/system/usr/share/hermes-os/tray/screenshot.py`, `voice.py`, `voice_worker.py`, siehe [sehen-hoeren.md](sehen-hoeren.md) |
| Menüeintrag „Hermes", trägt `X-KDE-Shortcuts=Meta+H` | `files/system/usr/share/applications/hermes-os-tray.desktop` |
| Dieselbe Datei für den globalen Kurzbefehl | `files/system/usr/share/kglobalaccel/hermes-os-tray.desktop` |
| Autostart in der Plasma-Sitzung | `files/system/etc/xdg/autostart/hermes-os-tray.desktop` |
| Programmsymbol (geflügelte Sprechblase mit H, Pixel-Art als SVG, ein Pfad je Farbe) und die sechs Zustände (aus, bereit, arbeitet, fragt, hört zu, spricht) | `files/system/usr/share/icons/hicolor/scalable/{apps,status}/` |
| Client-Test gegen ein nachgebautes Gateway | `tests/tray-client-check.py` |
| Render-Test des Fensters ohne Display | `tests/tray-gui-check.py` |
| Sprach-Test: Wörterbücher, Abdeckung, Übersetzer an der echten `Main.qml` | `tests/lang-check.py` |
| Schaubilder des Fensters für Design-Änderungen (breit und schmal mit echt wirkendem Gespräch, dazu Begrüßung und tippende Punkte) | `tests/tray-showcase.py` |

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

## Sprache der Oberfläche

Deutsch ist die Vorgabe, wie das ganze System ab Werk. Ist die Sitzung
englisch, zeigen Kontor, Menü am Symbol, Tooltip, Benachrichtigungen,
Freigabe-Kasten, Bibliothek und Protokoll englische Texte, etwa für eine
Demo-Aufnahme. Es gibt kein gettext und keine `.qm`-Dateien (im Image fehlt
`lrelease`): der deutsche Text ist der Schlüssel, das Wörterbuch `EN` in
`tray/lang.py` liefert den englischen dazu.

- **Wer entscheidet:** `lang.is_english()`, bei jedem Aufruf aus der Umgebung.
  `HERMES_OS_LANG=en` oder `de` gewinnt. Sonst zählt der erste nicht leere Wert
  aus `LANGUAGE` (nur der Eintrag vor dem ersten Doppelpunkt), `LC_ALL`,
  `LC_MESSAGES` und `LANG`: englisch, wenn er mit `en` beginnt. Es zählt nur
  dieser erste Wert, `LC_ALL=C.UTF-8` mit `LANG=en_US.UTF-8` bleibt deutsch,
  ebenso `LANGUAGE=de` mit `LANG=en_US.UTF-8`.
- **QML:** Jeder sichtbare Text in `Main.qml` steht deutsch in `qsTr("…")`,
  Zahlen und Kürzel über `qsTr("… %1 …").arg()`. In englischer Sitzung
  installiert `hermes-os-tray` vor dem Laden von `Main.qml` einen
  `DictTranslator` (Unterklasse von `QTranslator` in `tray/lang.py`); in
  deutscher Sitzung keinen, dann liefert `qsTr` den Quelltext.
- **Python:** `_()` aus `tray/lang.py` dort, wo ein Text das Programm verlässt:
  Eigenschaft für QML, Benachrichtigung, Menü, Meldung im Verlauf. Konstanten
  wie `STATE_TEXT`, `CHOICE_LABEL`, `EFFORTS`, `DEFAULT_QUESTION` und `ACTIONS`
  bleiben deutsch, weil Tests gegen sie vergleichen.
- **Plugin:** Grenze (`boundary.py`) und Protokoll (`audit.py`) haben ein
  eigenes kleines Wörterbuch, `plugins/hermes_os/lang.py`, mit derselben
  `is_english` als Code-Kopie; das Plugin läuft im Gateway, das Symbol lädt
  `audit.py` über den Pfad, keiner kennt den Ordner des anderen. Die Meldung
  der Grenze entsteht im Gateway und folgt dessen Umgebung; die Backticks um
  den Befehl bleiben in jeder Sprache, weil `hermes_client.approval_command`
  ihn daraus liest. Die Zeilen des Protokolls baut das Symbol beim Lesen, sie
  folgen seiner Sprache.
- **Formate:** Dauer im Verlauf „0,3 s“ oder „0.3 s“, ohne Angabe „fertig“
  oder „done“; Datum im Verlauf „03.10. 18:31“ oder „Oct 03 18:31“ (Monatsnamen
  aus `lang.MONTHS`); Datum im Protokoll `29.09.2026` oder `2026-09-29`.
- **Bleibt deutsch:** Meldungen von `library.py` auf der Seite Bibliothek,
  Fehlertexte des Gateways (`GatewayError`) und des Sprachhelfers
  (`voice_worker.py`), der Vorspann für Kontext an den Agenten
  (`hermes_client.with_context`), Namen der Kürzel in den Systemeinstellungen
  (`desktop.py`), Einrichtungsassistent, Dashboard, Morgenbericht und der
  System-Prompt des Plugins. In welcher Sprache Hermes antwortet, erkennt
  (`stt.language`) und vorliest (`tts.piper.voice`), steht in
  `~/.hermes/config.yaml`.
- **Umschalten:** Sprache der Plasma-Sitzung auf Englisch stellen
  (Systemeinstellungen, Region und Sprache; gilt nach der nächsten Anmeldung),
  oder nur für Hermes `HERMES_OS_LANG=en` in
  `~/.config/environment.d/hermes-os-lang.conf`. Danach das Symbol und
  `hermes-gateway` neu starten, sonst behalten beide ihre alte Umgebung. Die
  Autostart-Dateien und der KRunner-Eintrag tragen `[en]`-Schlüssel.
- **Neue Texte:** deutsch schreiben, in `qsTr()` oder `_()` einwickeln, im
  Wörterbuch einen EN-Eintrag anlegen. `tests/lang-check.py` findet fehlende
  Schlüssel, vergessene Literale in `Main.qml`, abweichende Platzhalter und
  Funktionen, die `_` als Wegwerfnamen binden.

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
prüft die Antwort als HTML aus `chat_text.py` mit „Hermes · Uhrzeit“
darunter, klickt die Freigabe-Knöpfe und wertet jede QML-Warnung als Fehler. Mit `--out`
entsteht je Schritt ein PNG (off, ready-empty, attachments, typing, streaming,
approval, answered, nokey), gut zum Ansehen nach einer Änderung am Aussehen.
Das Gate (`80-validate.sh`, 7d und 7e) führt beide Tests im Image-Build aus
und prüft dazu `hermes-os-tray --check`, die Desktop-Dateien und das
First-Login-Skript mit einer Wegwerf-`.env`.

Die Sprache prüft `tests/lang-check.py`: Teil 1 bis 4 ohne Qt, auch unter
Windows; der Qt-Teil lädt die echte `Main.qml` mit den Stubs aus
`tray-gui-check.py`, ohne Übersetzer deutsch, mit `DictTranslator` englisch
und danach wieder deutsch. Das Gate führt ihn in 7d aus.

```sh
python3 tests/lang-check.py --tray-dir files/system/usr/share/hermes-os/tray \
  --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
```

`audit-check.py`, `model-choice-check.py`, `runner-check.py` und
`sehen-hoeren-check.py` vergleichen deutsche Texte und setzen deshalb selbst
`HERMES_OS_LANG=de`; sie bestehen auch in einer englischen Sitzung.
Englische Schaubilder zeichnet `tests/tray-showcase.py --lang en`.

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
  `hermes-os-tray --show`. Der Knopf „Im Chat besprechen" am Morgenbericht
  schickt auf demselben Weg `discuss <pfad>` (`--discuss`), siehe
  [morgenbericht.md](morgenbericht.md); Meta+Umschalt+H schickt `look`
  (`--look`), `--talk` schaltet die Aufnahme um. Bleibt der Socket nach einem Absturz stehen, räumt
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
  verschwindet; das Fenster prüft stattdessen den Abstand zum Ende. Dazu
  gehört `originY`: die ListView verschiebt ihren Anfang, wenn Zeilen oberhalb
  die Höhe ändern, ohne ihn stand der Knopf auch am Ende (VM 112, 29.09.).
- **Keine `Column` um das Textfeld einer Blase.** Eine Column misst ihre Höhe
  erst beim nächsten Layout; mit dem Nachführen ans Ende (`positionViewAtEnd`
  bei jeder neuen Inhaltshöhe) legte die ListView die Zeilen immer wieder neu
  an, der Render-Test hing. Das Textfeld sitzt deshalb direkt in der Blase.
- **Das Textfeld kennt keinen Absatz- und Zeilenabstand.**
  `Kirigami.SelectableLabel` ist ein TextEdit, ohne `lineHeight`, und das
  Markdown setzt Qt eng. `chat_text.py` setzt die Abstände in einem
  QTextDocument und gibt HTML ab; Schriftart und -größe aus dessen Kopf
  fallen weg, sonst gewänne die Schrift des Python-Dokuments über die des
  Textfelds. PySide liest `textFormat` nicht (kein Konverter für die
  Aufzählung); der Render-Test erkennt das HTML am Inhalt.

- **`_` ist kein Wegwerfname.** Ruft eine Funktion `_()`, macht ein
  `a, _ = …` darin den Namen in der ganzen Funktion lokal, und `_()` wirft
  `UnboundLocalError`. Wegwerfwerte heißen deshalb `_filter`, `_tool` oder
  ähnlich; `tests/lang-check.py` prüft das.
- **`strftime("%b")` folgt der Locale.** `QApplication` ruft
  `setlocale(LC_ALL, "")`; danach liefert `%b` in einer deutschen Sitzung
  „Okt“, auch wenn `HERMES_OS_LANG=en` gilt. Englische Monatsnamen kommen aus
  `lang.MONTHS`.
- **Der Übersetzer braucht `isEmpty() == False`**, sonst meldet
  `installTranslator` False und schickt kein LanguageChange. Qt fragt auch
  eigene Kontexte ab (`QGuiApplication`, `QIODevice`); für sie liefert der
  Übersetzer `None` (Null-QString), dann nimmt Qt den Quelltext. Ein leerer
  Text `""` wäre für PySide6 ein gültiges Ergebnis und ließe Qt-eigene Menüs
  (Cut, Copy, Paste) leer.

## Geplant

- Einstellungsfenster „KI-Assistent": Anbieter und Modell (öffnet den
  Assistenten), Gateway, Sprache, die Grenze (`approvals`), erreichbar aus dem
  Symbol und in den Systemeinstellungen über
  `/usr/share/plasma/systemsettings/externalmodules/*.desktop`
  (`X-KDE-System-Settings-Parent-Category`).
- Dashboard-Knopf auch im Fensterkopf; heute nur im Menü am Symbol.
- Bilder aus Hermes' Antwort schon beim Streamen zeigen (heute erst mit dem
  Abschlussereignis) und Videos oder PDFs aus MEDIA-Tags zum Öffnen anbieten.
- Hübschere Icons; das Symbol im Fensterkopf trägt inzwischen einen
  Statuspunkt in der Farbe des Zustands.
