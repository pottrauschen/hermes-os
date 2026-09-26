# hermes-os

> Arbeitsname. Der Name steht in `.github/workflows/build.yml` (`IMAGE_BASENAME`), als
> `ARG IMAGE_NAME` und `LABEL title` in `Dockerfile` und `Dockerfile.nvidia`, im
> `Makefile` (`IMAGE_NAME`) und in den Pfaden `/usr/share/hermes-os`.

Ein atomares Desktop-Linux, in dem ein KI-Agent Systembestandteil ist. Basis ist
[Aurora DX](https://getaurora.dev) (Universal Blue, Fedora bootc, KDE Plasma auf
Wayland). Der Agent ist [Hermes Agent](https://github.com/NousResearch/hermes-agent)
von Nous Research, auf ein Release festgenagelt und ins Image gebacken.

Das Repo folgt dem Muster von querencia-linux: ein `Dockerfile`, das nur `build.sh`
aufruft, nummerierte Skripte in `files/scripts/`, Systemdateien in `files/system/`,
ein Validierungs-Gate, Build-Tests, Signierung, ein eigener GitHub-Workflow nach dem
Universal-Blue-Muster.

## Was das System kann und was nicht

| | Stand |
|---|---|
| Schreibgeschützte Basis, Updates mit Rollback | Aurora, fertig |
| Hermes als Nutzerdienst (Messaging, Cron, Sprachnachrichten auf Plattformen) | Hermes, konfiguriert |
| Einrichtung beim ersten Login: Anbieter, Schlüssel, Modell | Kirigami-Assistent, siehe [docs/einrichtung.md](docs/einrichtung.md) |
| Sichtbarer Agent am Desktop: Symbol in der Systemleiste mit Zuständen, Chat-Fenster per Klick oder Meta+H mit Bildern (Datei, Strg+V, Ablegen), Freigaben als Benachrichtigung | Leisten-Symbol, gebaut, Fenster in der VM offscreen geprüft, siehe [docs/systemagent.md](docs/systemagent.md) |
| Sprache am Desktop: lokale Erkennung (faster-whisper) und Ausgabe (piper) | im Terminal: `hermes`, dann `/voice on` (Push-to-Talk) |
| Undo für Projektdateien (Checkpoints vor write/patch und destruktiven Shell-Befehlen) | Hermes, eingeschaltet |
| Gefährliche Befehle fragen, Rest läuft frei | Hermes Approval-Gate plus Plugin-Hook, siehe unten |
| Das System kennt sich selbst (Image, Dienste, Apps, Hardware, Netz, Journal, Updates) | Plugin `hermes_os`, Phase 2, lesend, ohne Root |
| Apps per Sprache starten | `app_launch`, fertig |
| Fenster steuern, tippen, klicken, Widgets lesen (AT-SPI) | Phase 3, Plan in [docs/phase3-desktop.md](docs/phase3-desktop.md) auf Basis von agent-cu |
| Portal-Vermittler und unabhängiges Audit-Log | Phase 4, noch nicht gebaut |

## Aufbau

```
Basis-Image (Aurora DX)         /usr, read-only, bootc, Rollback
  + Hermes v2026.9.24 (0.21.5)  /usr/lib/hermes-agent, eigene Python-3.13-Venv (uv), vorkompiliert
  + uv                          /usr/bin/uv, Installer für Nachinstallationen ins Home
  + Agent-Schicht               /usr/share/hermes-os: Plugin, Skill, Config-Vorlage, ujust-Rezepte
  + Einrichtung                 /usr/libexec/hermes-os-setup (Kirigami, PySide6 aus Aurora) + setup/hermes_bridge.py in der Venv
  + Leisten-Symbol              /usr/libexec/hermes-os-tray (Kirigami, PySide6) + tray/hermes_client.py, spricht mit dem API-Server des Gateways (127.0.0.1:8642)
  + Dienst                      hermes-gateway.service (User-Unit, an graphical-session gebunden)
  + First-Login                 legt ~/.hermes an, verlinkt Plugin und Skill, legt den API-Schlüssel an, öffnet den Assistenten
Nutzerdaten                     ~/.hermes: Config, Sessions, Memory, Checkpoints, lazy-packages
Apps                            Flatpak
Entwicklung                     Distrobox / Podman
```

Vier Schichten, vier Update-Zyklen. Hermes wird nur über ein neues Image aktualisiert.
Der Launcher fängt `hermes update` ab und verweist auf `ujust update`; darunter trägt der
Code den Install-Stempel `apt`, den Termux-Wert, weil Hermes damit verlässlich mit Exit 2
verweigert. Ein Hermes-Bump ist eine Änderung von `HERMES_REF` im `Dockerfile`.

Die Hermes-Tags `v2026.x.y` liegen auf der Release-Linie 0.21.x mit Python 3.11 bis 3.13.
Der main-Zweig ist bereits bei Python 3.14 und einem anderen Build-System. Wer main pinnt,
muss `HERMES_PYTHON` anheben und `10-hermes.sh` anpassen.

Optionale Backends, die Hermes erst bei Gebrauch nachlädt (Messaging-SDKs, Wake-Word,
Cloud-Suche), landen über `HERMES_LAZY_INSTALL_TARGET` unter `~/.hermes/lazy-packages`,
nie in der read-only Venv. Die Variable setzen der Launcher und
`/usr/lib/environment.d/60-hermes-os.conf`, letzteres auch für die Gateway-Unit, die
`hermes setup` selbst unter `~/.config/systemd/user` anlegt.

## Die Grenze

Frei: Home, Container, Flatpak, Apps starten, `systemctl --user`, lesende Befehle.
Fragen: bootc, rpm-ostree, `ujust update`, Systemdienste, `/etc`, `/usr`, Firewall,
Nutzer, Root-Shells, Partitionen. Neustart und Herunterfahren führt der Agent nie aus.

Drei Stellen setzen das durch:

- **System-Prompt-Section** in `plugins/hermes_os/__init__.py`, die der Agent in jeder
  Session liest.
- **`approvals.smart_policy`** in `config.yaml.default` für den Guardian. Der sieht nur
  Befehle, die Hermes' eigener Detektor als gefährlich erkennt (rm -r, Schreiben nach
  /etc, systemctl stop/mask).
