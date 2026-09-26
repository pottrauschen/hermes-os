# Einrichtung: Assistent für den ersten Login und Dashboard danach

Stand: 2026-09-26. Wie ein Nutzer Hermes auf hermes-os an ein Sprachmodell
anschließt, ohne ein Terminal zu brauchen, und was dafür im Image liegt.

## Zwei Teile

1. **Assistent für den ersten Login.** Ein Kirigami-Fenster, das der
   First-Login öffnet: Anbieter wählen, Schlüssel eintragen und prüfen, Modell
   wählen, fertig. Gebaut, im Image ab dem nächsten CI-Lauf.
2. **Dashboard für alles danach.** Hermes bringt mit `hermes dashboard` eine
   Web-Oberfläche für Konfiguration, Schlüssel, Provider-Login, Sessions, Chat
   und Cron mit. Der Backend-Teil liegt schon in der Venv; das Frontend muss in
   CI mit Node 26 gebaut und nach `hermes_cli/web_dist` gelegt werden. Noch
   nicht gebaut, Plan unten.

## Teil 1: der Assistent

### Dateien

| Was | Wo |
|---|---|
| Startprogramm, Python mit PySide6 | `files/system/usr/libexec/hermes-os-setup` |
| Oberfläche, QML mit Kirigami | `files/system/usr/share/hermes-os/setup/Main.qml` |
| Brücke in die Hermes-Venv | `files/system/usr/share/hermes-os/setup/hermes_bridge.py` |
| Menüeintrag „Hermes einrichten" | `files/system/usr/share/applications/hermes-os-setup.desktop` |
| Render-Test ohne Display | `tests/setup-gui-check.py` |

PySide6, Kirigami und QtWebEngine sind Teil von Aurora DX; das Image braucht
kein zusätzliches Paket. Der Assistent läuft mit Fedoras Python, nicht mit der
Hermes-Venv, und ruft für alles Hermes-Spezifische die Brücke als Unterprozess
in der Venv auf. Die Brücke spricht JSON und bekommt den Schlüssel nur über
die Umgebungsvariable `HERMES_OS_SETUP_KEY`, nie als Argument.

### Was die Brücke tut

- `catalog`: Hermes' Provider-Katalog (`hermes_cli.provider_catalog`),
  gefiltert auf Anbieter mit API-Schlüssel plus Nous Portal. Lokale Server,
  Cloud-SDK-Auth und Sammelrouten ohne eigenen Schlüssel bleiben weg. Die
  Liste ist damit Hermes' Liste, nicht unsere.
- `models <slug>`: Basis-URL wie im Wizard, Modellliste über
  `probe_api_models`, Schlüsselprüfung. OpenRouter beantwortet `/models` auch
  ohne Schlüssel, deshalb dort `/key`; andere Anbieter verlangen bei `/models`
  Auth, dort zählt die Liste. Ergebnis: `ok`, `rejected` oder `unknown`.
- `save <slug> <modell>`: `save_env_value` für den Schlüssel in `.env`,
  `_persist_model` für Anbieter, Modell und Basis-URL in `config.yaml`, exakt
  die Helfer, die `hermes setup` benutzt. OpenRouter bekommt
  `api_mode: chat_completions`, alle anderen lassen `api_mode` weg.
- `check`: Trockenlauf für das Validierungs-Gate, ohne Netz und ohne Schreiben.

Diese Helfer sind interne Funktionen von Hermes ohne Stabilitätszusage. Der
Pin auf `HERMES_REF` schützt; bei einem Hermes-Bump gehört
`hermes-os-setup --check` und der Render-Test zum Pflichtprogramm.

### Ablauf im Fenster

1. **Willkommen**: was Hermes ist, Hermes-Version, Hinweis falls schon ein
   Anbieter eingerichtet ist, Ausweg „Lieber im Terminal einrichten".
