"""hermes-os -- Sprache der Oberfläche des Leisten-Symbols: Deutsch ab Werk,
Englisch, wenn die Sitzung englisch ist (docs/systemagent.md, „Sprache der
Oberfläche“).

Kein gettext und keine .qm-Dateien (im Image gibt es kein lrelease): der
deutsche Quelltext ist der Schlüssel, EN liefert den englischen Text dazu.
Python-Seite: `_(text)` an der Stelle, an der ein Text das Programm verlässt
(Eigenschaft für QML, Benachrichtigung, Menü, Meldung); Konstanten bleiben
deutsch, weil Tests gegen sie vergleichen. QML-Seite: jedes sichtbare Literal
in Main.qml steht in qsTr("…"); hermes-os-tray installiert DictTranslator vor
dem Laden von Main.qml, aber nur in englischer Sitzung. Ohne Übersetzer liefert
qsTr den deutschen Quelltext.

Welche Sprache gilt, entscheidet is_english() bei jedem Aufruf aus der Umgebung.
Die Kopie in plugins/hermes_os/lang.py entscheidet gleich (tests/lang-check.py
prüft den Gleichlauf); sie übersetzt die Texte der Grenze und des Protokolls.

Neue Texte: deutsch schreiben, in _() oder qsTr() einwickeln und hier einen
EN-Eintrag anlegen; tests/lang-check.py findet fehlende Schlüssel.
Nur Standardbibliothek; PySide6 erst, wenn DictTranslator gebraucht wird.
"""
from __future__ import annotations

import os
import re
import string
from typing import Dict, List

_LANG_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def is_english(env=None) -> bool:
    """Englisch, wenn HERMES_OS_LANG mit en beginnt; mit de beginnend deutsch.
    Sonst entscheidet der erste nicht leere Wert aus LANGUAGE (nur der Eintrag vor
    dem ersten Doppelpunkt), LC_ALL, LC_MESSAGES und LANG: englisch, wenn er mit en
    beginnt. Liest die Umgebung bei jedem Aufruf, ohne Zwischenspeicher."""
    env = os.environ if env is None else env
    forced = str(env.get("HERMES_OS_LANG") or "").strip().lower()
    if forced.startswith("en"):
        return True
    if forced.startswith("de"):
        return False
    for name in _LANG_VARS:
        value = str(env.get(name) or "").strip()
        if name == "LANGUAGE":
            value = value.split(":", 1)[0].strip()
        if value:
            return value.lower().startswith("en")
    return False


# Monatsnamen für englische Datumsangaben. Nicht strftime("%b"): QApplication ruft
# setlocale(LC_ALL, ""), danach liefert %b in einer deutschen Sitzung „Okt“.
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

