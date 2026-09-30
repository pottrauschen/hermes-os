#!/usr/bin/python3
# =============================================================================
# hermes-os -- Schaubilder des Kontors für Design-Änderungen
# =============================================================================
# Rendert tray/Main.qml offscreen mit einem echt wirkenden Gespräch (lange
# Antwort mit Markdown, Werkzeugzeilen, Bildschirmfoto, Freigabe-Pille) in
# zwei Breiten, dazu schmal die Begrüßung im leeren Kontor und die tippenden
# Punkte, damit Vorher und Nachher vergleichbar sind. Nutzt die Stubs aus
# tests/tray-gui-check.py; prüft nichts, das tut der Render-Test.
#
# Aufruf:
#   tests/tray-showcase.py [--qml-dir DIR] --out DIR [--image PNG] [--lang en]
# --image: ein echtes Bildschirmfoto für die Nutzerblase (sonst eine Fläche).
# --lang en: englische Oberfläche wie in einer englischen Sitzung (Übersetzer aus
#   lang.py im QML-Ordner) und ein englisches Gespräch, etwa für einen Demo-Clip.
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
    "Gebootet ist `hermes-os-nvidia` in Version `44.20260922.1.20260927`. "
    "Auf `/var` sind noch 5,7 GB frei; das ist knapp, wenn du lokale Modelle laden willst. "
    "Soll ich nachsehen, was dort am meisten Platz braucht?"
)
ANSWER_EN = (
    "This is the **hermes-os Kontor**, the window we are talking about.\n\n"
    "**What stands out:**\n\n"
    "- Top left shows the state: *Hermes is ready*.\n"
    "- The history in the middle shows your screenshot.\n"
    "- At the bottom is the input with buttons for image, screen region and microphone.\n\n"
    "Booted is `hermes-os-nvidia` in version `44.20260922.1.20260927`. "
    "`/var` has 5.7 GB free; that is tight if you want to load local models. "
    "Shall I check what takes the most space there?"
)


def conversation(lang, url):
    """Das Gespräch der Schaubilder: (Rolle, Text, Metadaten, Bilder, Uhrzeit)."""
    if lang == "en":
        return [
            ("user", "Which image is booted, and how much space is left?", "", None, "18:31"),
            ("tool", "os_status · 0.3 s", "completed", None, "18:31"),
            ("tool", "terminal: df -h /var · 0.5 s", "completed", None, "18:31"),
            ("assistant", ANSWER_EN, "", None, "18:31"),
            ("user", "What am I looking at here? Briefly describe what this screen region shows.", "", [url], "18:37"),
            ("assistant", "This is the Hermes dashboard: sessions, models, cron jobs and logs in one place. "
                          "The only odd thing is that it carries the same icon as the Kontor.", "", None, "18:37"),
            ("info", "Approval: Allow once", "", None, "18:38"),
            ("user", "right, you forgot that one, didn't you?", "", None, "18:38"),
            ("assistant", "Yes. The Kontor should have been at the top of the list.", "", None, "18:38"),
        ], ("user", "Then please add it.", "", None, "18:39")
    return [
        ("user", "Welches Image ist gebootet, und wie viel Platz ist noch frei?", "", None, "18:31"),
        ("tool", "os_status · 0,3 s", "completed", None, "18:31"),
        ("tool", "terminal: df -h /var · 0,5 s", "completed", None, "18:31"),
        ("assistant", ANSWER, "", None, "18:31"),
        ("user", "Was sehe ich hier? Beschreibe kurz, was auf diesem Bildschirmausschnitt zu sehen ist.", "", [url],
         "18:37"),
        ("assistant", "Das ist das Dashboard von Hermes: Sitzungen, Modelle, Cron-Jobs und Logs "
                      "an einem Ort. Auffällig ist nur, dass es dasselbe Symbol trägt wie das Kontor.", "", None, "18:37"),
        ("info", "Freigabe: Einmal erlaubt", "", None, "18:38"),
        ("user", "genau - den hast du vergessen - oder?", "", None, "18:38"),
        ("assistant", "Ja. Das Kontor hätte ganz oben auf der Liste stehen sollen.", "", None, "18:38"),
    ], ("user", "Dann nimm es bitte auf.", "", None, "18:39")