2. **Anbieter**: Liste aus dem Katalog, OpenRouter zuerst.
3. **Schlüssel und Modell**: Passwortfeld, Link zur Schlüsselseite des
   Anbieters (kopieren oder öffnen), „Schlüssel prüfen und Modelle laden",
   Modellwahl mit Vorgabe aus Hermes' Katalog. Speichern nur mit geprüftem
   oder zumindest nicht abgelehntem Schlüssel.
4. **Fertig**: schreibt über die Brücke, ruft danach das First-Login-Skript
   erneut auf, das das Gateway einschaltet, und bietet den Chat im Terminal an.

### Abo statt Schlüssel

Vier Anbieter kennt Hermes mit Anmeldung statt Schlüssel: Nous Portal,
ChatGPT/Codex, xAI Grok (SuperGrok, Premium+) und MiniMax. Der Assistent
zeigt sie in der Liste als „Anmeldung statt Schlüssel" und startet auf der
Anmeldeseite Hermes' eigenen Flow im Terminal: `hermes portal` für Nous, das
danach Modell und Anbieter selbst setzt, `hermes model` für die anderen, wo
Anmeldung und Modellwahl in einem Rutsch laufen. Adresse und Code aus dem
Terminal lassen sich am Handy öffnen, weil im Image noch kein Browser liegt.
Nous ist der Hersteller von Hermes, das ist der vorgesehene Weg. Für
ChatGPT, xAI und MiniMax gelten deren Bedingungen; die wurden nicht geprüft.

**Claude Pro/Max geht nicht.** Hermes böte den Setup-Token aus Claude Code
an (`claude setup-token`, Ablage in `ANTHROPIC_TOKEN`). Anthropics Rechtsseite
zu Claude Code (code.claude.com/docs/en/legal-and-compliance, gelesen am
2026-09-26) schließt das aus: OAuth-Anmeldung ist „intended exclusively" für
„ordinary use of Claude Code and other native Anthropic applications";
Entwickler dürfen nicht „route requests through Free, Pro, or Max plan
credentials" und nicht „collect, store, or intermediate Claude.ai credentials
or session tokens". Die Consumer Terms erlauben automatisierten Zugriff nur
per API-Schlüssel. Anthropic kündigt Maßnahmen „without prior notice" an,
das Risiko wäre das Abo des Nutzers. Deshalb nimmt die Brücke bei Anthropic
nur API-Schlüssel und weist einen Token mit dem Präfix `sk-ant-oat` ab; die
Oberfläche sagt es auf der Anthropic-Seite. Entschieden am 2026-09-26.

Aus demselben Grund steht in `config.yaml.default` `auth.adopt_external_logins:
false`. Hermes würde sonst eine Claude-Code-Anmeldung unter
`~/.claude/.credentials.json` von selbst übernehmen, sobald jemand Claude Code
im eigenen Home installiert und sich dort anmeldet.

Erlaubt wäre Claude Code selbst auf hermes-os: Anthropic gestattet das
Vorinstallieren des unveränderten Binaries unter den Commercial Terms, jeder
Nutzer meldet sich mit eigenem Konto an, und es gibt ein signiertes
dnf-Repository. Das wäre ein zweiter Agent neben Hermes, keine Modellquelle
für Hermes. Nicht umgesetzt, keine Entscheidung dazu.

Die Seiten sind dauerhaft instanziierte Items, keine `Component`s. Kirigami
warnt beim Push einer `Component` mit „Created graphical object was not placed
in the graphics scene"; mit Items bleibt das aus, und Eingaben überleben das
Zurückblättern.

### First-Login und Rezepte

`hermes-os-first-login` öffnet beim allerersten Login den Assistenten, sofern
`hermes-os-setup --check` durchläuft; sonst wie bisher ein Terminal mit
`hermes setup`. `ujust hermes-setup` startet den Assistenten,
`ujust hermes-setup-terminal` den vollen Wizard mit TTS, Terminal-Backend,
Gateway und Tools. Sobald ein Anbieter eingerichtet ist, legt das Skript
außerdem den Schlüssel für den lokalen API-Server des Gateways in `.env` an,
über den das Leisten-Symbol mit Hermes spricht
([docs/systemagent.md](systemagent.md)).

