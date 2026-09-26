# Sehen und Hören

Stand: 2026-09-26. Zwei Wege, Hermes ohne Tippen zu erreichen, beide im
Leisten-Symbol ([systemagent.md](systemagent.md)): ein Bildschirmausschnitt
mit der Frage „Was sehe ich hier?“ und Push-to-Talk mit Antwort per Sprache.
Gebaut, `make lint` und der Test ohne Hardware grün, das Fenster mit Stubs
offscreen gerendert; in der Plasma-Sitzung noch nicht ausprobiert, siehe
[Offen](#offen).

## Was sehe ich hier?

**Meta+Umschalt+H** öffnet Spectacles Auswahlrahmen. Nach Enter oder
Doppelklick geht der Ausschnitt an Hermes:

- **Fenster zu:** Hermes bekommt Bild und Standardfrage („Was sehe ich hier?
  Beschreibe kurz …“) still in einem eigenen Gespräch je Tag
  (`hermes-os-look-<Datum>`), wie beim Nachschlagen aus KRunner
  ([krunner.md](krunner.md)). Die Antwort kommt als Benachrichtigung mit dem
  Ausschnitt als Symbol und dem Knopf **Im Chat besprechen**: der holt Frage,
  Bild und Antwort ins Fenster, hängt den Ausschnitt für die Nachfrage an und
  gibt die Antwort der nächsten Nachricht als Kontext mit. Fragt Hermes dabei
  nach einer Freigabe, wird sie abgelehnt und die Antwort sagt das.
- **Fenster offen** (oder der Kamera-Knopf neben dem Textfeld, oder der
  Menüpunkt am Symbol bei offenem Fenster): der Ausschnitt landet als Anhang,
  die Standardfrage steht im Eingabefeld und lässt sich ändern, Enter schickt
  beides. Das ist der Weg für eine eigene Frage zum Bild.
- Escape im Auswahlrahmen bricht ab, ohne Meldung.

`hermes-os-tray --look "Frage"` macht dasselbe mit eigener Frage, auch aus
Skripten; die laufende Instanz bekommt den Befehl über den lokalen Socket.

## Push-to-Talk

**Meta+Leertaste halten** nimmt auf, loslassen stoppt. Kurz **antippen**
(unter 0,35 s) schaltet die Aufnahme ein, der nächste Druck beendet sie; so
geht es auch mit dem Mikrofon-Knopf im Fenster und `hermes-os-tray --talk`.
Die Aufnahme endet spätestens nach 90 Sekunden. Danach:

1. Die Aufnahme (16 kHz, mono, WAV) geht an den **Sprachhelfer** in der
   Hermes-Venv, der sie mit faster-whisper erkennt: Modell aus
   `stt.local.model`, Sprache aus `stt.local.language` oder `stt.language`
   in `~/.hermes/config.yaml` (die Vorlage setzt `small` und `de`).
2. Der Text geht wie eine getippte Nachricht ins Chat-Fenster (`backend.send`),
   das Fenster öffnet sich, die Antwort kommt gestreamt.
3. Ist die Antwort fertig, liest Piper sie vor (Stimme aus `tts.piper.voice`,
   Vorlage `de_DE-thorsten-medium`), ohne Markdown, Tabellen als Aufzählung,
   Links als „Link“, höchstens 1500 Zeichen, den Rest zeigt das Fenster.

Während Hermes zuhört, ist das Leisten-Symbol rot mit Mikrofon und der Kopf
des Fensters sagt „Hermes hört zu …“; während er spricht, blau mit
Lautsprecher. Ein Druck auf das Kürzel, während Hermes spricht, unterbricht
ihn und nimmt auf; der Mikrofon-Knopf im Fenster wird in beiden Zuständen zum
Stopp. Beim ersten Gebrauch lädt der Helfer das Whisper-Modell und die Stimme
herunter; der Kopf sagt dann „Lade Sprachmodell small …“.

Ohne Mikrofon (keine Eingabequelle laut `pactl list short sources`, Monitore
zählen nicht) kommt eine Benachrichtigung „Hermes kann nicht zuhören“; eine
leere Aufnahme (pw-record bricht ohne Quelle nicht ab, die Datei bleibt bei 0
Sekunden) meldet „Hermes hat nichts gehört“. Ohne Gateway sagt die Meldung,
was verstanden wurde. Nichts davon stürzt ab; der Zustand geht zurück auf
`idle`.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `files/system/usr/share/hermes-os/tray/desktop.py` | gemeinsame Helfer: Tastenfolgen im Qt-Format, Kollisionsliste, `notify` und `notify_actions` (notify-send mit Knöpfen), `GlobalShortcut` (KGlobalAccel über D-Bus mit Drücken und Loslassen) |
| `files/system/usr/share/hermes-os/tray/screenshot.py` | Spectacle-Aufruf, `LookFlow` (Ablauf ohne Qt), `install()` mit `look` für Main.qml |
| `files/system/usr/share/hermes-os/tray/voice.py` | Rekorder (pw-record, parecord, arecord), Mikrofon-Prüfung, `Worker` (Sprachhelfer als Prozess), `PushToTalk` (Zustandsautomat), Text fürs Vorlesen, `install()` mit `voice` für Main.qml |
| `files/system/usr/share/hermes-os/tray/voice_worker.py` | läuft mit der Venv-Python: faster-whisper und Piper, JSON-Zeilen auf stdin/stdout, `--check` fürs Gate |
| `files/system/usr/share/hermes-os/tray/dbus_peer.py` | neu: `add_match`, `subscribe`, `emit_signal` für Signale |
| `files/system/usr/share/applications/hermes-os-sehen.desktop`, dieselbe Datei unter `kglobalaccel/` | Menüeintrag „Hermes: Was sehe ich hier?“ mit `X-KDE-Shortcuts=Meta+Shift+H`, `Exec=hermes-os-tray --look` |
| `files/system/usr/share/icons/hicolor/scalable/status/hermes-os-tray-{listening,speaking}.svg` | Zustände hört zu und spricht |
| `files/system/usr/libexec/hermes-os-tray` | Registrierung: `--look`, `--talk`, Socket-Befehle `look` und `talk`, Menüpunkte, `answerFinished`, `discussAnswer` |
| `files/system/usr/share/hermes-os/tray/Main.qml` | Zustandsanzeige im Kopf, Kamera- und Mikrofon-Knopf |
| `tests/sehen-hoeren-check.py` | Test ohne Hardware und ohne Qt, siehe unten |

Der Sprachhelfer ist ein eigener Prozess, weil das Leisten-Symbol mit Fedoras
Python und PySide6 läuft, faster-whisper und Piper aber in der Hermes-Venv
(Python 3.13) liegen. Er startet beim ersten Auftrag, hält die Modelle geladen
und beendet sich nach zehn Minuten ohne Auftrag. Erkennung und Synthese gehen
zuerst über Hermes' eigene Helfer (`tools.transcription_tools.
transcribe_audio_local_fallback`, der `stt.*` vollständig auswertet, dazu
`tools.voice_mode.is_whisper_hallucination`); Piper wird direkt aufgerufen,
mit der Stimme aus dem Ordner, den auch Hermes benutzt
(`~/.hermes/cache/piper-voices`, ein gefüllter Alt-Ordner
`piper_voices_cache` oder `tts.piper.voices_dir`), fehlt sie, lädt
`python -m piper.download_voices` sie dorthin. Sind Hermes' Helfer nicht
importierbar, ruft der Helfer faster-whisper direkt, mit denselben Argumenten
wie Hermes (`beam_size 5`, VAD, Schwellen für `no_speech_prob` und
`avg_logprob`). Nichts davon hat eine Stabilitätszusage; das Gate prüft die
Importe bei jedem Build, ein Hermes-Bump prüft `voice_worker.py --check` in
der Venv.

Schwere Arbeit läuft nie im GUI-Thread: Aufnahme beenden, Erkennung, Synthese
und Abspielen sitzen in Arbeitsthreads oder im Helferprozess und melden sich
über ein Qt-Signal zurück; `PushToTalk` sieht nur Ereignisse im Hauptthread.

## Kürzel

| Kürzel | Weg | Warum so |
|---|---|---|
| Meta+Umschalt+H | Desktop-Datei unter `/usr/share/kglobalaccel/`, kglobalacceld startet `hermes-os-tray --look` | wie Meta+H, frei in Plasma 6, passt zum Fenster-Kürzel; nur Drücken nötig |
| Meta+Leertaste | die laufende Instanz meldet sich bei `org.kde.kglobalaccel` an (Komponente `hermes-os-voice`, „Hermes: Sprechen“) und bekommt `globalShortcutPressed` und `globalShortcutReleased` | Halten braucht ein Loslassen, und das gibt es nur auf diesem Weg; eine Desktop-Datei startet nur Programme. Meta+Leertaste ist in KWin, Plasma und Spectacle frei; nur fcitx5 benutzt es zum Wechsel der Eingabemethode, wenn es eingeschaltet ist |

Beide lassen sich in den Systemeinstellungen unter Tastenkürzel ändern
(Anwendungen „Hermes: Was sehe ich hier?“ und Komponente „Hermes: Sprechen“);
kglobalacceld gibt beim Anmelden die gespeicherte Wahl zurück, das Fenster
zeigt sie im Tooltip des Mikrofon-Knopfs. Gegen kglobalacceld gilt: es
beobachtet seine Anmelder nicht, deshalb gibt das Symbol beim Beenden das
Kürzel mit `setInactive` frei und meldet sich neu an, wenn `org.kde.kglobalaccel`
einen neuen Besitzer bekommt (KWin neu gestartet). Seit Plasma 6.7 speichert
kglobalacceld ein schon belegtes Kürzel trotzdem und die zuerst angemeldete
Aktion gewinnt still; das Symbol fragt mit `globalShortcutAvailable` nach und
schreibt eine Warnung ins Journal.

## Testen

Ohne Qt, ohne Audio, überall mit Python 3.9 oder neuer:

```sh
python3 tests/sehen-hoeren-check.py      # läuft auch in make lint und im Gate (80-validate.sh, 7l)
```

Prüft die Desktop-Datei (beide Kopien identisch, Kürzel, Exec,
`desktop-file-validate` falls vorhanden), Tastenfolgen und Kollisionen, die
Anmeldung bei KGlobalAccel gegen ein nachgebautes kglobalacceld auf einem
privaten Bus (`doRegister`, `setShortcutKeys` als `a(ai)`, `getComponent`,
Signale für Drücken und Loslassen, gespeicherte Belegung, `setInactive`),
`notify_actions` gegen ein nachgebautes notify-send, Aufnahmebefehle,
Mikrofon-Prüfung, den Rekorder gegen einen nachgebauten Prozess, den
Zustandsautomaten mit allen Wegen, den Sprachhelfer gegen Attrappen von
`faster_whisper` und `piper` (Modell und Sprache aus `config.yaml`, Filter der
Segmente, Synthese, Frist, Leerlauf) und den Bildweg gegen einen nachgebauten
Client (Bild als data-URL im Run, Benachrichtigung, Knopf, Anhang bei offenem
Fenster). Fehlt `dbus-daemon`, wird der Bus-Teil übersprungen.

Im Image-Build prüft das Gate zusätzlich `voice_worker.py --check` mit der
Venv-Python (faster-whisper, Piper und Hermes' Helfer importierbar) und
`tests/tray-gui-check.py` rendert die Sprachzustände im Fenster mit Stubs für
`voice` und `look`.

In der Test-VM (siehe [testumgebung.md](testumgebung.md)), mit einer Testfassung
aus dem Home wie in [systemagent.md](systemagent.md):

```sh
busctl --user call org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel \
  shortcutKeys as 4 hermes-os-voice push-to-talk "Hermes: Sprechen" "Mit Hermes sprechen"   # Kürzel angemeldet?
pactl list short sources                                   # Mikrofon da?
HERMES_HOME=$HOME/.hermes /usr/lib/hermes-agent/.venv/bin/python \
  /usr/share/hermes-os/tray/voice_worker.py --check         # Helfer in der Venv
spectacle -i -b -n -r -o /tmp/test.png                     # Auswahlrahmen ohne Fenster
/usr/libexec/hermes-os-tray --look "Was steht da?"         # Bildweg
/usr/libexec/hermes-os-tray --talk                         # Aufnahme ein, noch einmal: aus
journalctl --user -u hos-tray -f                           # Warnungen des Symbols
```

## Stolperfallen

- **`spectacle --background` liefert ein eingefrorenes Bild**, wenn die Anzeige
  per DPMS aus ist ([testumgebung.md](testumgebung.md)). Für den Auswahlrahmen
  ist die Anzeige an; beim Aufruf per Skript vorher `kscreen-doctor --dpms on`.
- **Spectacle ist eine Unique-Anwendung.** Läuft schon ein Spectacle, gibt ein
  zweiter Aufruf seine Argumente an das erste weiter und endet sofort; auf den
  Prozess zu warten sagt dann nichts. Deshalb `--new-instance`. Escape endet
  mit Exit 0 ohne Datei; die Zieldatei wird vorher gelöscht, „keine Datei“
  heißt abgebrochen.
- **Das Screenshot-Portal hat keinen Bereichsmodus.** Interaktiv zeigt
  xdg-desktop-portal-kde nur Vollbild, Bildschirm, Fenster; ohne Dialog nimmt
  es den ganzen Bildschirm und fragt einmal nach Erlaubnis. KWins
  `ScreenShot2` kann Bereiche, aber nur mit Koordinaten. Deshalb Spectacle.
- **QML `Image` lädt keine data-URLs:** der Ausschnitt bleibt als Datei unter
  `~/.cache/hermes-os/tray/ausschnitt-*.png` (14 Tage), zum Gateway geht die
  data-URL wie bei jedem Anhang.
- **Eine Desktop-Datei sendet kein Loslassen.** `KServiceActionComponent`
  reagiert nur auf Drücken. Push-to-Talk meldet sich deshalb selbst an, unter
  einem eigenen Komponentennamen, nicht `hermes-os-tray.desktop`: unter dem
  Namen führt kglobalacceld die Desktop-Datei, und die sendet keine Signale.
- **Loslassen kommt beim ersten losgelassenen Teil** des Kürzels, Meta oder
  Leertaste. Tastenwiederholung kommt seit Plasma 6.5 als eigenes Signal
  `globalShortcutRepeated`, das das Symbol ignoriert; ein zweites „Pressed“
  bei gehaltener Taste (ältere Plasma) verhallt im Automaten.
- **pw-record bricht ohne Mikrofon nicht ab**, es schreibt 0 Frames. Deshalb
  die Prüfung vorher und die Längenprüfung danach; SIGINT lässt pw-record den
  WAV-Kopf sauber schreiben.
- **faster-whisper und Piper laufen nicht mit Fedoras Python.** Der
  Sprachhelfer ist ein Prozess mit der Venv-Python; `HERMES_OS_VOICE_PYTHON`
  überschreibt den Interpreter für Tests. Hermes' `tools.*`-Helfer haben keine
  Stabilitätszusage; fehlen sie, geht der direkte Weg.
- **Das Whisper-Modell landet im Hugging-Face-Cache** (`~/.cache/huggingface/hub`),
  Hermes setzt kein `download_root`; Terminal-Chat und Leisten-Symbol teilen
  sich damit die Datei. `small` ist rund 460 MB, der erste Aufruf braucht Netz.
- **Sprache ist Englisch, wenn `stt.language` fehlt:** Hermes' Vorgabe ist
  `en`. Die Config-Vorlage setzt `de`; wer die Vorlage nicht nutzt, sollte
  den Schlüssel setzen, sonst versteht Whisper deutsche Fragen als Englisch.

## Offen

- Test in VM 112: Auswahlrahmen aus dem Hintergrund, Benachrichtigung mit Bild
  und Knopf, Anhang bei offenem Fenster; Anmeldung bei KGlobalAccel (Eintrag in
  den Systemeinstellungen, Drücken und Loslassen, Verhalten nach `kwin_wayland
  --replace`); Mikrofon und Lautsprecher in der VM (Audio-Gerät in Proxmox),
  erster Download von Modell und Stimme, Latenz von Erkennung und Synthese auf
  der CPU; Tastenwiederholung; Meta+Leertaste gegen fcitx5, falls
  eingeschaltet.
- Antwort schon beim Streamen sprechen (satzweise), heute erst nach dem
  Abschluss des Runs.
- Eigene Frage ohne Fenster: eine Benachrichtigung mit Eingabefeld
  (`inline-reply`) kann Plasma, `notify-send` gibt die Antwort aber nicht
  zurück; dafür bräuchte es einen eigenen Aufruf von
  `org.freedesktop.Notifications` über `dbus_peer`.
- Wake-Word aus dem Leisten-Symbol; heute nur Kürzel und Knopf.
