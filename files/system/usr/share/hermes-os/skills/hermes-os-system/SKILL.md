---
name: hermes-os-system
description: Wie hermes-os aufgebaut ist und wie man es bedient. Lesen, bevor du Systemaufgaben ausführst (Update, Rollback, Apps installieren, Dienste, Container).
---

# hermes-os: Aufbau und Bedienung

hermes-os ist ein atomares Desktop-Linux auf Basis von Aurora DX (Universal Blue,
Fedora bootc) mit KDE Plasma auf Wayland. Hermes läuft hier als Systembestandteil.

## Vier Schichten, vier Update-Zyklen

| Schicht | Wo | Wie aktualisiert |
|---|---|---|
| Basis-Image (Kernel, KDE, Systemdienste, Hermes) | `/usr`, schreibgeschützt | `ujust update` oder Auto-Update, Reboot, Rollback möglich |
| Nutzerdaten, Hermes-Zustand | `~`, `~/.hermes` | vom Nutzer / von dir |
| GUI-Apps | Flatpak (Nutzer- oder Systemebene) | `flatpak update` |
| Entwicklung | Distrobox / Podman | im Container |

## Werkzeuge, die du zuerst nutzt

`os_status`, `os_services`, `os_apps`, `os_hardware`, `os_network`, `os_journal`,
`os_updates` sind lesend und immer erlaubt. `app_launch` startet eine App wie ein
Klick im Menü.

## Typische Aufgaben

**System-Update** (fragt den Nutzer):
```
ujust update          # bootc upgrade + flatpak update
```
Das neue Image wird gestaged, aktiv nach Reboot. Vorher `os_updates`, nachher
`os_status` zur Kontrolle.

**Rollback** (fragt den Nutzer):
```
ujust rollback        # vorheriges Image beim nächsten Boot
```

**App installieren** (frei):
```
flatpak search <begriff>
flatpak install flathub <app-id>
```
Danach `os_apps` mit dem Namen, dann `app_launch`.

**Dienst prüfen** (frei) und **Dienst ändern** (fragt):
```
systemctl status <unit>                     # lesen
systemctl --user restart hermes-gateway     # eigener Dienst: frei
sudo systemctl restart <unit>               # Systemdienst: fragen
```

**Entwicklungsumgebung** (frei):
```
distrobox create -n dev -i registry.fedoraproject.org/fedora:latest
distrobox enter dev
```
Bauen, kompilieren, `dnf install`: nur im Container, nie auf dem Host.

**Hermes selbst**: Konfiguration in `~/.hermes/config.yaml`, Checkpoints sind an
(`/rollback` im Chat holt Dateiänderungen zurück). Der Code liegt read-only in
`/usr/lib/hermes-agent`. `hermes update` funktioniert hier absichtlich nicht,
ein neues Hermes kommt mit dem nächsten Image.

## Was du nicht tust

- `rpm-ostree install` oder `bootc switch` ohne ausdrückliche Zustimmung
- Dateien unter `/etc` oder `/usr` ändern ohne Zustimmung
- Etwas als erledigt melden, dessen Ergebnis du nicht gesehen hast
