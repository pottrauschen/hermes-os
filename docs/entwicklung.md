# Entwicklung: hermes-os vom Arbeitsplatz aus weiterbauen

Stand: 2026-09-27. Wie hermes-os entsteht, von der Änderung am Windows-PC bis
zum Test am Bildschirm der Test-VM. Diese Seite ist der Einstieg; was zu
einem Thema gehört, steht in dessen eigener Doku (Doc-Map in `CLAUDE.md`).
Stand, Entscheidungen und offene Punkte liegen nicht im Repo, sondern im
Second Brain (`/hole hermes-os`).

## Wer was tut

```
Windows-PC            entwickeln: Repo, Claude Code, Second Brain, GitHub-Zugang
  └ git push main
GitHub Actions        bauen: beide Images, Gate, Tests, Push nach GHCR (rund 30 min)
  └ ghcr.io/pottrauschen/hermes-os, hermes-os-nvidia
Test-VM 112           testen: bootc upgrade, Neustart, am Bildschirm (KVM) oder von hier
  auf Proxmox .40
```

Der Windows-PC kann keine VM fahren und keine Images bauen (kein Podman,
kein Linux). Gebaut wird nur in der CI; die Bau-VM 110 braucht es nur für
einen neuen Datenträger ([testumgebung.md](testumgebung.md)).

| Was | Wo |
|---|---|
| Arbeitskopie | `C:\Users\<user>\Desktop\hermes-os` (Git Bash oder PowerShell) |
| Repo | `github.com/pottrauschen/hermes-os`, Zweig `main` |
| Images | `ghcr.io/pottrauschen/hermes-os` (AMD/Intel), `…/hermes-os-nvidia` |
| Hermes-Upstream | `NousResearch/hermes-agent`, gepinnt über `HERMES_REF` im Dockerfile |
| Test-VM | VM 112, `<user>@192.168.1.142`, Anmeldung per SSH-Schlüssel |
| Proxmox-Host | `root@192.168.1.40` (`qm …`) |

## Aufbau des Repos

| Ordner, Datei | Inhalt |
|---|---|
| `Dockerfile`, `Dockerfile.nvidia` | bis auf die FROM-Zeile gleich; Node-Stufe fürs Dashboard, dann `build.sh` |
| `files/system/` | alles, was ins Image kommt, Pfad für Pfad wie im System |
| `files/scripts/` | Bauschritte `NN-*.sh` in Reihenfolge, `80-validate.sh` ist das Gate, `89-tests.sh` die Tests im Build |
| `tests/` | Prüfungen ohne Hardware, meist Python mit Attrappen; `tests/vm-hilfen.sh` für die VM |
| `docs/` | eine Seite je Thema, Doc-Map in `CLAUDE.md` |
| `.github/workflows/build.yml` | der Bau in der CI |

Die Teile von hermes-os und ihre Doku:

| Teil | Programm, Dateien | Doku |
|---|---|---|
| Einrichtungsassistent | `usr/libexec/hermes-os-setup`, `usr/share/hermes-os/setup/` | [einrichtung.md](einrichtung.md) |
| Leisten-Symbol und Kontor | `usr/libexec/hermes-os-tray`, `usr/share/hermes-os/tray/` | [systemagent.md](systemagent.md) |
| KRunner „Hermes fragen“ | im Leisten-Symbol (`tray/runner.py`, `dbus_peer.py`) | [krunner.md](krunner.md) |
| Sehen und Hören | `tray/screenshot.py`, `voice.py`, `voice_worker.py` | [sehen-hoeren.md](sehen-hoeren.md) |
| Dashboard-Fenster | `usr/libexec/hermes-os-dashboard`, `usr/share/hermes-os/dashboard/` | [dashboard.md](dashboard.md) |
| Plugin: Systemwissen, Grenze, Protokoll, Bibliothek, Bericht | `usr/share/hermes-os/plugins/hermes_os/` | [grenze.md](grenze.md), [protokoll.md](protokoll.md), [bibliothek.md](bibliothek.md), [morgenbericht.md](morgenbericht.md) |
| Anleitung für Hermes (Skill) | `usr/share/hermes-os/skills/hermes-os-system/SKILL.md` | im Skill selbst |
| Lokales Modell | `usr/libexec/hermes-os-lokal`, `usr/share/hermes-os/local/` | [lokales-modell.md](lokales-modell.md) |
| ujust-Rezepte | `usr/share/hermes-os/hermes-os.just` | [handbuch.md](handbuch.md) |

