# Phase 3: Desktop-Steuerung

Stand: 2026-09-25. Bewertung von [kortix-ai/agent-computer-use](https://github.com/kortix-ai/agent-computer-use)
(`agent-cu`, MIT, Rust, Version 0.1.1) als Grundlage für die dritte Tür aus dem Bauplan:
Widgets semantisch lesen und bedienen über AT-SPI statt Pixel klicken.

## Was agent-cu ist

Ein einzelnes Binary mit einer CLI, die jede Desktop-App über den Accessibility-Baum
bedient. Kern-Schleife: `snapshot` liefert die interaktiven Elemente mit Referenzen
(`@e5`), `click`/`type`/`key` handeln, ein erneuter `snapshot` prüft das Ergebnis. Alle
Ausgaben sind JSON. Dazu `find` mit Selektoren, `wait-for`, `ensure-text`, `get-value`,
`batch`, YAML-Workflows zum Wiederabspielen, und eine `SKILL.md`, die einem Agenten
genau diese Schleife beibringt.

Aufbau: `agent-computer-use-core` (Knoten, Rollen, Selektoren, Aktionen), je ein Crate für
Linux, macOS, Windows, plus Chrome DevTools für Electron und Browser.

## Warum es zu hermes-os passt

- Es ist die Evidence-Idee auf Desktop-Ebene: nichts gilt als getan, bevor ein neuer
  Snapshot es zeigt. Keine Vision-Tokens, deterministisch.
- Linux-Backend liest über AT-SPI2 auf D-Bus (`zbus`). AT-SPI ist unabhängig vom
  Compositor, das Lesen funktioniert also unter Wayland genauso wie unter X11.
- Ein statisches Binary lässt sich ins Image backen. Die `SKILL.md` lässt sich fast
  wörtlich als Hermes-Skill übernehmen.

## Wo es für hermes-os nicht reicht

Das Linux-Crate teilt sich in zwei Hälften, und nur eine ist Wayland-tauglich:

| Funktion | Umsetzung in 0.1.1 | Unter Plasma Wayland |
|---|---|---|
| Baum lesen, Elemente finden, Text, Werte, Fenster auflisten | AT-SPI2 über D-Bus | funktioniert |
| Klicken, Tippen, Tasten, Fenster aktivieren, verschieben, Screenshot | `xdotool` (X11) | nur XWayland-Fenster, native Qt/GTK-Apps nicht |
| Fokussiertes Element | nicht implementiert | fehlt |
| Berechtigungsprüfung | nur Verbindungstest zur Registry | schaltet den a11y-Bus nicht ein |

Klicks werden über `Component.GetExtents` in Koordinaten übersetzt und dann per
`xdotool` ausgeführt. Die AT-SPI-Schnittstellen `Action` (DoAction: click, press) und
`EditableText` (SetTextContents) werden nicht benutzt, obwohl sie ohne Zeiger auskommen
und überall funktionieren.

Offen und erst auf dem gebooteten System prüfbar: Qt-Apps unter KDE stellen ihren
Baum nur bereit, wenn Accessibility aktiv ist (`org.a11y.Status`, oder
`QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`). agent-cu setzt das nicht selbst.

## Plan

1. **Binary ins Image.** Eigener CI-Job baut `agent-cu` aus dem gepinnten Tag mit Cargo
   und legt es als Artefakt ab; `files/scripts/30-desktop.sh` kopiert es nach
   `/usr/bin/agent-cu`. Kein `xdotool` im Image, das wäre X11.
2. **Hermes-Skill** `hermes-os-desktop` aus der `SKILL.md`, angepasst: keine Claude-Code-
   Freigaberegeln, stattdessen die hermes-os-Grenze (Apps bedienen ist frei, das System
   bleibt hinter dem Freigabe-Gate). Gefahrenstufe: `agent-cu` schreibt in Apps, nicht
   ins System, also frei.
3. **Wayland-Eingabe beisteuern.** Im Linux-Crate eine zweite Eingabeschicht:
   zuerst AT-SPI `Action` und `EditableText` (deckt Buttons, Menüs, Textfelder ohne
   Zeiger ab), dann für echte Zeiger- und Tastatureingabe `libei` über das
   RemoteDesktop-Portal (Plasma 6 unterstützt es, Freigabe kann dauerhaft gespeichert
   werden). Fenster aktivieren und verschieben über KWin-Scripting per D-Bus statt
   `xdotool`. Größenordnung: einige hundert Zeilen Rust. Upstream anbieten, sonst Fork.
4. **Auf dem Image testen:** a11y-Bus-Status unter KDE, Thunderbird und Konsole über
   `agent-cu snapshot` lesen, dann einen Klick über `Action`.

## Risiken

- Junges Projekt: Version 0.1.1, zwei npm-Releases, letzter Commit Mai 2026, ein
  Hauptautor. Die CLI-Schnittstelle kann sich ändern, also Tag pinnen.
- Bis Schritt 3 fertig ist, kann der Agent unter Wayland lesen, aber nicht handeln.
  Für "öffne Thunderbird" reicht weiterhin `app_launch` aus Phase 2.
