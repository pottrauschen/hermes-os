# Morgenbericht

Hermes meldet sich einmal am Tag von selbst mit einer Desktop-Benachrichtigung,
etwa:

> **Morgenbericht**
> Neues Image verfügbar (44.20260926). 3 Fehler im Journal seit gestern 08:30,
> davon 1 neu: bluetooth.service. /home bei 92 %. Kein fehlgeschlagener Dienst.
> 2 Flatpak-Updates verfügbar.
> [Im Chat besprechen]

Der Knopf öffnet das Kontor des Leisten-Symbols mit dem ganzen Bericht als
Kontext. Ein Update stößt der Bericht nie selbst an; wer im Chat „spiel das
Update ein" schreibt, bekommt die normale Freigabe aus der Grenze (README).

## Ein- und ausschalten

```sh
ujust hermes-morgenbericht-ein          # fragt nach der Uhrzeit, Vorgabe 08:30
ujust hermes-morgenbericht-ein 07:45    # ohne Rückfrage, so richtet es auch der Agent ein
ujust hermes-morgenbericht-aus
/usr/libexec/hermes-os-morgenbericht --probe   # Bericht jetzt ansehen, ohne zu speichern
```

Der Agent kennt die Rezepte aus dem Skill `hermes-os-system` und richtet den
Bericht auf Zuruf ein; `ujust hermes-morgenbericht-*` ist frei, der
Freigabe-Hook greift nur bei `ujust update` und Verwandten. Ohne laufendes
Gateway kommt kein Bericht, das Rezept weist darauf hin.

## Was drinsteht

| Teil | Quelle | Im Bericht |
|---|---|---|
| Update-Stand | `tools.image_update_state()`, dieselbe Logik wie `os_updates`: `rpm-ostree status --json` und `skopeo inspect` (Digest und Label `org.opencontainers.image.version`) | verfügbar, bereit nach Neustart, aktuell oder unbekannt |
| Journal-Fehler | `journalctl --since @<letzter Bericht> -p err -o json`, gezählt nach Unit (Nutzer-Units statt `user@`), sonst `SYSLOG_IDENTIFIER` | Anzahl, und welche Quellen im letzten Bericht noch nicht vorkamen |
| Plattenplatz | `df -B1 --output=…` für `/`, `/var`, `/home`; auf bootc ist `/` ein composefs-Abbild, gemessen wird dann `/sysroot`; Pfade auf demselben Dateisystem werden zusammengefasst | ab 85 % „bei N %", ab 95 % „fast voll", sonst „ok (höchstens N %)" |
| Dienste | `systemctl list-units --failed`, System und `--user` | Namen der fehlgeschlagenen Units |
| Flatpak | `flatpak remote-ls --updates` (wie `os_updates`), abschaltbar mit `flatpak=false` | nur wenn welche anstehen |

Die Kurzfassung ist die Benachrichtigung. Die Einzelheiten (Quellen mit Anzahl
und einer Beispielzeile, Belegung je Dateisystem, Image-Zeilen) gehen als
Kontext in den Chat. Ohne ein Kommando (etwa ohne Zugriff aufs System-Journal
oder ohne Netz für skopeo) sagt der Satz „unbekannt" oder „nicht lesbar", der
Bericht kommt trotzdem. Sieht das Konto das System-Journal nicht (nicht in
wheel, adm oder systemd-journal), steht „(nur eigene Einträge lesbar)" dabei.

## Wie es gebaut ist

```
Gateway (hermes-gateway.service, Cron-Ticker alle 60 s)
  └─ Job hermes-os-morgenbericht, "30 8 * * *", --script, --no-agent, deliver local
       └─ ~/.hermes/scripts/hermes-os-morgenbericht.sh   (legt das Rezept an, springt nur weiter)
            └─ /usr/libexec/hermes-os-morgenbericht      (Fedoras Python)
                 ├─ report.build_report(record=True)     → $XDG_STATE_HOME/hermes-os/morgenbericht.json
                 └─ report.handle_desktop_notify(report=True)
                      └─ systemd-run --user --collect --unit hermes-os-notify-XXXX
                           └─ sh: notify-send -A chat=… -A default=… wartet auf die Wahl
                                └─ chat oder Klick: hermes-os-tray --discuss <kontextdatei>
                                     └─ lokaler Socket an die laufende Instanz, sonst neue Instanz
```

- **Skript-Job ohne Modell.** Hermes' Cron kennt neben Aufträgen an den Agenten
  Skript-Jobs (`hermes cron create … --script … --no-agent`): Hermes führt das
  Skript aus und legt dessen Ausgabe unter `~/.hermes/cron/output/<job>/` ab, ein
  Modell läuft nicht. Der Bericht kostet damit nichts, braucht keinen
  erreichbaren Anbieter und kann nichts ändern; der Agent kommt erst im Chat
  dazu. `deliver local` schickt nichts an Messaging-Plattformen.
- **Dieselben Werkzeuge wie im Chat.** `os_report` und `desktop_notify` liegen in
  `plugins/hermes_os/report.py` und sind für den Agenten registriert; der
  Einstieg lädt dieselbe Datei. Fragt man im Chat „wie steht's ums System?",
  kann der Agent `os_report` aufrufen, ohne den Vergleichspunkt zu verschieben
  (`record` ist nur im täglichen Lauf gesetzt).
