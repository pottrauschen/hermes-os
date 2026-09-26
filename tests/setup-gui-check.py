#!/usr/bin/python3
# =============================================================================
# hermes-os -- Einrichtungsassistent offscreen rendern (ohne Display, ohne Netz)
# =============================================================================
# Lädt Main.qml mit einem Stub statt der echten Brücke, springt jede Seite an,
# zeichnet sie und legt optional ein PNG je Seite ab. Jede QML-Warnung ist ein
# Fehler: so fällt ein kaputtes Binding oder ein umbenanntes Kirigami-Element
# schon im Image-Build auf, nicht erst beim ersten Login.
#
# Aufruf:
#   tests/setup-gui-check.py [--qml-dir DIR] [--out DIR]
# Exit 0 = alle Seiten sauber. Läuft überall, wo PySide6 und Kirigami liegen:
# im Image-Build (80-validate.sh), in der Test-VM, auf einem Aurora-Desktop.
# =============================================================================
import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

from PySide6.QtCore import (QDeadlineTimer, QObject, QTimer, Property, Signal, Slot,
                            qInstallMessageHandler, QtMsgType)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

PAGES = ["welcome", "provider", "key", "portal", "save"]
# Harmloses Rauschen ohne Display; alles andere zählt.
IGNORE = ("MESA-EGL", "egl: failed", "Could not register app ID", "QXcbConnection",
          "dri2 screen", "portal")


