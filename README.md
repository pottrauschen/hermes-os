# hermes-os

> Arbeitsname. Der Name steht an genau drei Stellen: `.github/actions/config/action.yml`
> (`IMAGE_NAME`), `Dockerfile` (ARG und LABELs) und in den Pfaden `/usr/share/hermes-os`.

Ein atomares Desktop-Linux, in dem ein KI-Agent Systembestandteil ist. Basis ist
[Aurora DX](https://getaurora.dev) (Universal Blue, Fedora bootc, KDE Plasma auf
Wayland). Der Agent ist [Hermes Agent](https://github.com/NousResearch/hermes-agent)
von Nous Research, auf ein Release festgenagelt und ins Image gebacken.

Das Repo folgt dem Muster von querencia-linux: ein `Dockerfile`, das nur `build.sh`
aufruft, nummerierte Skripte in `files/scripts/`, Systemdateien in `files/system/`,
ein Validierungs-Gate, Build-Tests, Signierung, CI über AlmaLinux atomic-ci.

## Was das System kann und was nicht

| | Stand |
|---|---|
| Schreibgeschützte Basis, Updates mit Rollback | Aurora, fertig |
| Hermes als Systemdienst, Sprache (STT lokal, TTS lokal) | Hermes, konfiguriert |
| Undo pro Tool-Aufruf (Checkpoints) | Hermes, eingeschaltet |
| Gefährliche Befehle fragen, Rest läuft frei | Hermes Approval-Gate plus `smart_policy` |
| Das System kennt sich selbst (Image, Dienste, Apps, Hardware, Netz, Journal, Updates) | Plugin `hermes_os`, Phase 2, lesend |
| Apps per Sprache starten | `app_launch`, fertig |
| Fenster steuern, tippen, klicken, Widgets lesen (AT-SPI) | Phase 3, Plan in [docs/phase3-desktop.md](docs/phase3-desktop.md) auf Basis von agent-cu |
| Portal-Vermittler und unabhängiges Audit-Log | Phase 4, noch nicht gebaut |

## Aufbau

```
Basis-Image (Aurora DX)         /usr, read-only, bootc, Rollback
  + Hermes v2026.9.24 (0.21.5)  /usr/lib/hermes-agent, eigene Python-3.13-Venv (uv)
  + Agent-Schicht               /usr/share/hermes-os: Plugin, Skill, Config-Vorlage
  + Dienst                      hermes-gateway.service (User-Unit, aus bis nach Setup)
  + First-Login                 legt ~/.hermes an, verlinkt Plugin und Skill
Nutzerdaten                     ~/.hermes: Config, Sessions, Memory, Checkpoints
Apps                            Flatpak
Entwicklung                     Distrobox / Podman
```

Vier Schichten, vier Update-Zyklen. Hermes wird nur über ein neues Image aktualisiert.
Der Code trägt den Install-Stempel `apt`, damit `hermes update` verweigert und auf den
Paketmanager verweist, hier also das Image. Ein Hermes-Bump ist eine Änderung von
`HERMES_REF` im `Dockerfile`.

Die Hermes-Tags `v2026.x.y` liegen auf der Release-Linie 0.21.x mit Python 3.11 bis 3.13.
Der main-Zweig ist bereits bei Python 3.14 und einem anderen Build-System. Wer main pinnt,
muss `HERMES_PYTHON` anheben und `10-hermes.sh` anpassen.

## Die Grenze

Steht in zwei Dateien, die zusammenpassen müssen:

- `files/system/usr/share/hermes-os/plugins/hermes_os/__init__.py`: die System-Prompt-Section,
  die der Agent in jeder Session liest.
- `files/system/usr/share/hermes-os/config.yaml.default`: `approvals.smart_policy`, die Regel
  für den Guardian, der jeden Terminal-Befehl vor der Ausführung bewertet.

Frei: Home, Container, Flatpak, Apps starten, `systemctl --user`, lesende Befehle.
Fragen: bootc, rpm-ostree, Systemdienste, `/etc`, Firewall, Nutzer, Löschen außerhalb
des Projekts.

## Bauen

Lokal, mit Podman auf Linux:

```sh
make lint            # Syntax, überall
make image           # AMD/Intel
make image VARIANT=nvidia
make qcow2 && make run-qemu-qcow
```

In CI: Push auf `main` baut beide Varianten und pusht nach `ghcr.io/<owner>/hermes-os`
und `hermes-os-nvidia`, Tags `latest`, Datum und Commit. Wöchentlicher Rebuild montags.
Vor dem Build wird die Signatur des Aurora-Basis-Images gegen `aurora-cosign.pub` geprüft.
Signierung des eigenen Images, sobald das Secret `SIGNING_SECRET` (cosign private key)
im Repo hinterlegt und der zugehörige `cosign.pub` committet ist; `90-signing.sh` trägt
ihn dann in die Container-Policy des Images ein.

Der Workflow ist bewusst eigenständig und nicht AlmaLinux atomic-ci wie bei
querencia-linux: dessen Build-Action prüft nach dem Build `rpm -q almalinux-gpg-keys`,
was auf einer Fedora-Basis scheitert.

Die NVIDIA-Variante ist eine eigene Datei `Dockerfile.nvidia`, weil die FROM-Zeile
literal sein muss (Signaturprüfung und Parser lesen sie). `make lint` prüft, dass sich
beide Dateien nur in dieser Zeile unterscheiden.

Auf einem bestehenden bootc-System (Aurora, Bluefin, Silverblue, Kinoite) umschalten:

```sh
sudo bootc switch ghcr.io/pottrauschen/hermes-os:latest          # AMD / Intel
sudo bootc switch ghcr.io/pottrauschen/hermes-os-nvidia:latest   # NVIDIA
sudo reboot
```

Das Paket auf GitHub muss dafür öffentlich sein (Packages, hermes-os, Package settings,
Visibility). Ein per Actions erzeugtes Paket ist anfangs privat.

## Nach dem ersten Login

Das First-Login-Skript öffnet ein Terminal mit `hermes setup`. Dort Provider und Modell
wählen. Danach:

```sh
ujust hermes-gateway-enable   # Sprache und Messaging als Dienst
ujust hermes-doctor
hermes                        # chatten
```

## Testen ohne Podman

`tests/venv-smoke.sh` führt den riskantesten Build-Schritt, die Hermes-Venv, außerhalb
eines Containers aus und lädt das Plugin gegen die echte Plugin-API des Releases. Das
prüft die Python-Seite, nicht die Fedora-Paketschicht. Braucht uv ab 0.10.

## Status und offene Punkte

- **Beide Images bauen in CI** und liegen unter `ghcr.io/pottrauschen/hermes-os` und
  `ghcr.io/pottrauschen/hermes-os-nvidia` (Tags `latest`, Datum, Commit). Basis ist
  Aurora auf Fedora 44. Im Build laufen Validierungs-Gate und Tests durch: Hermes 0.21.5
  startet aus der read-only Venv, das Plugin lädt über den echten Plugin-Loader,
  Sprachpakete sind importierbar, `hermes update` verweigert. `bootc container lint`
  ist sauber. Der Hermes-Baum im Image ist rund 1 GB groß.
- **Noch nie gebootet.** Der nächste Schritt ist ein Boot in einer VM (`make qcow2`,
  `make run-qemu-qcow`) oder ein `bootc switch` auf einem Testrechner. Erst dort zeigt
  sich, ob First-Login, Gateway-Unit und ujust-Einbindung wie gedacht greifen.
- Getestet ohne Container: Hermes 0.21.5 auf Python 3.13 mit uv 0.11.33 baut, startet,
  und das Plugin registriert sich gegen die Plugin-API des Releases (siehe Test-Skript).
- Basis-Images geprüft (Registry-Manifest): `ghcr.io/ublue-os/aurora-dx:stable` und
  `ghcr.io/ublue-os/aurora-dx-nvidia-open:stable`. Ein `aurora-dx-nvidia:stable` gibt
  es nicht.
- Lokale Sprache: faster-whisper (Extra `voice`) und piper-tts sind fest in die Venv
  gebaut, weil Hermes sie sonst zur Laufzeit in die read-only Venv nachinstallieren
  würde. Alles andere Optionale landet über `HERMES_LAZY_INSTALL_TARGET` unter
  `~/.hermes/lazy-packages`.
- Die Hermes-TUI wird nicht gebaut (braucht Node im Build). CLI, Gateway und Sprache
  brauchen sie nicht.
- ujust: Auroras Haupt-justfile importiert eine feste Liste plus optional
  `60-custom.just` (Paketquelle `ublue-os-just`). Unsere Rezepte landen deshalb genau
  dort; das Validierungs-Gate prüft, dass `ujust --list` sie zeigt.
- Phase 3 (Desktop-Steuerung) wird ein eigenes Plugin mit eigener Gefahrenstufe.

## Lizenz

MIT. Hermes Agent ist MIT (Nous Research). Aurora ist Apache 2.0 (Universal Blue).
