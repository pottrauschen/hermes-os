# Handbuch: hermes-os benutzen

hermes-os ist ein Linux mit KDE Plasma, in dem ein Assistent mitarbeitet:
**Hermes**. Hermes kennt deinen Rechner (System, Programme, Hardware), kann
Dinge für dich erledigen und fragt vorher, wenn etwas das System verändert.
Diese Seite erklärt die Bedienung. Wie es gebaut ist, steht in
[entwicklung.md](entwicklung.md).

## Der erste Start

1. Anmelden wie gewohnt.
2. Der **Einrichtungsassistent** öffnet sich von selbst. Dort wählst du, mit
   welchem Sprachmodell Hermes arbeitet: einen Anbieter (zum Beispiel
   OpenRouter), deinen Schlüssel von dort und ein Modell. Später findest du
   ihn im Menü als „Hermes einrichten“.
3. Danach sitzt Hermes als Symbol unten rechts in der Leiste.

Die Farbe des Symbols sagt, was Hermes gerade tut:

| Farbe | Bedeutung |
|---|---|
| grau | aus, oder noch nicht eingerichtet |
| blau | bereit |
| orange | arbeitet |
| gelb | fragt dich um Erlaubnis |
| rot mit Mikrofon | hört zu |
| blau mit Lautsprecher | spricht |

## Mit Hermes reden

**Kontor:** So heißt das Chat-Fenster, in der Titelleiste und im Startmenü
„Hermes-Kontor“. Klick auf das Symbol oder **Meta+H**. Frage eintippen,
Enter schickt ab, Umschalt+Enter macht eine neue Zeile. Escape oder
Schließen versteckt das Fenster nur, Hermes bleibt da.

- **Bilder mitschicken:** Knopf mit dem Bild, Strg+V (zum Beispiel ein
  Bildschirmfoto) oder die Datei ins Fenster ziehen.
- **Modell und Denkaufwand:** der kleine Knopf links neben dem Senden-Knopf,
  etwa „Sonnet 5 · mittel“. Mehr Denkaufwand heißt gründlichere, aber
  langsamere Antworten. Dieselbe Wahl gibt es im Rechtsklick-Menü am Symbol.
- **Neues Gespräch:** Knopf „Neu“ oben. Ein leeres Kontor zeigt rechts unten
  drei Vorschläge; ein Klick schickt den Vorschlag gleich ab.
- Oben findest du außerdem **Bibliothek**, **Protokoll** und **Einrichten**.

**Schneller ohne Fenster:**

| Kürzel | Was passiert |
|---|---|
| Meta+H | Kontor auf und zu |
| Meta+Umschalt+H | Bildschirmausschnitt wählen, Hermes sagt, was darauf zu sehen ist |
| Meta+Leertaste halten | Frage sprechen; die Antwort wird vorgelesen |
| Alt+Leertaste, dann `h: deine Frage` | Hermes aus KRunner fragen; Enter öffnet den Chat, „Nur nachschlagen“ antwortet als Benachrichtigung |

Im Terminal geht es auch: `hermes`.

## Was Hermes darf und wann er fragt

Hermes darf ohne Rückfrage alles in deinem Home-Ordner, Programme starten,
Apps aus Flathub installieren und nachsehen, wie es dem System geht.

**Er fragt vorher**, wenn etwas das System selbst verändert: Updates,
Systemdienste, Dateien unter `/etc` oder `/usr`, Firewall, Nutzer, Befehle
mit `sudo`. Dann erscheint im Kontor ein Kasten, und zusätzlich eine
Benachrichtigung mit denselben Knöpfen:

- **Einmal erlauben**: nur dieses eine Mal
- **Für diese Sitzung**: bis zum Ende des Gesprächs
- **Immer**: auch künftig ohne Frage
- **Ablehnen**

Ohne Antwort läuft der Befehl nach fünf Minuten nicht. Neu starten oder
herunterfahren tut Hermes nie selbst; er bittet dich darum.