## Ablauf einer Änderung

1. **Ändern** am PC.
2. **Lokal prüfen**, was unter Windows geht (nächster Abschnitt). Python-Syntax
   aller geänderten Dateien, Shell-Skripte mit `sed 's/\r$//' datei | bash -n`.
3. **In der VM ausprobieren**, bevor ein Image gebaut wird: Oberflächen
   offscreen zeichnen, Programme als Testfassung aus dem Home starten
   (Abschnitte unten). Das spart die halbe Stunde CI für jeden Versuch.
4. **Commit und Push auf `main`.** Commit-Nachricht auf Deutsch: Anlass,
   was sich geändert hat, wie geprüft. Doku und Tests gehören in denselben
   Commit wie der Code.
5. **CI abwarten** (`gh run watch`). Sie baut beide Varianten, lässt Gate und
   Tests im Image laufen und pusht erst dann.
6. **VM aktualisieren:** `sudo bootc upgrade`, dann Neustart. Den Neustart
   vorher mit dem abstimmen, der an der VM sitzt.
7. **Am echten Bildschirm prüfen**, per KVM oder von hier
   ([testumgebung.md](testumgebung.md), „VM 112 von hier bedienen“).

## Was unter Windows läuft

Ohne Qt/Kirigami und ohne Linux-Dateirechte geht ein Teil der Tests auch am
PC; Python ist `python3-64.exe`, Ausgaben mit `PYTHONIOENCODING=utf-8` lesen.
`make` gibt es in Git Bash nicht, die Schritte aus `make lint` also einzeln.

| Läuft unter Windows | Nur unter Linux (VM oder Build) |
|---|---|
| `tray-client-check.py`, `model-choice-check.py`, `library-check.py`, `boundary-check.py`, `runner-check.py` | `library2-check.py`, `audit-check.py` (Dateirechte 0600/0700), `report-check.py` (startet das Symbol), `dashboard-check.py` (startet den Server), `lokales-modell-check.py` (GPU-Attrappe mit Linux-Pfaden), `sehen-hoeren-check.py`, alle `*-gui-check.py`, `tray-showcase.py`, `venv-smoke.sh`, `boot-check.sh` |

Was unter Windows scheitert, läuft im Gate des Builds unter Linux; dort zählt
es.

## Oberflächen ohne Bildschirm prüfen

Kontor, Assistent und Dashboard sind QML mit Kirigami. Die Render-Tests
zeichnen sie offscreen mit Attrappen statt des echten Backends, jede
QML-Warnung ist ein Fehler. Sie brauchen PySide6 und Kirigami, laufen also in
der VM, ohne die Sitzung dort zu stören:

```sh
ssh <user>@192.168.1.142 'mkdir -p ~/ui-test/qml'
sed 's/\r$//' files/system/usr/share/hermes-os/tray/Main.qml | ssh <user>@192.168.1.142 'cat > ~/ui-test/qml/Main.qml'
sed 's/\r$//' tests/tray-gui-check.py | ssh <user>@192.168.1.142 'cat > ~/ui-test/tray-gui-check.py'
ssh <user>@192.168.1.142 'cd ~/ui-test && python3 tray-gui-check.py --qml-dir ~/ui-test/qml --out ~/ui-test/bilder'
```

`--out` legt je Schritt ein PNG ab (`tray-streaming.png`, `tray-approval.png`
…). Für Design-Arbeit zeichnet `tests/tray-showcase.py` ein echt wirkendes
Gespräch breit und schmal, mit Breeze-Symbolen, damit Vorher und Nachher
vergleichbar sind; `--image` nimmt ein echtes Bildschirmfoto für die
Nutzerblase. Neben `Main.qml` gehören weitere geänderte Dateien des Fensters
(etwa `tray/model_choice.py`) mit in den Testordner.