class StubBackend(QObject):
    """Dieselbe Schnittstelle wie Backend in hermes-os-setup, ohne Hermes."""
    busyChanged = Signal()
    modelsReady = Signal("QVariantList", str, str)
    modelsFailed = Signal(str)
    saved = Signal(str, str)
    saveFailed = Signal(str)

    def __init__(self):
        super().__init__()
        self._busy = False
        self.calls = []

    @Property("QVariantList", constant=True)
    def providers(self):
        return [
            {"slug": "openrouter", "label": "OpenRouter", "auth": "api_key",
             "env": "OPENROUTER_API_KEY", "signup": "https://openrouter.ai/keys", "hint": "",
             "login": []},
            {"slug": "anthropic", "label": "Anthropic", "auth": "api_key",
             "env": "ANTHROPIC_API_KEY", "signup": "https://platform.claude.com/settings/keys",
             "hint": "Claude Pro/Max lässt sich hier nicht verwenden.", "login": []},
            {"slug": "nous", "label": "Nous Portal", "auth": "oauth", "env": "",
             "signup": "https://nousresearch.com/", "hint": "Anmeldung im Terminal, Adresse und Code.",
             "login": ["portal"]},
        ]

    @Property(str, constant=True)
    def catalogError(self):
        return ""

    @Property(str, constant=True)
    def configuredProvider(self):
        return "openrouter"

    @Property(str, constant=True)
    def hermesVersion(self):
        return "Hermes Agent (Stub)"

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Slot(str, str)
    def checkKey(self, slug, key):
        self.calls.append(("checkKey", slug))
        QTimer.singleShot(0, lambda: self.modelsReady.emit(["a/modell-1", "b/modell-2"], "b/modell-2", "ok"))

    @Slot(str, str, str)
    def save(self, slug, key, model):
        self.calls.append(("save", slug, model))
        QTimer.singleShot(0, lambda: self.saved.emit(slug, model))

    @Slot(str)
    def openUrl(self, url):
        self.calls.append(("openUrl", url))

    @Slot(str)
    def copyToClipboard(self, text):
        self.calls.append(("copy", text))

    @Slot()
    def openTerminalSetup(self):
        self.calls.append(("terminal",))

    @Slot(str)
    def openLogin(self, slug):
        self.calls.append(("login", slug))

    @Slot()
    def openChat(self):
        self.calls.append(("chat",))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qml-dir", default=os.environ.get("HERMES_OS_SETUP_DIR", "/usr/share/hermes-os/setup"))
    ap.add_argument("--out", default="", help="PNG je Seite hierhin (optional)")
    args = ap.parse_args()
    main_qml = os.path.join(args.qml_dir, "Main.qml")
    if not os.path.isfile(main_qml):
        print(f"FEHL  {main_qml} fehlt")
        return 1

    warnings = []

    def handler(mode, ctx, msg):
        if any(s in msg for s in IGNORE):
            return
        # Nur Meldungen aus QML zählen: Bindings, fehlende Typen, Fehler in
        # Handlern nennen immer die .qml-Datei. Plattform-Rauschen (kein D-Bus
        # im Build-Container, keine Sitzung) wird gezeigt, bricht aber nicht ab.
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) and ".qml" in msg:
            warnings.append(msg)
        else:
            print(f"      {msg}")

    qInstallMessageHandler(handler)
    QQuickStyle.setStyle("org.kde.desktop")
    app = QGuiApplication(sys.argv)
    backend = StubBackend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(main_qml)
    if not engine.rootObjects():
        print("FEHL  Main.qml lädt nicht")
        for w in warnings:
            print(f"      {w}")
        return 1
    root = engine.rootObjects()[0]
    root.show()
    fail = 0

    def settle(ms=600):
        # Ereignisse verarbeiten, bis Seite, Bindings, Stub-Signale, verzögerte
        # Löschungen (deleteLater) und die Einblend-Animationen von Kirigami
        # (InlineMessage) durch sind.
        deadline = QDeadlineTimer(ms)
        while not deadline.hasExpired():
            app.processEvents()
            app.sendPostedEvents()

    for page in PAGES:
        before = len(warnings)
        ok = root.showPage(page)
        settle()
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            img = root.grabWindow()
            path = os.path.join(args.out, f"setup-{page}.png")
            img.save(path)
        new = warnings[before:]
        if not ok or new:
            fail = 1
            print(f"FEHL  Seite {page}: {'nicht gefunden' if not ok else ''}")
            for w in new:
                print(f"      {w}")
        else:
            print(f"OK    Seite {page} gerendert")
    # Modellsuche: Stub liefert Modelle, die Vorgabe muss gewählt sein, und
    # der Filter muss Wörter unabhängig von Groß/Klein finden.
    before = len(warnings)
    root.showPage("key")
    settle()
    backend.modelsReady.emit(["anthropic/claude-sonnet-5", "openai/gpt-6", "deepseek/deepseek-v4"],
                             "openai/gpt-6", "ok")
    settle()
    chosen = root.property("model")

    def js(value):  # QML-Funktionen liefern QJSValue, Arrays daraus als Liste
        return value.toVariant() if hasattr(value, "toVariant") else value

    hits = list(js(root.filterModels("Claude SONNET")))
    none = list(js(root.filterModels("gibtesnicht")))
    # Aufklappliste öffnen: die Liste muss Einträge und Höhe haben
    root.openModelList()
    settle()
    lv = root.findChild(QObject, "modelList")
    lv_ok = lv is not None and lv.property("count") == 3 and lv.property("visible") \
        and lv.property("height") > 0 and lv.property("contentHeight") > 0
    if lv is not None:
        print("      Modellliste: count=%s sichtbar=%s %sx%s contentHeight=%s" % (
            lv.property("count"), lv.property("visible"), lv.property("width"), lv.property("height"),
            lv.property("contentHeight")))
    if args.out:
        root.grabWindow().save(os.path.join(args.out, "setup-key-models-open.png"))
    # Tippen im Suchfeld darf weder wählen noch die Liste schließen (Kirigamis
    # SearchField feuert accepted sonst bei jeder Änderung, 2026-09-26).
    root.typeModelFilter("deep")
    settle()
    typing_ok = bool(root.modelListOpen()) and root.property("model") == "openai/gpt-6" \
        and lv is not None and lv.property("count") == 1
    print("      Tippen: Liste offen=%s gewählt=%r Treffer=%s" % (
        bool(root.modelListOpen()), root.property("model"), lv.property("count") if lv else None))
    root.closeModelList()
    settle()
    if chosen != "openai/gpt-6" or hits != ["anthropic/claude-sonnet-5"] or none or not lv_ok \
       or not typing_ok or warnings[before:]:
        fail = 1
        print(f"FEHL  Modellsuche: gewählt={chosen!r} treffer={hits!r} leer={none!r}")
        for w in warnings[before:]:
            print(f"      {w}")
    else:
        print("OK    Modellsuche: Vorgabe gewählt, Filter findet Wörter, Tippen wählt nicht")
    if args.out:
        root.grabWindow().save(os.path.join(args.out, "setup-key-models.png"))

    # Zurück und wieder Weiter, wie ein Nutzer: Kirigami löscht beim Poppen
    # Seiten ohne Elternteil verzögert; danach schlug jeder weitere Klick auf
    # Weiter fehl (2026-09-26). Deshalb liegen die Seiten in Main.qml in einem
    # Behälter-Item, und dieser Schritt prüft, dass sie das Poppen überleben.
    before = len(warnings)
    root.showPage("provider")
    settle()
    root.pushPage("key")
    settle()
    root.goBack()
    settle()
    alive = root.hasPage("key")
    root.pushPage("key")
    settle()
    if not alive or warnings[before:]:
        fail = 1
        print("FEHL  Zurück und wieder Weiter: Schlüssel-Seite " + ("verloren" if not alive else "mit Warnung"))
        for w in warnings[before:]:
            print(f"      {w}")
    else:
        print("OK    Zurück und wieder Weiter: Seite überlebt das Poppen")

    # Fertig-Seite: der Stub muss das Speichern gesehen haben
    if ("save", "openrouter", "test/modell") not in backend.calls:
        fail = 1
        print(f"FEHL  Fertig-Seite hat backend.save nicht aufgerufen: {backend.calls}")
    else:
        print("OK    Fertig-Seite ruft backend.save mit Anbieter und Modell")
    root.close()
    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
