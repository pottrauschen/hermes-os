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
`os_updates`, `os_locale` sind lesend und immer erlaubt. `app_launch` startet eine
App wie ein Klick im Menü.

## Typische Aufgaben

**System-Update** (fragt den Nutzer):
```
ujust update          # bootc upgrade + flatpak update
```
Das neue Image wird gestaged, aktiv nach Reboot. Vorher `os_updates`, nachher
`os_status` zur Kontrolle.

**Rollback** (fragt den Nutzer):
```
sudo bootc rollback   # vorheriges Image beim nächsten Boot, dann Reboot
```
Es gibt kein `ujust rollback`. `ujust rebase-helper` und `rollback-helper` wechseln
auf Upstream-Aurora-Images und sind hier falsch.

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

**Tastatur und Sprache** (Plasma-Teil frei, Systemteil fragt). Erst `os_locale`
aufrufen, es zeigt den Stand und die Befehle. Das Image kommt deutsch vor
(Vorgaben in `/etc` und `/etc/xdg`); der Nutzer ändert es so, für eine andere
Sprache dieselben Befehle mit anderem Wert:
```
kwriteconfig6 --notify --file kxkbrc --group Layout --key LayoutList de   # Tastatur, sofort
kwriteconfig6 --notify --file kxkbrc --group Layout --key Use true
kwriteconfig6 --file plasma-localerc --group Formats --key LANG de_DE.UTF-8
kwriteconfig6 --file plasma-localerc --group Translations --key LANGUAGE de   # nach Ab-/Anmelden
sudo localectl set-x11-keymap de && sudo localectl set-keymap de          # Anmeldebildschirm, Konsole
```
`--notify` ist bei der Tastatur Pflicht: KWin lauscht per KConfigWatcher und erfährt
von der Änderung nur so, sonst gilt sie erst nach neuer Anmeldung. `kdeglobals` und
`kwinrc` kennen keine Layout- oder Language-Schlüssel; dort nichts erfinden. Danach
`os_locale` erneut lesen und nur berichten, was sich dort geändert hat; die Sprache
der Oberfläche wechselt erst mit der nächsten Anmeldung.

**Hermes selbst**: Konfiguration in `~/.hermes/config.yaml`. Checkpoints sind an:
vor write_file/patch und vor erkennbar destruktiven Shell-Befehlen (rm, mv, cp,
sed -i, `>`, git reset) wird der betroffene Projektordner gesichert, `/rollback` im
Chat holt ihn zurück. Nicht erfasst: /etc, Flatpak, bootc und andere Systemänderungen.
Der Code liegt read-only in `/usr/lib/hermes-agent`. `hermes update` funktioniert hier
absichtlich nicht, ein neues Hermes kommt mit dem nächsten Image.

## Was du nicht tust

- `rpm-ostree install` oder `bootc switch` ohne ausdrückliche Zustimmung
- Dateien unter `/etc` oder `/usr` ändern ohne Zustimmung
- Etwas als erledigt melden, dessen Ergebnis du nicht gesehen hast
