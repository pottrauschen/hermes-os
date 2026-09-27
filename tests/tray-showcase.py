#!/usr/bin/python3
# =============================================================================
# hermes-os -- Schaubilder des Kontors für Design-Änderungen
# =============================================================================
# Rendert tray/Main.qml offscreen mit einem echt wirkenden Gespräch (lange
# Antwort mit Markdown, Werkzeugzeilen, Bildschirmfoto, Freigabe-Pille) in
# zwei Breiten, damit Vorher und Nachher vergleichbar sind. Nutzt die Stubs
# aus tests/tray-gui-check.py; prüft nichts, das tut der Render-Test.
#
# Aufruf:
#   tests/tray-showcase.py [--qml-dir DIR] --out DIR [--image PNG]
# --image: ein echtes Bildschirmfoto für die Nutzerblase (sonst eine Fläche).
# Läuft, wo PySide6 und Kirigami liegen: Test-VM, Aurora-Desktop.
# =============================================================================
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tray_gui_check", os.path.join(HERE, "tray-gui-check.py"))
tgc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tgc)

from PySide6.QtCore import QDeadlineTimer, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

ANSWER = (
    "Das ist das **Kontor von hermes-os**, über das wir gerade reden.\n\n"
    "**Was auffällt:**\n\n"
    "- Oben links steht der Zustand: *Hermes ist bereit*.\n"
    "- In der Mitte läuft der Verlauf mit deinem Bildschirmfoto.\n"
    "- Unten ist die Eingabe mit Knöpfen für Bild, Ausschnitt und Mikrofon.\n\n"
    "Gebootet ist `hermes-os-privat` in Version `44.20260922.1.20260927.privat`. "
    "Auf `/var` sind noch 5,7 GB frei; das ist knapp, wenn du lokale Modelle laden willst. "
    "Soll ich nachsehen, was dort am meisten Platz braucht?"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qml-dir", default=os.environ.get("HERMES_OS_TRAY_DIR", "/usr/share/hermes-os/tray"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", default="")
    ap.add_argument("--prefix", default="")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    QQuickStyle.setStyle("org.kde.desktop")
    app = QGuiApplication(sys.argv)
    # Offscreen lädt Qt kein Symbol-Thema; ohne Breeze fehlten alle Symbole im Bild
    QIcon.setThemeName("breeze-dark")
    QIcon.setFallbackThemeName("breeze")
    backend, voice, look = tgc.StubBackend(), tgc.StubVoice(), tgc.StubLook()
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", backend)
    ctx.setContextProperty("voice", voice)
    ctx.setContextProperty("look", look)
    engine.load(os.path.join(args.qml_dir, "Main.qml"))
    if not engine.rootObjects():
        print("Main.qml lädt nicht")
        return 1
    root = engine.rootObjects()[0]
    root.show()

    def settle(ms=700):
        deadline = QDeadlineTimer(ms)
        while not deadline.hasExpired():
            app.processEvents()
            app.sendPostedEvents()

    image = args.image
    if not image:
        img = QImage(640, 360, QImage.Format.Format_ARGB32)
        img.fill(QColor("#31363b"))
        image = os.path.join(args.out, "_bild.png")
        img.save(image)
    url = QUrl.fromLocalFile(os.path.abspath(image)).toString()

    backend.set_state("ready", configured=True)
    m = backend._model
    m.append("user", "Welches Image ist gebootet, und wie viel Platz ist noch frei?", when="18:31")
    m.append("tool", "os_status · 0,3 s", meta="completed", when="18:31")
    m.append("tool", "terminal: df -h /var · 0,5 s", meta="completed", when="18:31")
    m.append("assistant", ANSWER, when="18:31")
    m.append("user", "Was sehe ich hier? Beschreibe kurz, was auf diesem Bildschirmausschnitt zu sehen ist.",
             images=[url], when="18:37")
    m.append("assistant", "Das ist das Dashboard von Hermes: Sitzungen, Modelle, Cron-Jobs und Logs "
                          "an einem Ort. Auffällig ist nur, dass es dasselbe Symbol trägt wie das Kontor.",
             when="18:37")
    m.append("info", "Freigabe: Einmal erlaubt", when="18:38")
    m.append("user", "genau - den hast du vergessen - oder?", when="18:38")
    m.append("assistant", "Ja. Das Kontor hätte ganz oben auf der Liste stehen sollen.", when="18:38")

    for name, (w, h) in (("breit", (1180, 780)), ("schmal", (560, 780))):
        root.setWidth(w)
        root.setHeight(h)
        settle(900)
        lv = root.findChild(object, "messageList")
        if lv is not None:
            lv.positionViewAtEnd() if hasattr(lv, "positionViewAtEnd") else None
        settle(400)
        path = os.path.join(args.out, f"{args.prefix}{name}.png")
        root.grabWindow().save(path)
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
