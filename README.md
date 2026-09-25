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
| Fenster steuern, tippen, klicken, Widgets lesen (KWin, Virtual Input, AT-SPI) | Phase 3, noch nicht gebaut |
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
und `hermes-os-nvidia`. Wöchentlicher Rebuild montags. Signierung, sobald das Secret
`SIGNING_SECRET` (cosign private key) im Repo hinterlegt ist.

Auf einem bestehenden bootc-System umschalten:

```sh
sudo bootc switch ghcr.io/<owner>/hermes-os:latest
sudo reboot
```

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

- Der Image-Build ist noch nicht gelaufen. Erster Lauf in CI oder lokal mit Podman.
- Getestet ohne Container: Hermes 0.21.5 auf Python 3.13 mit uv 0.11.33 baut, startet,
  und das Plugin registriert sich gegen die Plugin-API des Releases (siehe Test-Skript).
- `ghcr.io/ublue-os/aurora-dx:stable` ist geprüft. Der NVIDIA-Name
  `aurora-dx-nvidia-open` ist aus der Universal-Blue-Namenskonvention abgeleitet, nicht
  geprüft.
- Die Hermes-TUI wird nicht gebaut (braucht Node im Build). CLI, Gateway und Sprache
  brauchen sie nicht.
- Ob Aurora `ujust`-Dateien aus `/usr/share/ublue-os/just/` automatisch einbindet, ist
  Konvention, nicht hier verifiziert.
- Phase 3 (Desktop-Steuerung) wird ein eigenes Plugin mit eigener Gefahrenstufe.

## Lizenz

MIT. Hermes Agent ist MIT (Nous Research). Aurora ist Apache 2.0 (Universal Blue).