def english_backend(tl):
    """StubBackend mit Zustand und Modellknopf aus dem Wörterbuch, wie das echte
    Backend in englischer Sitzung (Texte vom Backend kommen schon übersetzt)."""
    from PySide6.QtCore import Property
    states = {"off": "Hermes ist aus", "nokey": "Hermes läuft, aber der Schlüssel für das Leisten-Symbol fehlt",
              "ready": "Hermes ist bereit", "busy": "Hermes arbeitet", "asking": "Hermes fragt nach einer Freigabe"}
    efforts = {"": "Vorgabe", "low": "wenig", "medium": "mittel", "high": "gründlich"}

    class EnglishBackend(tgc.StubBackend):
        @Property(str, notify=tgc.StubBackend.stateChanged)
        def stateText(self):
            return tl._(states.get(self._state, self._state))

        @Property(str, notify=tgc.StubBackend.modelChanged)
        def modelText(self):
            label = next((o["label"] for o in self._choice_options if o["id"] == self._choice_model), self._choice_model)
            return f"{label} · {tl._(efforts.get(self._choice_effort, 'Vorgabe'))}"

        @Property("QVariantList", notify=tgc.StubBackend.modelChanged)
        def effortOptions(self):
            return [{"value": v, "label": tl._(label), "checked": v == self._choice_effort} for v, label in efforts.items()]

    return EnglishBackend()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qml-dir", default=os.environ.get("HERMES_OS_TRAY_DIR", "/usr/share/hermes-os/tray"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", default="")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--lang", choices=("de", "en"), default="de",
                    help="en: englische Oberfläche und ein englisches Gespräch")
    args = ap.parse_args()
    os.environ["HERMES_OS_LANG"] = args.lang
    os.makedirs(args.out, exist_ok=True)

    tgc.use_tray_dir(args.qml_dir)
    QQuickStyle.setStyle("org.kde.desktop")
    app = QGuiApplication(sys.argv)
    # Offscreen lädt Qt kein Symbol-Thema; ohne Breeze fehlten alle Symbole im Bild
    QIcon.setThemeName("breeze-dark")
    QIcon.setFallbackThemeName("breeze")
    translator = None
    if args.lang == "en":
        # Wie hermes-os-tray in englischer Sitzung: Übersetzer vor dem Laden von Main.qml
        spec_lang = importlib.util.spec_from_file_location("tray_lang_showcase", os.path.join(args.qml_dir, "lang.py"))
        tl = importlib.util.module_from_spec(spec_lang)
        spec_lang.loader.exec_module(tl)
        translator = tl.DictTranslator(app)
        app.installTranslator(translator)
        backend = english_backend(tl)
    else:
        backend = tgc.StubBackend()
    voice, look = tgc.StubVoice(), tgc.StubLook()
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

    def grab(name, sizes):
        for label, (w, h) in sizes:
            root.setWidth(w)
            root.setHeight(h)
            settle(900)
            lv = root.findChild(object, "messageList")
            if lv is not None:
                lv.positionViewAtEnd() if hasattr(lv, "positionViewAtEnd") else None
            settle(400)
            path = os.path.join(args.out, f"{args.prefix}{name}{label}.png")
            root.grabWindow().save(path)
            print(path)

    wide, narrow = ("breit", (1180, 780)), ("schmal", (560, 780))

    # Leerer Verlauf: Begrüßung und Vorschläge
    backend.set_state("ready", configured=True)
    grab("begruessung-", (narrow,))

    m = backend._model
    rows, last = conversation(args.lang, url)
    for role, text, meta, images, when in rows:
        m.append(role, text, meta=meta, images=images, when=when)
    grab("", (wide, narrow))

    # Hermes arbeitet: tippende Punkte am Ende
    role, text, meta, images, when = last
    m.append(role, text, meta=meta, images=images, when=when)
    backend.set_busy(True)
    backend.set_state("busy")
    backend.set_waiting(True)
    grab("tippen-", (narrow,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
