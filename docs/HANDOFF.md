# Übergabe hermes-os

Stand: 2026-09-25, Commit auf `main` nach dem Review-Durchlauf. Diese Datei ist für
die nächste Session oder Person gedacht, die ohne den Chatverlauf weitermacht.

## Ziel

Ein atomares KDE-Linux (Aurora DX, Fedora bootc, Wayland), in dem Hermes Agent
Systembestandteil ist: Das System kennt sich selbst, gefährliche Änderungen fragen,
alles andere läuft frei, Bedienung per Text und Sprache. Vorbild für den Aufbau war
das eigene, ältere Projekt querencia-linux (AlmaLinux, MATE, X11; obsolet).

## Was fertig ist

- Image-Build in CI, beide Varianten grün, Validierungs-Gate und Tests laufen im
  Build: `ghcr.io/pottrauschen/hermes-os` und `hermes-os-nvidia`, Tags `latest`,
  Datum, Commit. Version `<Aurora-Version>.<Datum>`.
- Hermes 0.21.5 (Tag v2026.9.24) unter `/usr/lib/hermes-agent`, uv-verwaltete
  Python-3.13-Venv, vorkompiliert, read-only. `/usr/bin/uv` bleibt als Installer;
  Nachinstallationen gehen nach `~/.hermes/lazy-packages`.
- Plugin `hermes_os`: acht Werkzeuge (Image, Dienste, Apps, Hardware, Netz, Journal,
  Updates, App starten), alle ohne Root, plus System-Prompt-Section und ein
  `pre_tool_call`-Hook, der System-Befehle in Hermes' Freigabe-Dialog schickt.
- Config-Vorlage (Checkpoints, Freigabe, lokale Sprache), Skill mit OS-Doku,
  Gateway-Unit nach Hermes' eigener Vorlage, First-Login-Skript, ujust-Rezepte über
  `60-custom.just`.
- Ein Review mit 51 Feststellungen (5 Untersucher, je ein Skeptiker): 31 bestätigt
  und eingearbeitet, 20 verworfen. Einzig offen: `image-info.json` nennt weiter
  `aurora-dx` (kosmetisch, fastfetch und MOTD).

## Was nicht verifiziert ist

Das Image hat nie gebootet. Alles ist im Container-Build geprüft, nichts am laufenden
Desktop. Beim ersten Boot prüfen:

1. First-Login: öffnet sich ein Terminal mit `hermes setup`? Liegt `~/.hermes/config.yaml`
   mit der Vorlage vor? Sind Plugin und Skill unter `~/.hermes` verlinkt?
   Log: `~/.hermes/hermes-os-first-login.log`.
2. `hermes` im Terminal: startet, Plugin geladen (`hermes plugins list`), `os_status`
   liefert Deployments, `app_launch org.kde.konsole` öffnet ein Fenster.
3. Freigabe: `sudo bootc upgrade --check` im Chat muss den Freigabe-Dialog auslösen,
   `flatpak install` darf es nicht.
4. Gateway: nach `hermes setup` prüfen, ob Hermes eine eigene Unit unter
   `~/.config/systemd/user` angelegt hat (erwartet) und ob `systemctl --user status
   hermes-gateway` läuft. `HERMES_LAZY_INSTALL_TARGET` muss in der Unit-Umgebung
   sichtbar sein (`systemctl --user show-environment`).
5. Sprache: `hermes`, dann `/voice on`. Mikrofon unter Wayland/PipeWire, faster-whisper
   und piper lokal.
6. `ujust --list` zeigt die `hermes-*`-Rezepte.
7. AT-SPI für Phase 3: `busctl --user tree org.a11y.atspi.Registry` liefert einen Baum,
   sonst Accessibility in den KDE-Einstellungen einschalten.

## Nächste Schritte

1. Erster Boot (VM: `make qcow2 && make run-qemu-qcow`; Rechner: `sudo bootc switch
   ghcr.io/pottrauschen/hermes-os:latest`). Paket auf GitHub vorher auf öffentlich.
2. Befunde aus dem Boot in Issues oder direkt fixen; Validierungs-Gate um alles
   ergänzen, was sich im Build prüfen lässt.
3. Phase 3 nach `docs/phase3-desktop.md`: agent-cu ins Image (eigener CI-Job mit Cargo),
   Skill aus dessen SKILL.md, Wayland-Eingabe über AT-SPI Action/EditableText und libei
   beisteuern.
4. Hermes-Bump: `HERMES_REF` im Dockerfile, vorher `tests/venv-smoke.sh` mit dem neuen
   Tag laufen lassen. Tags bleiben auf der 0.21-Linie; main braucht Python 3.14 und
   ein anderes Build-Skript.

## Wo was liegt

| Was | Wo |
|---|---|
| Build-Skripte, Reihenfolge 10 bis 91 | `files/scripts/` |
| Alles, was ins Image kopiert wird | `files/system/` |
| Plugin, Skill, Config-Vorlage, Rezepte | `files/system/usr/share/hermes-os/` |
| Gateway-Unit, environment.d, tmpfiles | `files/system/usr/lib/` |
| First-Login | `files/system/usr/libexec/hermes-os-first-login` |
| CI | `.github/workflows/build.yml` |
| Smoke-Test ohne Container | `tests/venv-smoke.sh` |
| Phase-3-Plan | `docs/phase3-desktop.md` |

## Entscheidungen, die man kennen sollte

- Eigener Workflow statt AlmaLinux atomic-ci: dessen Build-Action prüft
  `rpm -q almalinux-gpg-keys`, auf Fedora ein sicherer Fehlschlag.
- Zwei Dockerfiles mit literaler FROM-Zeile, weil Signaturprüfung und
  Versionsableitung sie lesen; `make lint` hält sie synchron.
- Hermes nativ im Image, nicht als Container: Der Agent muss bootc, flatpak, systemd
  und den Desktop des Hosts sehen.
- Install-Stempel `apt` (Termux-Wert), weil Hermes damit `hermes update` mit Exit 2
  verweigert; der Launcher fängt `update` vorher ab und verweist auf `ujust update`.
- Der Guardian von Hermes sieht nur Befehle, die der eingebaute Detektor kennt. Die
  Grenze für bootc, rpm-ostree, systemctl, Nutzer und Disks setzt deshalb der
  Plugin-Hook durch, nicht die `smart_policy`.
- `ujust rollback` gibt es auf Aurora nicht; überall `sudo bootc rollback`.

## Verwandte Repos

- `pottrauschen/hermes-agent`, `pottrauschen/oh-my-hermes`: reine Spiegel der Upstreams,
  keine eigenen Commits. oh-my-hermes wurde bewertet und bewusst nicht eingesetzt
  (425.000 Zeilen Hülle um einen 90.000-Zeilen-Kern, enge Versionskopplung).
- `pottrauschen/querencia-linux`: das ältere bootc-Projekt, Vorlage für Aufbau und CI.
- `kortix-ai/agent-computer-use`: Grundlage für Phase 3, MIT, AT-SPI-Lesen
  Wayland-tauglich, Eingabe noch X11.