- **`pre_tool_call`-Hook** im Plugin für alles, was der Detektor nicht kennt: bootc,
  rpm-ostree, `ujust update`, systemctl ohne `--user`, Nutzer- und Partitionsverwaltung,
  Root-Shells, Schreiben nach /etc, /usr, /boot. Der Hook schickt den Aufruf in Hermes'
  Freigabe-Dialog (CLI-Prompt, Gateway `/approve`; ohne Menschen fail-closed).

## Bauen

Lokal, mit Podman auf Linux:

```sh
make lint            # Syntax, überall
make image           # AMD/Intel
make image VARIANT=nvidia
make qcow2 && make run-qemu-qcow
```

In CI: Push auf `main` baut beide Varianten und pusht nach `ghcr.io/<owner>/hermes-os`
und `hermes-os-nvidia`, Tags `latest`, Datum und Commit. Die Image-Version ist
`<Aurora-Version>.<Datum>`. Wöchentlicher Rebuild montags. Vor dem Build wird die Signatur
des Aurora-Basis-Images gegen `aurora-cosign.pub` geprüft. Signierung des eigenen Images,
sobald das Secret `SIGNING_SECRET` (cosign private key) im Repo hinterlegt und der
zugehörige `cosign.pub` committet ist; `90-signing.sh` trägt ihn dann in die
Container-Policy des Images ein.

Der Workflow ist bewusst eigenständig und nicht AlmaLinux atomic-ci wie bei
querencia-linux: dessen Build-Action prüft nach dem Build `rpm -q almalinux-gpg-keys`,
was auf einer Fedora-Basis scheitert.

Die NVIDIA-Variante ist eine eigene Datei `Dockerfile.nvidia`, weil die FROM-Zeile
literal sein muss (Signaturprüfung und Versionsableitung lesen sie). `make lint` prüft,
dass sich beide Dateien nur in dieser Zeile unterscheiden.

Auf einem bestehenden bootc-System (Aurora, Bluefin, Silverblue, Kinoite) umschalten:

```sh
sudo bootc switch ghcr.io/pottrauschen/hermes-os:latest          # AMD / Intel
sudo bootc switch ghcr.io/pottrauschen/hermes-os-nvidia:latest   # NVIDIA
sudo reboot
```

Das Paket auf GitHub muss dafür öffentlich sein (Packages, hermes-os, Package settings,
Visibility). Ein per Actions erzeugtes Paket ist anfangs privat.

## Nach dem ersten Login

