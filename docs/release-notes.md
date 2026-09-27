# Release-Notes

Je Version ein Abschnitt, die neueste oben. Der Text eines Abschnitts ist der Text der
Release auf GitHub.

## hermes-os 0.1

Erste Veröffentlichung, Stand: 2026-09-27. Entwurf: Tag `v0.1` und Release auf GitHub
stehen noch aus.

**In English.** hermes-os is an atomic desktop Linux with an AI agent built into the
system: KDE Plasma on Wayland, based on Aurora DX (Universal Blue, Fedora bootc), with
Hermes Agent by Nous Research pinned and baked into the read-only image. The agent sits
in the system tray, answers in its own chat window, knows the machine it runs on, and
asks before it touches the system; reboot and shutdown it leaves to you. Switch any
bootc system (Aurora, Bluefin, Silverblue, Kinoite) with
`sudo bootc switch ghcr.io/pottrauschen/hermes-os:latest`, or
`ghcr.io/pottrauschen/hermes-os-nvidia:latest` for NVIDIA, and reboot. This is a first
release: it has run in a virtual machine but not yet on real hardware, the image is not
signed yet, and it ships German defaults (locale, keyboard, Plasma language, time zone;
changeable in System Settings) while the agent's windows are German only. Built on
Hermes Agent by Nous Research; hermes-os is MIT-licensed.

### Was hermes-os ist

Ein atomares Desktop-Linux, in dem ein KI-Agent Systembestandteil ist.

- **Basis:** Aurora DX (Universal Blue, Fedora bootc, KDE Plasma auf Wayland), Fedora 44.
  Das System unter `/usr` ist schreibgeschützt; Updates kommen als ganzes Image und
  lassen sich zurückrollen.
- **Agent:** Hermes Agent von Nous Research, fest auf das Release v2026.9.24 (0.21.5),
  ins Image gebacken und schreibgeschützt unter `/usr`. Hermes wird nur mit einem neuen
  Image aktualisiert; `hermes update` verweigert und verweist auf `ujust update`.
- **Deutsch ab Werk:** Systemsprache, Tastatur, Plasma-Sprache und Zeitzone
  Europe/Berlin, änderbar in den Systemeinstellungen.
- **Images**, öffentlich auf ghcr.io, neu gebaut bei jedem Push und wöchentlich:
  `ghcr.io/pottrauschen/hermes-os` (AMD und Intel) und
  `ghcr.io/pottrauschen/hermes-os-nvidia` (NVIDIA).
- **Quelltext:** [github.com/pottrauschen/hermes-os](https://github.com/pottrauschen/hermes-os).

### Was drin ist

- **Leisten-Symbol und Kontor:** Das Symbol zeigt, was Hermes tut (grau aus, blau
  bereit, orange arbeitet, gelb fragt). Klick oder Meta+H öffnet das Kontor, das
  Chat-Fenster, mit Bildern (Datei, Strg+V, Ablegen) und der Wahl von Modell und
  Denkaufwand.
- **Hermes kennt das System:** Image, Dienste, Apps, Hardware, Netz, Journal, Updates,
  Sprache und Tastatur, lesend und ohne Root.
- **Die Grenze:** Alles im Home ist frei. Was das System berührt (Updates,
  Systemdienste, `/etc`, `/usr`, sudo außer für reine Lesebefehle), fragt vorher, als
  Kasten im Kontor und als KDE-Benachrichtigung mit Knöpfen. Neustart und
  Herunterfahren führt Hermes nie selbst aus, er bittet darum. Das Protokoll im Kontor
  zeigt, was er am System getan hat.
- **„Was sehe ich hier?“:** Meta+Umschalt+H wählt einen Bildschirmausschnitt, Hermes
  erklärt ihn.
- **Hermes fragen in KRunner:** Alt+Leertaste, dann `hermes <Frage>` oder `h: <Frage>`.
- **Bibliothek:** Adressen, Dateien und Ordner, in denen Hermes nachschlägt und die er
  als Quelle nennt.
- **Außerdem:** Einrichtungsassistent beim ersten Login, Hermes' Web-Dashboard als
  Fenster, Morgenbericht als Benachrichtigung, Sprechen per Push-to-Talk
  (Meta+Leertaste) mit Erkennung und Sprachausgabe auf dem eigenen Rechner, optional ein
  lokales Modell auf der eigenen GPU (Ollama, auf Wunsch ins Home geladen, nicht im
  Image).

### Installation

Von einem bestehenden bootc-System (Aurora, Bluefin, Silverblue, Kinoite):

```sh
sudo bootc switch ghcr.io/pottrauschen/hermes-os:latest          # AMD / Intel
sudo bootc switch ghcr.io/pottrauschen/hermes-os-nvidia:latest   # NVIDIA
sudo reboot
```

Nach dem Neustart und der ersten Anmeldung öffnet sich der Einrichtungsassistent:
Anbieter (zum Beispiel OpenRouter), Schlüssel und Modell, oder ein lokales Modell.
Einzelheiten stehen in der
[Einrichtung](https://github.com/pottrauschen/hermes-os/blob/main/docs/einrichtung.md),
die Bedienung im
[Handbuch](https://github.com/pottrauschen/hermes-os/blob/main/docs/handbuch.md).

Zurück zum vorherigen System: `sudo bootc rollback`, dann neu starten.

### Was noch fehlt

- **Keine echte Hardware:** hermes-os lief bisher nur in einer virtuellen Maschine
  (Proxmox), noch nicht auf echter Hardware.
- **Nicht signiert:** Das eigene Image ist noch nicht signiert. Die Signatur des
  Aurora-Basis-Images wird vor jedem Bau geprüft.
- **Nur Deutsch:** Die Fenster des Agenten gibt es nur auf Deutsch.
- **Nicht alles im Alltag erprobt:** Sprechen und Vorlesen sind in einer echten Sitzung
  ungeprüft, die Test-VM hat kein Mikrofon. Morgenbericht, Dashboard-Fenster, Freigaben
  und Protokoll liefen in der Test-VM in Einzelprüfungen, noch nicht im Alltag.
- **Phase 3 ist ein Plan:** Dass Hermes selbst klickt und tippt (AT-SPI, auf Basis von
  agent-cu), steht erst im
  [Plan](https://github.com/pottrauschen/hermes-os/blob/main/docs/phase3-desktop.md).
- **Die Grenze erkennt Befehle, keine Wirkungen:** Was ein Skript oder `python3 -c` im
  Inneren tut, sieht sie nicht. Die eigentliche Barriere gegen Systemänderungen ist, dass
  der Nutzer ohne Passwort kein Root hat; die Grenze sorgt dafür, dass Hermes fragt,
  bevor er es versucht. Einzelheiten unter
  [Die Grenze](https://github.com/pottrauschen/hermes-os/blob/main/docs/grenze.md).

### Dank und Lizenz

hermes-os ist gebaut auf [Hermes Agent](https://github.com/NousResearch/hermes-agent)
von Nous Research (MIT) und [Aurora](https://getaurora.dev) von Universal Blue
(Apache 2.0). Hermes Agent ist das Projekt von Nous Research; hermes-os bringt es als
Systembestandteil auf den Desktop. Built on Hermes Agent by Nous Research.

hermes-os steht unter der MIT-Lizenz, © 2026 pottrauschen.