EN: Dict[str, str] = {
    # ---- Main.qml: Kopf, Eingabe, Modell-Auswahl -------------------------------
    "Hermes-Kontor": "Hermes Kontor",
    "Welches Image ist gebootet?": "Which image is booted?",
    "Gibt es ein Update?": "Is there an update?",
    "Starte Firefox": "Launch Firefox",
    "Bibliothek": "Library",
    "Bibliothek: Adressen, Dateien und Ordner, die Hermes kennen soll":
        "Library: addresses, files and folders Hermes should know",
    "Protokoll": "Log",
    "Protokoll: was Hermes am System getan hat": "Log: what Hermes did to the system",
    "Neu": "New",
    "Neues Gespräch": "New conversation",
    "Einrichten": "Set up",
    "Hermes einrichten: Anbieter, Schlüssel und Modell": "Set up Hermes: provider, key and model",
    "Bild entfernen": "Remove image",
    "Frag Hermes …": "Ask Hermes …",
    "Bild anhängen": "Attach image",
    "Bild anhängen: Datei wählen, Strg+V oder ins Fenster ziehen":
        "Attach image: choose a file, press Ctrl+V or drag it into the window",
    "Bildschirmausschnitt anhängen": "Attach screen region",
    "Bildschirmausschnitt wählen und dazu fragen (%1 fragt sofort)":
        "Select a screen region and ask about it (%1 asks right away)",
    "Aufnahme beenden": "Stop recording",
    "Vorlesen abbrechen": "Stop reading aloud",
    "Mit Hermes sprechen": "Talk to Hermes",
    " (%1 halten oder antippen)": " (hold or tap %1)",
    "1 Bild geht mit": "1 image attached",
    "%1 Bilder gehen mit": "%1 images attached",
    "Modell und Denkaufwand für die nächsten Nachrichten": "Model and reasoning for the next messages",
    "Modell": "Model",
    "Anderes Modell: Hermes einrichten …": "Other model: set up Hermes …",
    "Denkaufwand": "Reasoning",
    "Stopp": "Stop",
    "Senden": "Send",
    "Stopp: Hermes anhalten": "Stop: halt Hermes",
    "Senden (Enter) · Umschalt+Enter für eine neue Zeile": "Send (Enter) · Shift+Enter for a new line",
    "Das Gateway läuft, aber in ~/.hermes/.env fehlt der Schlüssel für das Leisten-Symbol. "
    "„Gateway starten“ legt ihn an und startet das Gateway neu.":
        "The gateway is running, but ~/.hermes/.env lacks the key for the tray icon. "
        "“Start gateway” adds it and restarts the gateway.",
    "Das Hermes-Gateway läuft nicht.": "The Hermes gateway is not running.",
    "Hermes ist noch nicht eingerichtet: Anbieter, Schlüssel und Modell fehlen.":
        "Hermes is not set up yet: provider, key and model are missing.",
    "Hermes einrichten": "Set up Hermes",
    "Gateway starten": "Start gateway",
    # ---- Main.qml: Begrüßung, Ablegen, Freigabe -----------------------------------
    "Hallo, ich bin Hermes.": "Hi, I’m Hermes.",
    "Ich kenne dieses System: Image, Dienste, Apps und Hardware. Frag mich etwas, "
    "zieh ein Bild ins Fenster oder füge einen Screenshot mit Strg+V ein.":
        "I know this system: image, services, apps and hardware. Ask me something, "
        "drag an image into the window or paste a screenshot with Ctrl+V.",
    "<b>Meta+Umschalt+H</b> fragt zu einem Bildschirmausschnitt, "
    "<b>Meta+Leertaste</b> halten spricht mit mir.":
        "<b>Meta+Shift+H</b> asks about a screen region, hold <b>Meta+Space</b> to talk to me.",
    "Bild hier ablegen": "Drop image here",
    "Einmal erlauben": "Allow once",
    "Für diese Sitzung": "This session",
    "Immer erlauben": "Always allow",
    "Ablehnen": "Deny",
    "Hermes bittet um Freigabe": "Hermes asks for approval",
    "Warum: ": "Why: ",
    "Ohne Antwort läuft der Befehl nicht.": "Nothing runs without an answer.",
    # ---- Main.qml: Seite Bibliothek ----------------------------------------------
    "Zurück zum Chat": "Back to chat",
    "1 Eintrag": "1 entry",
    "%1 Einträge": "%1 entries",
    "Kein Spiegel: noch nicht indiziert.": "No mirror: not indexed yet.",
    "Adressen, Dateien und Ordner, die Hermes kennen soll. Er liest sie bei Bedarf, folgt "
    "Verweisen auf derselben Seite und nennt die Quelle. „Spiegeln“ legt einen durchsuchbaren "
    "Index an, in dem Hermes und du suchen. Neue Einträge gelten ab dem nächsten Gespräch.":
        "Addresses, files and folders Hermes should know. He reads them when needed, follows "
        "links on the same site and names the source. “Mirror” builds a searchable index for "
        "Hermes and you. New entries apply from the next conversation.",
    "Adresse oder Pfad:": "Address or path:",
    "https://docs.kde.org/ oder ein Ordner im Home": "https://docs.kde.org/ or a folder in your home",
    "Datei wählen": "Choose file",
    "Ordner wählen": "Choose folder",
    "Titel:": "Title:",
    "optional, sonst Host oder Dateiname": "optional, otherwise host or file name",
    "Notiz für Hermes:": "Note for Hermes:",
    "z. B. deutsche Handbücher unter stable_kf6/de": "e.g. English handbooks under stable_kf6/en",
    "Hinzufügen": "Add",
    "Dateien, Ordner oder eine Adresse aus dem Browser hierher ziehen":
        "Drag files, folders or an address from the browser here",
    "In den Spiegeln suchen, z. B. versteckte Dateien": "Search the mirrors, e.g. hidden files",
    "Suchen": "Search",
    "Öffnen": "Open",
    "Noch keine Einträge": "No entries yet",
    "Trag oben eine Adresse ein, zum Beispiel https://docs.kde.org/, oder wähle eine Datei oder einen Ordner.":
        "Enter an address above, for example https://docs.kde.org/, or choose a file or a folder.",
    "Spiegeln abbrechen": "Cancel mirroring",
    "Spiegeln": "Mirror",
    "Spiegeln: Seiten samt Verweisen auf demselben Host in den Index holen (Ordner und Dateien werden indiziert)":
        "Mirror: fetch pages and their links on the same host into the index (folders and files are indexed)",
    "Titel und Notiz ändern": "Edit title and note",
    "Entfernen": "Remove",
    "Speichern": "Save",
    "Abbrechen": "Cancel",
    "Doku-Server (MCP)": "Documentation servers (MCP)",
    "Server aus Hermes' Katalog, die Fragen zu Bibliotheken, Frameworks und fremden Projekten aus "
    "deren Dokumentation beantworten. Ein Schalter trägt den Server in Hermes' config.yaml ein oder "
    "aus; das Gateway übernimmt das von selbst innerhalb etwa einer Minute, ein laufendes Gespräch "
    "ab dem nächsten neuen Gespräch.":
        "Servers from Hermes' catalog that answer questions about libraries, frameworks and other "
        "projects from their documentation. A switch adds the server to Hermes' config.yaml or removes "
        "it; the gateway picks that up by itself within about a minute, a running conversation from "
        "the next new conversation.",
    # ---- Main.qml: Seite Protokoll -------------------------------------------------
    "Heute": "Today",
    "Letzte 7 Tage": "Last 7 days",
    "Alles": "All",
    "Nur Änderungen": "Changes only",
    "Nur Systembefehle, die wirklich gelaufen sind": "Only system commands that actually ran",
    "Exportieren": "Export",
    # Schlüsselwörter, an denen die Seite eine Fehlermeldung erkennt: die englischen
    # Meldungen aus hermes-os-tray und audit.py enthalten genau diese Wörter
    "fehlgeschlagen": "failed",
    "nicht verfügbar": "not available",
    # Datum wie in audit.py (Spalte date), damit „heute“ nur die Uhrzeit zeigt
    "dd.MM.yyyy": "yyyy-MM-dd",
    "Keine Änderungen am System": "No changes to the system",
    "Noch nichts protokolliert": "Nothing logged yet",
    "Hier steht, was Hermes am System getan hat: jede Freigabe-Anfrage mit Entscheidung, "
    "jeder Systembefehl mit Ergebnis und jeder App-Start. Andere Zeiträume stehen oben zur Wahl.":
        "This shows what Hermes did to the system: every approval request with its decision, "
        "every system command with its result and every app launch. Other time ranges can be chosen above.",
    "Ausgabe ausblenden": "Hide output",
    "Ausgabe zeigen": "Show output",

    # ---- hermes-os-tray: Zustand, Verlauf, Dialoge, Menü ------------------------------
    "Hermes ist aus": "Hermes is off",
    "Hermes läuft, aber der Schlüssel für das Leisten-Symbol fehlt":
        "Hermes is running, but the key for the tray icon is missing",
    "Hermes ist bereit": "Hermes is ready",
    "Hermes arbeitet": "Hermes is working",
    "Hermes fragt nach einer Freigabe": "Hermes asks for approval",
    "Kein lesbares Bild: {name}": "Not a readable image: {name}",
    "Bild auch verkleinert zu groß: {name}": "Image too large even when scaled down: {name}",
    "fertig": "done",
    "Fehler": "error",
    "Modell nicht umgestellt: {err}": "Model not changed: {err}",
    "Modell für die nächsten Nachrichten: {model}": "Model for the next messages: {model}",
    "Denkaufwand nicht umgestellt: {err}": "Reasoning not changed: {err}",
    "Denkaufwand für die nächsten Nachrichten: {effort}": "Reasoning for the next messages: {effort}",
    "Höchstens {count} Bilder je Nachricht.": "At most {count} images per message.",
    "Bilder (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;Alle Dateien (*)":
        "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;All files (*)",
    " (nicht aus diesem Fenster gestartet)": " (not started from this window)",
    "Bibliothek: {title}, {state}": "Library: {title}, {state}",
    "Noch kein Spiegel: erst einen Eintrag spiegeln, dann suchen.":
        "No mirror yet: mirror an entry first, then search.",
    "Keine Treffer für „{query}“.": "No hits for “{query}”.",
    "1 Treffer für „{query}“": "1 hit for “{query}”",
    "{count} Treffer für „{query}“": "{count} hits for “{query}”",
    " (LIKE-Suche, kein FTS5).": " (LIKE search, no FTS5).",
    "Suche fehlgeschlagen: {err}": "Search failed: {err}",
    "Die Bibliothek ist nicht verfügbar (library.py fehlt).": "The library is not available (library.py missing).",
    "Nichts Verwertbares abgelegt: Dateien, Ordner oder eine http(s)-Adresse.":
        "Nothing usable dropped: files, folders or an http(s) address.",
    "Eingetragen: {titles}": "Added: {titles}",
    "Eingetragen, gilt ab dem nächsten Gespräch: {titles}": "Added, applies from the next conversation: {titles}",
    "Bibliothek: {titles} eingetragen, gilt ab dem nächsten Gespräch.":
        "Library: {titles} added, applies from the next conversation.",
    "Datei für die Bibliothek": "File for the library",
    "Texte und Dokumente (*.pdf *.md *.txt *.html *.htm *.rst *.csv *.json *.yaml *.yml);;Alle Dateien (*)":
        "Texts and documents (*.pdf *.md *.txt *.html *.htm *.rst *.csv *.json *.yaml *.yml);;All files (*)",
    "Ordner für die Bibliothek": "Folder for the library",
    "Das Protokoll ist nicht verfügbar (audit.py fehlt).": "The log is not available (audit.py missing).",
    "hermes-protokoll-{date}.txt": "hermes-log-{date}.txt",
    "Protokoll exportieren": "Export log",
    "Textdateien (*.txt);;Alle Dateien (*)": "Text files (*.txt);;All files (*)",
    "Gespeichert: {path}": "Saved: {path}",
    "(Bild mitgeschickt)": "(image attached)",
    "Verlauf nicht geladen: {err}": "History not loaded: {err}",
    "Der Bericht zur Benachrichtigung ist nicht mehr da.": "The report for this notification is gone.",
    "Frag nach, was dich daran interessiert; der Bericht geht mit.":
        "Ask about whatever interests you; the report goes along.",
    "Frage zum Bildschirmausschnitt: {question}\n\nAntwort von Hermes: {answer}":
        "Question about the screen region: {question}\n\nAnswer from Hermes: {answer}",
    "Frag nach, was dich daran interessiert; Ausschnitt und Antwort gehen mit.":
        "Ask about whatever interests you; the region and the answer go along.",
    "unbekannt": "unknown",
    "Hermes hat abgebrochen: {reason}": "Hermes aborted: {reason}",
    "Abgebrochen.": "Cancelled.",
    "Freigabe: {detail}": "Approval: {detail}",
    "Kontor öffnen": "Open Kontor",
    "kein Modell": "no model",
    "Was sehe ich hier?": "What am I looking at?",
    "Dashboard öffnen": "Open dashboard",
    "Chat im Terminal": "Chat in terminal",
    "Beenden": "Quit",

    # ---- model_choice.py: Denkaufwand --------------------------------------------------
    "Vorgabe": "Default",
    "wenig": "low",
    "mittel": "medium",
    "gründlich": "thorough",
    "sehr gründlich": "very thorough",
    "maximal": "maximum",
    "unbekannter Denkaufwand: {effort}": "unknown reasoning level: {effort}",

    # ---- runner.py: KRunner und Nachschlagen -------------------------------------------
    "Enter: im Kontor fragen": "Enter: ask in the Kontor",
    "Hermes fragen: ": "Ask Hermes: ",
    "Nur nachschlagen": "Look up only",
    "Hermes nicht erreichbar: {err}": "Hermes not reachable: {err}",
    "Verbindung abgebrochen, bevor Hermes fertig war.": "Connection lost before Hermes finished.",
    "Verbindung abgebrochen: {err}": "Connection lost: {err}",
    "Keine Antwort in der Zeit. Im Kontor weiterfragen.": "No answer in time. Keep asking in the Kontor.",
    "Hermes wollte einen Befehl mit Freigabe ausführen; beim Nachschlagen wird das abgelehnt.":
        "Hermes wanted to run a command that needs approval; a lookup denies that.",
    "(keine Antwort)": "(no answer)",
    "Hermes: Nachschlagen fehlgeschlagen": "Hermes: lookup failed",
    "Hermes ist nicht bereit": "Hermes is not ready",
    "Die Frage aus KRunner steht im Eingabefeld des Kontors.":
        "The question from KRunner is waiting in the Kontor input field.",

    # ---- screenshot.py: Was sehe ich hier? ------------------------------------------------
    "Was sehe ich hier? Beschreibe kurz, was auf diesem Bildschirmausschnitt zu sehen ist, "
    "und sag, was daran wichtig oder auffällig ist.":
        "What am I looking at here? Briefly describe what this screen region shows "
        "and say what is important or striking about it.",
    "Hermes: Was sehe ich hier?": "Hermes: What am I looking at?",
    "Im Chat besprechen": "Discuss in chat",
    "Spectacle ist nicht installiert.": "Spectacle is not installed.",
    "Cache nicht beschreibbar: {err}": "Cache not writable: {err}",
    "Spectacle startet nicht: {err}": "Spectacle does not start: {err}",
    "Exit {code}": "exit {code}",
    "Kein Bildschirmausschnitt": "No screen region",

    # ---- voice.py: Push-to-Talk -----------------------------------------------------------
    "Hermes hört zu …": "Hermes is listening …",
    "Hermes versteht …": "Hermes is transcribing …",
    "Hermes denkt nach …": "Hermes is thinking …",
    "Hermes spricht …": "Hermes is speaking …",
    "unbekannter Rekorder: {tool}": "unknown recorder: {tool}",
    "kein Aufnahmeprogramm (pw-record, parecord, arecord) gefunden":
        "no recording program (pw-record, parecord, arecord) found",
    "{program} startet nicht: {err}": "{program} does not start: {err}",
    "keine Aufnahme": "no recording",
    "Nichts aufgenommen ({hint}). Ist ein Mikrofon angeschlossen und in den Systemeinstellungen gewählt?":
        "Nothing recorded ({hint}). Is a microphone connected and selected in System Settings?",
    "Zu kurz gedrückt: Kürzel halten und sprechen, oder antippen und beim nächsten Druck beenden.":
        "Pressed too briefly: hold the shortcut and speak, or tap it and press again to stop.",
    "Sprachhelfer startet nicht: {err}": "Speech helper does not start: {err}",
    "Sprachhelfer hat sich beendet": "Speech helper has exited",
    "Sprachhelfer nicht erreichbar: {err}": "Speech helper not reachable: {err}",
    "Sprachhelfer antwortet nicht ({op}, {seconds} s)": "Speech helper does not answer ({op}, {seconds} s)",
    " Codeblock ausgelassen. ": " Code block skipped. ",
    " … Den Rest zeige ich im Fenster.": " … The rest is in the window.",
    "Hermes kann nicht zuhören": "Hermes cannot listen",
    "Aufnahme nicht möglich.": "Recording is not possible.",
    "Hermes hat nichts gehört": "Hermes heard nothing",
    "Hermes hat dich nicht verstanden": "Hermes did not understand you",
    "Hermes hat nichts verstanden": "Hermes understood nothing",
    "Bitte noch einmal, etwas näher am Mikrofon.": "Please try again, a little closer to the microphone.",
    "Verstanden: „{text}“. Das Gateway antwortet gerade nicht.":
        "Understood: “{text}”. The gateway is not answering right now.",
    "Hermes kann nicht sprechen": "Hermes cannot speak",
    "Kein Aufnahmeprogramm (pw-record oder parecord) gefunden.": "No recording program (pw-record or parecord) found.",
    "Der Sprachhelfer der Hermes-Venv fehlt.": "The speech helper in the Hermes venv is missing.",
    "Kein Mikrofon gefunden. Anschließen und in den Systemeinstellungen unter Audio wählen.":
        "No microphone found. Connect one and select it in System Settings under Audio.",
    "Erkennung fehlgeschlagen": "Recognition failed",
    "Sprachausgabe fehlgeschlagen": "Speech output failed",
    "Kein Abspielprogramm (pw-play, paplay, aplay) gefunden.": "No playback program (pw-play, paplay, aplay) found.",
    "Lade Sprachmodell {name} …": "Loading speech model {name} …",
    "Lade Stimme {name} …": "Loading voice {name} …",
}


