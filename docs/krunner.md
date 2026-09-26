# KRunner: Hermes fragen

Alt+Leertaste öffnet KRunner. Wer dort `hermes <Frage>` tippt, kurz `h: <Frage>`,
bekommt oben den Treffer „Hermes fragen: <Frage>“. Enter öffnet das Chat-Fenster
des Leisten-Symbols und schickt die Frage sofort ab. Die Aktion „Nur
nachschlagen“ am Treffer (Knopf rechts im Treffer) fragt Hermes, ohne
das Fenster zu öffnen, und bringt die Antwort als Benachrichtigung.

Erkannt werden `hermes` mit Leerzeichen, Doppelpunkt oder Komma dahinter und
`h:`, Groß- und Kleinschreibung egal: `Hermes: …`, `hermes, …`, `H:…`. Die Frage
bleibt, wie sie getippt wurde. `hermes` allein, `h:` ohne Frage, `hermesfoo`
oder `hermes-os` liefern keinen Treffer; `hermes` allein findet weiter den
Menüeintrag „Hermes“.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `files/system/usr/share/krunner/dbusplugins/hermes-os.desktop` | meldet den Runner bei KRunner an: `X-Plasma-API=DBus`, Dienst `io.github.pottrauschen.hermesos.tray*`, Pfad `/runner`, Filter-Regex und Mindestlänge |
| `files/system/usr/share/hermes-os/tray/runner.py` | Präfix, Treffer, Aktionen, Run, wartende Frage, Nachschlagen; `install()` hängt den Runner an die Qt-Schleife des Leisten-Symbols |
| `files/system/usr/share/hermes-os/tray/dbus_peer.py` | kleine D-Bus-Anbindung mit Standardbibliothek: Anmeldung, Hello, RequestName, Drahtformat lesen und schreiben |
| `files/system/usr/libexec/hermes-os-tray` | ruft nach dem Start `runner.install(...)` auf; `--check` prüft, dass `runner.py` importierbar ist |

Der Runner läuft im Prozess des Leisten-Symbols, weil dort Ereignisschleife,
Gateway-Client und Fenster schon sind. KRunner spricht ihn über
`org.kde.krunner1` an:

- **Match(s) → a(sssida{sv})**: ein Treffer (ID `frage:<Frage>`, Text, Symbol
  `hermes-os`, Kategorie-Relevanz 100 = Highest, Relevanz 1.0, Eigenschaften
  `subtext`, `category`, `actions`), sonst eine leere Liste.
- **Actions → a(sss)**: `lookup`, „Nur nachschlagen“. Wegen
  `X-Plasma-Request-Actions-Once=true` fragt KRunner das nur einmal ab.
- **SetActivationToken(s)**: kommt unter Wayland direkt vor Run; das Token
  landet in `XDG_ACTIVATION_TOKEN`, Qt nimmt es beim Aktivieren des Fensters.
- **Run(ss)**: leere Aktion schickt die Frage ins Fenster, `lookup` schlägt nach.
- **Teardown**, **Config** (nur bei `DBus2`), **Introspect**, **Ping**.

Der Dienstname in der Desktop-Datei endet auf `*`. Dann ruft KRunner nur
Dienste, die gerade auf dem Bus sind, und versucht keine D-Bus-Aktivierung:
läuft das Leisten-Symbol nicht, gibt es keinen Treffer und kein Fehlerprotokoll.
Der Filter `X-Plasma-Runner-Match-Regex` sorgt dafür, dass KRunner Match nur für
Eingaben mit Präfix aufruft.

**Ins Fenster:** Das Fenster geht sofort auf. Ist Hermes bereit (Gateway an,
Verlauf geladen, kein Run offen), geht die Frage gleich los, sonst wartet sie bis
zu 90 Sekunden und geht los, sobald es passt; eine neuere Frage aus KRunner
ersetzt eine wartende. Klappt es in der Zeit nicht, steht die Frage im
Eingabefeld und eine Benachrichtigung sagt es. Die Frage geht über denselben Weg
wie eine getippte (`backend.send`), also auch mit Bildern, die gerade als Anhang
im Fenster liegen.