Arbeitsweise, die sich bewährt hat: Vorher-Bild, Änderung, Nachher-Bild,
beide ansehen, erst dann committen.

## Programme als Testfassung aus dem Home

Die Programme lesen ihre Module über Umgebungsvariablen, damit eine
geänderte Fassung laufen kann, ohne `/usr` anzufassen:

| Variable | Wofür |
|---|---|
| `HERMES_OS_TRAY_DIR` | Ordner mit `Main.qml` und den Modulen des Leisten-Symbols |
| `HERMES_OS_LOCAL_DIR` | Ordner mit `local_model.py` |
| `HERMES_OS_LIBRARY_PY`, `HERMES_OS_AUDIT_PY` | Bibliothek und Protokoll des Plugins |
| `HERMES_HOME` | Hermes-Verzeichnis; für Versuche ein Wegwerfordner, nie `/tmp` über Neustarts hinweg |

Das Leisten-Symbol läuft nur einmal je Nutzer; eine zweite Instanz reicht an
die laufende weiter. Für eine Testfassung erst das laufende Symbol beenden,
dann die Fassung als Nutzerdienst starten, damit sie die SSH-Sitzung
überlebt:

```sh
systemd-run --user -p ExitType=cgroup -E HERMES_OS_TRAY_DIR=$HOME/ui-test/tray \
  python3 $HOME/ui-test/hermes-os-tray
```

`hermes-os-tray --check`, `hermes-os-setup --check`, `hermes-os-lokal --check`
prüfen eine Fassung ohne Fenster.

## Hermes auf ein neues Release heben

Ein Bump ist eine Änderung von `HERMES_REF` im `Dockerfile` (beide Dateien).
Vorher `tests/venv-smoke.sh`, `hermes-os-setup --check`,
`tests/setup-gui-check.py`, `tests/tray-client-check.py` und
`tests/dashboard-check.py`, dazu das Frontend lokal bauen
([dashboard.md](dashboard.md)). Die Brücke des Assistenten nutzt interne
Hermes-Helfer ohne Stabilitätszusage, das Leisten-Symbol die Runs-API des
Gateways; beides bricht bei einem Bump zuerst. Wie Hermes selbst etwas tut,
steht im Code unter `/usr/lib/hermes-agent` in der VM; nachsehen ist
verlässlicher als raten, und ein Mitschnitt mit einem kleinen Server auf
127.0.0.1 zeigt, was Hermes wirklich an einen Endpunkt schickt.

## Stolperfallen am Windows-Arbeitsplatz

- **Zeilenenden:** Der Arbeitsbaum ist CRLF, der Index LF. Vor dem Kopieren
  in die VM `sed 's/\r$//'`, Skripte so auch prüfen (`| bash -n`).
- **Heredocs mit Apostrophen** zerlegt die Shell-Schicht des Werkzeugs;
  solche Dateien und Commit-Nachrichten als Datei schreiben und mit
  `git commit -F` übergeben.
- **Git Bash schreibt Pfade um:** `gh api /user/…` wird zu
  `C:/Program Files/Git/user/…`. Den führenden Schrägstrich weglassen.
- **Python schreibt in Pipes die Codepage**, nicht UTF-8; Tests mit
  Umlauten brauchen `PYTHONIOENCODING=utf-8` oder `reconfigure`.
- **Claude Code in Claude Code:** Wer aus einer Claude-Code-Sitzung heraus
  `claude` startet, muss `CLAUDECODE` aus der Umgebung nehmen.
- **Sudo in der VM** fragt nach dem Passwort: `echo … | sudo -k -S -p ""`,
  `-k`, damit eine gemerkte Anmeldung nicht die Passwortzeile schluckt.

## Regeln

Was Claude vorher fragt, wie Geheimnisse behandelt werden und welche
Bedingungen von Anbietern gelten, steht in `CLAUDE.md` unter
„Arbeitsregeln“. Kein Session-Wissen als Datei im Repo; Übergaben und
Befunde mit Datum gehören ins Brain.