Im **Protokoll** (Knopf mit der Uhr) siehst du, was Hermes am System getan
hat: Freigaben mit deiner Entscheidung, Systembefehle mit Ergebnis,
gestartete Programme.

## Was Hermes sonst noch kann

- **Bibliothek:** Adressen, Dateien und Ordner eintragen, in denen Hermes
  nachschlagen soll, etwa ein Handbuch oder deine Notizen. Er nennt die
  Quelle, wenn er daraus zitiert. Einträge lassen sich spiegeln und dann
  durchsuchen. Mehr: [bibliothek.md](bibliothek.md).
- **Morgenbericht:** jeden Morgen eine Benachrichtigung zu Updates,
  Fehlern, Plattenplatz und Diensten; „Im Chat besprechen“ öffnet ihn im
  Chat. Einschalten: `ujust hermes-morgenbericht-ein 07:45`.
- **Dashboard:** Hermes' eigene Einstellungen in einem Fenster: Modelle,
  Schlüssel, Gespräche, geplante Aufgaben, Erweiterungen, Protokolle. Im
  Menü am Symbol „Dashboard öffnen“.
- **Lokales Modell:** Hermes ohne Cloud, auf deiner Grafikkarte. Kleine
  Modelle sind schwächer als die großen aus der Cloud. Einschalten:
  `ujust hermes-lokal-ein`. Mehr: [lokales-modell.md](lokales-modell.md).
- **Programme starten:** „Starte Firefox“ reicht.

## Das System aktuell halten

hermes-os aktualisiert sich als Ganzes, wie ein Handy: Das neue System wird
im Hintergrund geladen und gilt ab dem nächsten Neustart. Das alte bleibt
als Rückfall.

- **Updates:** `ujust update`, danach neu starten. Hermes kann das für dich
  anstoßen, fragt aber vorher.
- **Zurück zum Stand davor**, falls nach einem Update etwas nicht geht:
  `sudo bootc rollback`, dann neu starten.
- **Programme:** über Discover oder Flathub. Sie werden getrennt vom System
  aktualisiert.
- Hermes selbst kommt mit dem System. `hermes update` gibt es hier nicht.

## Befehle im Überblick

Alle Befehle von hermes-os beginnen mit `ujust hermes`. `ujust --list | grep hermes`
zeigt sie mit kurzer Erklärung.

| Befehl | Wofür |
|---|---|
| `ujust hermes-setup` | Anbieter, Schlüssel und Modell wählen |
| `ujust hermes-tray` | Kontor öffnen |
| `ujust hermes-dashboard` | Dashboard öffnen |
| `ujust hermes-doctor` | Hermes prüft sich selbst |
| `ujust hermes-gateway-status` | Läuft der Hintergrunddienst? Letzte Meldungen |
| `ujust hermes-gateway-enable` | Hintergrunddienst einschalten |
| `ujust hermes-morgenbericht-ein` / `-aus` | Morgenbericht an und aus |
| `ujust hermes-lokal-ein` / `-aus` / `-entfernen` | lokales Modell |
| `ujust hermes-os-info` | welches System und welches Hermes installiert sind |

## Wenn etwas nicht geht

| Was du siehst | Was hilft |
|---|---|
| Symbol bleibt grau, „Gateway läuft nicht“ | Im Kontor auf „Gateway starten“, oder `ujust hermes-gateway-enable` |
| „noch nicht eingerichtet“ | „Hermes einrichten“ im Menü oder im Fenster |
| Hermes antwortet mit einem Fehler zum Anbieter | Schlüssel und Guthaben beim Anbieter prüfen, dann `ujust hermes-setup` |
| Sprechen geht nicht | Mikrofon in den Systemeinstellungen prüfen; das Symbol sagt, wenn keines da ist |
| Nach einem Update geht etwas nicht mehr | `sudo bootc rollback`, neu starten, und Bescheid geben |
| Unklar, was Hermes getan hat | Protokoll im Kontor |

`ujust hermes-doctor` sammelt die wichtigsten Prüfungen auf einen Blick.