**Nur nachschlagen:** eigener Run im Gespräch `hermes-os-krunner-<Datum>`, ein
Gespräch je Tag, damit Nachfragen am selben Tag Zusammenhang haben und der
Fenster-Verlauf sauber bleibt. Die Antwort kommt als `notify-send`, gekürzt auf
900 Zeichen, `MEDIA:`-Pfade entfernt. Fragt Hermes dabei nach einer Freigabe,
lehnt der Nachschlag sie ab und sagt das in der Benachrichtigung: ohne Fenster
erteilt niemand bewusst eine Freigabe. Nach 180 Sekunden wird der Run gestoppt.

## Testen

```sh
python3 tests/runner-check.py            # läuft auch in make lint und im Gate (80-validate.sh, 7h)
```

Der Test braucht weder Qt noch Hermes noch Plasma. Er prüft Präfix-Erkennung,
Umlaute, leere Eingabe, Treffer und Relevanz, Run, die wartende Frage, das
Nachschlagen gegen einen nachgebauten Client, das Drahtformat und die
Desktop-Datei (Pflichtschlüssel, Dienstname und Pfad passen zu `runner.py`,
Filter passt zur Erkennung, `desktop-file-validate` falls vorhanden). Gibt es
`dbus-daemon` und `dbus-send`, startet er einen privaten Bus und ruft Match, Run,
Actions und Introspect über den echten Bus auf.

In der Plasma-Sitzung (VM 112):

```sh
busctl --user list | grep hermesos                        # Name gehört dem Leisten-Symbol
gdbus call --session -d io.github.pottrauschen.hermesos.tray -o /runner \
  -m org.kde.krunner1.Match 'hermes Wie spät ist es?'     # Treffer als a(sssida{sv})
kquitapp6 krunner                                         # KRunner liest dbusplugins neu
```

Danach Alt+Leertaste, `h: Welches Image ist gebootet?`, Enter, und einmal über
„Nur nachschlagen“. Eine Testfassung des Runners läuft mit, wenn das
Leisten-Symbol aus dem Home gestartet wird (`HERMES_OS_TRAY_DIR`, siehe
[systemagent.md](systemagent.md)); die Desktop-Datei gehört dafür nach
`~/.local/share/krunner/dbusplugins/`.

## Stolperfallen

- **QtDBus aus PySide6 reicht nicht.** Match muss `a(sssida{sv})` liefern, ein
  Feld von Strukturen. `QDBusArgument.beginArray` braucht dafür einen mit
  `qDBusRegisterMetaType` angemeldeten C++-Typ, den es aus Python nicht gibt
  („type … is not registered with D-Bus“); mit einem falschen Elementtyp bricht
  libdbus den Prozess per `abort()` ab. Eine Antwort mit `av` nimmt KRunner nicht
  an, weil `QDBusPendingReply` die Signatur vergleicht. Deshalb `dbus_peer.py`.
  Nebenbei: `QDBusArgument << 5` schreibt in PySide6 ein Byte, nicht `int32`.
- **KConfig-Maskierung:** In Desktop-Dateien wird `\s` beim Lesen zu einem
  Leerzeichen. Der Filter in `X-Plasma-Runner-Match-Regex` kommt deshalb ohne
  Backslash aus (`(?i)^ *(hermes[ :,]|h *:)`); der Test prüft das.
- **Listen in der Desktop-Datei** trennt KConfig an Kommas. Die
  `X-Plasma-Runner-Syntax-Descriptions` dürfen darum kein Komma enthalten.
- **`X-Plasma-API=DBus2` mit `*` im Dienstnamen vermeiden:** Bei `DBus2` fragt
  KRunner beim Laden Config vom ersten passenden Dienst ab; läuft zu dem
  Zeitpunkt keiner, greift KRunner auf eine leere Menge zu. Filter und
  Mindestlänge stehen deshalb in der Desktop-Datei, `Config` antwortet nur für
  den Fall, dass jemand umstellt.
- **Run-IDs:** KRunner gibt die Treffer-ID ohne das eigene Präfix zurück
  (`X-Plasma-Runner-Unique-Results` ist aus). Die Frage steckt vollständig in der
  ID, auch wenn der Text im Treffer gekürzt ist.