def _(text: str) -> str:
    """Text in der Sprache der Sitzung: englisch aus EN, sonst der deutsche Quelltext.
    Unbekannte Texte bleiben, wie sie sind."""
    if is_english():
        return EN.get(text, text)
    return text


# ---- Übersetzer für Main.qml --------------------------------------------------------------
_TRANSLATOR_CLASS = None


def _translator_class():
    global _TRANSLATOR_CLASS
    if _TRANSLATOR_CLASS is None:
        from PySide6.QtCore import QTranslator

        class DictTranslator(QTranslator):
            """QTranslator aus einem Wörterbuch: liefert zum deutschen Quelltext den
            englischen, sonst None (Null-QString, dann nimmt Qt den Quelltext; ein
            leerer Text "" wäre ein gültiges Ergebnis und leert Qt-eigene Menüs). Der Kontext zählt nicht;
            Qt fragt auch eigene Kontexte (QGuiApplication, QIODevice) ab, die kennt EN
            nicht. isEmpty() muss False sein, sonst meldet installTranslator False und
            schickt kein LanguageChange."""

            def __init__(self, parent=None, table=None):
                super().__init__(parent)
                self._table = EN if table is None else table

            def translate(self, context, sourceText, disambiguation=None, n=-1):
                if not isinstance(sourceText, str):
                    sourceText = bytes(sourceText or b"").decode("utf-8", "replace")
                return self._table.get(sourceText)

            def isEmpty(self):
                return False

        _TRANSLATOR_CLASS = DictTranslator
    return _TRANSLATOR_CLASS