Das First-Login-Skript öffnet den Einrichtungsassistenten: Anbieter aus Hermes' Katalog,
Schlüssel eintragen und prüfen, Modell wählen. Er schreibt `.env` und `config.yaml` über
Hermes' eigene Helfer und schaltet das Gateway ein. Später erreichbar als „Hermes
einrichten" im Menü oder `ujust hermes-setup`; der volle Terminal-Wizard bleibt unter
`ujust hermes-setup-terminal`. Details in [docs/einrichtung.md](docs/einrichtung.md).

Ab dem Login sitzt Hermes als Symbol in der Systemleiste: grau, solange das Gateway
aus ist, blau wenn bereit, orange während er arbeitet, gelb wenn er eine Freigabe
braucht. Klick oder Meta+H öffnet das Chat-Fenster, in das man auch Bilder legen kann
(Dateidialog, Strg+V, Ablegen); eine Freigabe kommt zusätzlich als Benachrichtigung mit
Knöpfen. Details in [docs/systemagent.md](docs/systemagent.md). Danach:

```sh
hermes                        # chatten; Sprache: /voice on (Push-to-Talk)
ujust hermes-gateway-enable   # Messaging, Cron, Sprachnachrichten auf Plattformen als Dienst
ujust hermes-doctor
```

Rollback eines Updates: `sudo bootc rollback`, dann Reboot. Ein `ujust rollback` gibt es
nicht; `ujust rebase-helper` wechselt auf Upstream-Aurora und ist hier falsch.

## Testen ohne Podman

`tests/venv-smoke.sh` führt den riskantesten Build-Schritt, die Hermes-Venv, außerhalb
eines Containers aus, lädt das Plugin über den echten Plugin-Loader des Releases und
prüft den Freigabe-Hook mit Beispielbefehlen. Das prüft die Python-Seite, nicht die
Fedora-Paketschicht. Braucht uv ab 0.10.

## Status und offene Punkte

- **Beide Images bauen in CI** und liegen unter `ghcr.io/pottrauschen/hermes-os` und
  `ghcr.io/pottrauschen/hermes-os-nvidia`. Basis ist Aurora auf Fedora 44. Im Build
  laufen Validierungs-Gate und Tests durch: Hermes 0.21.5 startet aus der read-only
  Venv, das Plugin lädt über den echten Plugin-Loader, der Freigabe-Hook greift,
  Sprachpakete sind importierbar, `hermes update` verweigert, `ujust --list` zeigt die
  Rezepte. `bootc container lint` ist sauber. Der Hermes-Baum im Image ist rund 1 GB groß.
- **Erster Boot am 2026-09-26** in einer Proxmox-VM, Ablauf und Befunde in
  [docs/testumgebung.md](docs/testumgebung.md): Image, Hermes, Plugin, Skill, Rezepte
  und First-Login greifen. Offen bleibt der Boot auf echter Hardware per `bootc switch`.
- **Oberfläche:** Der Assistent für den ersten Login und das Leisten-Symbol sind gebaut;
  das Symbol lief bisher nur durch Gate und Tests, nicht in der VM. Als nächster Schritt
  soll Hermes' eigenes Web-Dashboard (`hermes dashboard`) ins Image: Frontend in CI mit
  Node bauen, im Image als Fenster über QtWebEngine öffnen, erreichbar aus dem
  Leisten-Symbol. Siehe [docs/einrichtung.md](docs/einrichtung.md).
- **Review:** 51 Feststellungen aus einem mehrstufigen Review (fünf Untersucher, je ein
  Skeptiker), 31 bestätigt und eingearbeitet, 20 verworfen. Nicht übernommen, weil
  kosmetisch: Auroras `image-info.json` nennt weiterhin `aurora-dx` (fastfetch, MOTD).
- Basis-Images geprüft (Registry-Manifest und cosign): `ghcr.io/ublue-os/aurora-dx:stable`
  und `ghcr.io/ublue-os/aurora-dx-nvidia-open:stable`.
- ujust: Auroras `/usr/bin/ujust` ruft just mit `/usr/share/ublue-os/just/00-entry.just`
  auf (aus dem Aurora-common-Image), und die importiert eine feste Liste plus optional
  `60-custom.just`. Unsere Rezepte landen deshalb genau dort.
- Die Hermes-TUI wird nicht gebaut (braucht Node im Build). CLI, Gateway und Sprache
  brauchen sie nicht.
- Phase 3 (Desktop-Steuerung) wird ein eigenes Plugin mit eigener Gefahrenstufe.

## Lizenz

MIT. Hermes Agent ist MIT (Nous Research). Aurora ist Apache 2.0 (Universal Blue).