### Testen

Ohne Display, ohne Netz, mit Stub statt Brücke:

```sh
tests/setup-gui-check.py --qml-dir files/system/usr/share/hermes-os/setup --out /tmp/shots
```

Rendert jede Seite offscreen, legt PNGs ab und wertet jede QML-Warnung als
Fehler. Das Validierungs-Gate (`80-validate.sh`, Abschnitt 7c) führt denselben
Test im Image-Build aus; das Skript kommt über den Build-Kontext (`/ctx/tests`),
nicht ins Image. Läuft überall, wo PySide6 und Kirigami liegen, etwa auf
einem Aurora-Desktop oder in der Test-VM.

In der Test-VM lässt sich der Assistent aus einem Verzeichnis statt aus
`/usr` starten und in die laufende Sitzung schieben:

```sh
systemd-run --user --unit hos-test --collect \
  -E HERMES_OS_SETUP_DIR=/tmp/hos/share/hermes-os/setup -E HERMES_HOME=/tmp/hos/home \
  /usr/bin/python3 /tmp/hos/libexec/hermes-os-setup
```

`HERMES_HOME` auf ein Wegwerfverzeichnis zeigen lassen, sonst schreibt der
Test in die echte Konfiguration.

### Stolperfallen

- Schlüssel nie in Argumente: `ps` zeigt sie. Deshalb Umgebungsvariable.
- OpenRouter liefert `/models` ohne Auth; wer den Schlüssel darüber prüft,
  prüft nichts. `/key` antwortet mit 401 bei falschem Schlüssel.
- `hermes auth add` legt Schlüssel in `auth.json` als Credential-Pool ab, nicht
  in `.env`, und setzt weder Anbieter noch Modell in `config.yaml`. Das ist
  nicht der Weg des Wizards; deshalb die Brücke.
- Ohne installierte `.desktop`-Datei meldet Qt „Could not register app ID".
  Nur im Test aus `/tmp`, nicht im Image.
- Der Assistent braucht eine grafische Sitzung. Per SSH gestartet fehlt
  `WAYLAND_DISPLAY`; `systemd-run --user` nimmt die Umgebung der Sitzung.

## Teil 2: Dashboard, Plan

- **Bau in CI**: zweite Dockerfile-Stufe aus dem offiziellen Node-26-Image,
  klont Hermes am selben `HERMES_REF`, `npm ci --workspace web`,
  `npm run build -w web`. Ergebnis nach `/usr/lib/hermes-agent/hermes_cli/web_dist`
  über ein neues Skript `15-hermes-dashboard.sh`. Der CI-Grep auf die
  Aurora-FROM-Zeile nimmt `tail -1`, `make lint` blendet nur die Aurora-Zeile
  aus; eine identische Node-Zeile in beiden Dockerfiles stört beides nicht.
- **Start am Desktop**: ein Startskript `/usr/libexec/hermes-os-dashboard`,
  das `hermes dashboard --status` prüft, sonst `hermes dashboard --skip-build
  --no-open` startet, auf Port 9119 wartet und ein QtWebEngine-Fenster auf
  `127.0.0.1:9119` öffnet. Auf localhost braucht das Dashboard keine Anmeldung.
  Der Menüeintrag „Hermes" gehört schon dem Leisten-Symbol; das Dashboard
  bekommt „Hermes-Dashboard".
- **Gate**: `web_dist/index.html` vorhanden, `hermes dashboard --status` läuft.
- **Zusammenspiel**: Der Assistent bekommt auf der Fertig-Seite den Knopf
  „Dashboard öffnen"; das Leisten-Symbol zeigt den Menüpunkt „Dashboard
  öffnen", sobald `/usr/libexec/hermes-os-dashboard` ausführbar ist
  (`hermes-os-tray` prüft den Pfad beim Start). Ab dem zweiten Login startet
  das First-Login-Skript nur das Gateway.