def __getattr__(name):
    # lang.DictTranslator erst beim ersten Zugriff bauen: das Modul lädt ohne Qt
    # (Tests, model_choice, runner), und ohne PySide6 gibt es die Klasse nicht.
    if name == "DictTranslator":
        try:
            return _translator_class()
        except ImportError as exc:
            raise AttributeError(f"DictTranslator braucht PySide6: {exc}") from exc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---- Selbsttest (hermes-os-tray --check, tests/lang-check.py) --------------------------------
_TOKEN_RES = (re.compile(r"%[0-9A-Za-z]"), re.compile(r"`"), re.compile(r"</?\w+>"))


def placeholders(text: str) -> List[str]:
    """Was in Schlüssel und Übersetzung gleich sein muss: {Felder}, %1 und
    strftime-Kürzel, Backticks, HTML-Tags. ValueError bei kaputten Klammern."""
    fields = sorted(f for _lit, f, _spec, _conv in string.Formatter().parse(text) if f is not None)
    tokens = sorted(t for rx in _TOKEN_RES for t in rx.findall(text))
    return ["{" + f + "}" for f in fields] + tokens


def check_table(table: Dict[str, str]) -> List[str]:
    problems = []
    for key, value in table.items():
        if not isinstance(key, str) or not isinstance(value, str):
            problems.append(f"kein Text: {key!r} -> {value!r}")
            continue
        if key and not value.strip():
            problems.append(f"leere Übersetzung für {key!r}")
        try:
            if placeholders(key) != placeholders(value):
                problems.append(f"Platzhalter weichen ab: {key!r} -> {value!r}")
        except ValueError as exc:
            problems.append(f"Platzhalter unlesbar ({exc}): {key!r}")
    return problems


def self_test() -> List[str]:
    """Befunde, leer heißt in Ordnung."""
    problems = check_table(EN)
    cases = [({}, False), ({"LANG": "en_US.UTF-8"}, True), ({"LANG": "de_DE.UTF-8", "HERMES_OS_LANG": "en"}, True),
             ({"LANG": "en_US.UTF-8", "HERMES_OS_LANG": "de"}, False), ({"LANGUAGE": "en_US:de"}, True),
             ({"LANGUAGE": "de", "LANG": "en_US.UTF-8"}, False), ({"LC_ALL": "C.UTF-8", "LANG": "en_US.UTF-8"}, False)]
    for env, want in cases:
        if is_english(env) != want:
            problems.append(f"is_english({env}) liefert {not want}")
    return problems