- **Zustand** unter `$XDG_STATE_HOME/hermes-os/` (Vorgabe `~/.local/state`):
  `morgenbericht.json` mit `baseline` (Zeitpunkt und Quellen des letzten
  täglichen Berichts) und `latest` (letzter Bericht für `desktop_notify`),
  `notify/*.txt` mit den Kontextdateien der Benachrichtigungen, 14 Tage
  aufbewahrt. Der erste Bericht schaut 24 Stunden zurück und meldet noch nichts
  als neu.
- **Der Knopf nutzt den Weg des Leisten-Symbols.** Wie bei den Freigaben wartet
  `notify-send --action` und schreibt die Wahl auf stdout. Der Weg ins Fenster
  ist derselbe lokale Socket, über den Menü und Meta+H `--show` schicken; neu
  ist der Befehl `discuss <pfad>`. Das Symbol liest nur Dateien aus
  `$XDG_STATE_HOME/hermes-os/notify/` (`hermes_client.read_context_file`),
  zeigt den Bericht als Blase von Hermes und stellt ihn der nächsten Nachricht
  als Kontext voran, markiert als Fremdtext, weil Journal-Meldungen darin
  stehen, die jeder lokale Prozess schreiben kann (`hermes_client.with_context`).
  `desktop_notify` maskiert `& < >`, weil Plasma einfaches HTML deutet.
- **Verpasste Läufe:** Das Gateway hängt an der Plasma-Sitzung. Wer sich erst
  nach der Uhrzeit anmeldet, bekommt den Bericht einmal nachgeholt, sobald das
  Gateway startet (`cron.catch_up_missed`, in Hermes vorgegeben an); mehrere
  verpasste Tage werden zu einem Lauf.
- **Zeitzone:** Hermes rechnet Cron-Ausdrücke in `timezone` aus
  `~/.hermes/config.yaml`, sonst in der Zeitzone des Systems (`hermes_time.py`).
  Die Vorlage setzt keine, also gilt die des Systems; ab Werk ist das
  Europe/Berlin (`/etc/localtime`, `20-agent-layer.sh`). Vorher fehlte die Datei,
  dann gilt UTC, und der Bericht kam in VM 112 zwei Stunden zu spät.

## Testen

Ohne Hermes, überall mit Python 3.9 oder neuer:

```sh
python3 tests/report-check.py
```

Ersetzt die Kommandos durch Fixtures (rpm-ostree, skopeo, journalctl, df,
systemctl, flatpak) und prüft Kurzfassung, Schwellen, composefs-Wurzel,
Vergleich mit dem Vortag, fehlende Kommandos, den Zustand und
`desktop_notify` bis zum Aufruf von `hermes-os-tray --discuss`. `make lint` und
das Gate (`80-validate.sh`, 7h) führen ihn aus; das Gate prüft dazu
`hermes-os-morgenbericht --check` und dass `ujust --list` beide Rezepte zeigt.
`tests/venv-smoke.sh` lädt `os_report` und `desktop_notify` über den echten
Plugin-Loader.

In der Test-VM (siehe [testumgebung.md](testumgebung.md)):

```sh
ujust hermes-morgenbericht-ein 08:30
hermes cron list                                       # Job hermes-os-morgenbericht, no-agent
hermes cron run hermes-os-morgenbericht                # beim nächsten Tick, statt bis morgen zu warten
ls ~/.hermes/cron/output/*/                            # Ausgabe des Laufs
journalctl --user -u 'hermes-os-notify-*' -n 20        # die wartende Benachrichtigung
```

## Stolperfallen

- **Skripte nur aus `~/.hermes/scripts/`.** Hermes löst Symlinks auf und lehnt
  alles ab, was außerhalb landet; ein Link nach `/usr/libexec` geht nicht. Das
  Rezept legt deshalb eine kleine Datei an, die per `exec` ins Image springt.
  Liegt sie nicht mehr da, meldet der Job „Script not found"; `ujust
  hermes-morgenbericht-ein` legt sie neu an.
- **Leere Ausgabe heißt für Hermes „still".** Der Einstieg druckt deshalb immer
  die Kurzfassung und das Ergebnis der Zustellung, damit der Lauf im Verlauf
  (`~/.hermes/cron/output`) steht.
- **`df -P` und `--output` schließen sich aus.** GNU df bricht dann ab; der
  Test weist die Kombination ab.
- **composefs:** `df /` zeigt auf bootc das schreibgeschützte Abbild mit 100 %.
  Gemessen wird `/sysroot`, sonst stünde jeden Morgen „/ fast voll" da.
- **Die Benachrichtigung wartet in einer eigenen User-Unit**
  (`hermes-os-notify-*.service`), nicht im Gateway: Ein Neustart des Gateways
  räumt dessen cgroup ab und hätte den wartenden `notify-send` mitgenommen.
- **Wie lange der Knopf lebt, entscheidet Plasma.** notify-send wartet, bis die
  Benachrichtigung geschlossen wird. Ob ein Knopf in der Verlaufsliste nach
  dem Ausblenden des Popups noch wirkt, ist in der VM zu prüfen.

## Offen

- Prüfung in der Test-VM 112: Cron-Lauf aus dem Gateway in der Plasma-Sitzung,
  Benachrichtigung am Bildschirm, Knopf öffnet das Fenster mit dem Bericht,
  auch wenn das Symbol noch nicht lief; Zeitzone; `df` auf der echten
  bootc-Platte; ein nachgeholter Lauf direkt nach der Anmeldung, wenn
  Plasmas Benachrichtigungsdienst vielleicht noch nicht bereit ist.
- Bericht auch an Messaging-Plattformen (`deliver telegram` und Co.), wenn der
  Nutzer das will; heute bewusst nur am Desktop.
