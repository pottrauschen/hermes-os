#!/usr/bin/python3
# =============================================================================
# hermes-os -- Fenster des Leisten-Symbols offscreen rendern (ohne Display,
# ohne Gateway)
# =============================================================================
# Lädt tray/Main.qml mit einem Stub statt des echten Backends und spielt die
# Zustände durch: Gateway aus, bereit, Nachricht senden, Streaming, Freigabe
# mit Knöpfen, Schlüssel fehlt. Jede QML-Warnung ist ein Fehler, damit ein
# kaputtes Binding oder ein umbenanntes Kirigami-Element schon im Image-Build
# auffällt.
#
# Aufruf:
#   tests/tray-gui-check.py [--qml-dir DIR] [--out DIR]
# Exit 0 = alles sauber. Läuft überall, wo PySide6 und Kirigami liegen: im
# Image-Build (80-validate.sh, 7d), in der Test-VM, auf einem Aurora-Desktop.
# =============================================================================
import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

from PySide6.QtCore import (QAbstractListModel, QByteArray, QDeadlineTimer, QMetaObject, QModelIndex,
                            QObject, Qt, Property, Signal, Slot, qInstallMessageHandler, QtMsgType)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

# Harmloses Rauschen ohne Display; alles andere zählt.
IGNORE = ("MESA-EGL", "egl: failed", "Could not register app ID", "QXcbConnection", "dri2 screen", "portal")


class StubModel(QAbstractListModel):
    """Dieselben Rollen wie MessageModel in hermes-os-tray."""
    _USER = int(Qt.ItemDataRole.UserRole)
    RoleRole, TextRole, MetaRole = _USER + 1, _USER + 2, _USER + 3

    def __init__(self):
        super().__init__()
        self._rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        return {self.RoleRole: row["role"], self.TextRole: row["text"], self.MetaRole: row["meta"]}.get(int(role))

    def roleNames(self):
        return {self.RoleRole: QByteArray(b"role"), self.TextRole: QByteArray(b"text"),
                self.MetaRole: QByteArray(b"meta")}

    def append(self, role, text, meta=""):
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self._rows.append({"role": role, "text": text, "meta": meta})
        self.endInsertRows()
        return n

    def set_text(self, row, text):
        self._rows[row]["text"] = text
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.TextRole])

    def clear(self):
        self.beginResetModel()
        self._rows = []
        self.endResetModel()


class StubBackend(QObject):
    """Dieselbe Schnittstelle wie Backend in hermes-os-tray, ohne Gateway."""
    stateChanged = Signal()
    approvalChanged = Signal()
    busyChanged = Signal()
    versionChanged = Signal()
    showRequested = Signal()
    hideRequested = Signal()

    def __init__(self):
        super().__init__()
        self._state = "off"
        self._busy = False
        self._approval = {}
        self._configured = False
        self._model = StubModel()
        self.calls = []

    # Steuerung durch den Test
    def set_state(self, state, configured=None):
        self._state = state
        if configured is not None:
            self._configured = configured
        self.stateChanged.emit()

    def set_busy(self, value):
        self._busy = value
        self.busyChanged.emit()

    def set_approval(self, approval):
        self._approval = dict(approval or {})
        self.approvalChanged.emit()

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Property(str, notify=stateChanged)
    def stateText(self):
        return {"off": "Hermes ist aus", "nokey": "Schlüssel fehlt", "ready": "Hermes ist bereit",
                "busy": "Hermes arbeitet", "asking": "Hermes fragt"}.get(self._state, self._state)

    @Property(str, notify=stateChanged)
    def stateIcon(self):
        return "hermes-os-tray-" + ("off" if self._state == "nokey" else self._state)

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(bool, notify=approvalChanged)
    def approvalPending(self):
        return bool(self._approval)

    @Property("QVariantMap", notify=approvalChanged)
    def approval(self):
        return dict(self._approval)

    @Property(QObject, constant=True)
    def messages(self):
        return self._model

    @Property(str, notify=versionChanged)
    def hermesVersion(self):
        return "Hermes Agent (Stub)"

    @Property(bool, constant=True)
    def dashboardAvailable(self):
        return False

    @Property(bool, notify=stateChanged)
    def configured(self):
        return self._configured

    @Property(str, notify=stateChanged)
    def sessionId(self):
        return "hermes-os-tray"

    @Slot(str)
    def send(self, text):
        self.calls.append(("send", text))

    @Slot()
    def stopRun(self):
        self.calls.append(("stop",))

    @Slot(str)
    def approve(self, choice):
        self.calls.append(("approve", choice))

    @Slot()
    def openSetup(self):
        self.calls.append(("setup",))

    @Slot()
    def openDashboard(self):
        self.calls.append(("dashboard",))

    @Slot()
    def startGateway(self):
        self.calls.append(("gateway",))

    @Slot()
    def openTerminalChat(self):
        self.calls.append(("terminal",))

    @Slot()
    def newConversation(self):
        self.calls.append(("new",))
        self._model.clear()

    @Slot()
    def hideWindow(self):
        self.calls.append(("hide",))

    @Slot()
    def showWindow(self):
        self.calls.append(("show",))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qml-dir", default=os.environ.get("HERMES_OS_TRAY_DIR", "/usr/share/hermes-os/tray"))
    ap.add_argument("--out", default="", help="PNG je Schritt hierhin (optional)")
    args = ap.parse_args()
    main_qml = os.path.join(args.qml_dir, "Main.qml")
    if not os.path.isfile(main_qml):
        print(f"FEHL  {main_qml} fehlt")
        return 1

    warnings = []

    def handler(mode, ctx, msg):
        if any(s in msg for s in IGNORE):
            return
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
        deadline = QDeadlineTimer(ms)
        while not deadline.hasExpired():
            app.processEvents()
            app.sendPostedEvents()

    def shot(name):
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            root.grabWindow().save(os.path.join(args.out, f"tray-{name}.png"))

    def child(name):
        return root.findChild(QObject, name)

    def step(label, ok, detail=""):
        nonlocal fail
        new = warnings[step.mark:]
        step.mark = len(warnings)
        if ok and not new:
            print(f"OK    {label}")
        else:
            fail = 1
            print(f"FEHL  {label}" + (f": {detail}" if detail else ""))
            for w in new:
                print(f"      {w}")
    step.mark = 0

    # 1. Gateway aus, nichts eingerichtet: Hinweis mit "Hermes einrichten"
    settle()
    off_box, setup_act, gw_act = child("offBox"), child("setupAction"), child("gatewayAction")
    shot("off")
    step("Gateway aus: Hinweis und Einrichten-Knopf sichtbar",
         off_box is not None and off_box.property("visible") and setup_act is not None
         and setup_act.property("visible") and gw_act is not None and not gw_act.property("visible"),
         f"offBox={off_box and off_box.property('visible')} setup={setup_act and setup_act.property('visible')}")
    if setup_act is not None:
        QMetaObject.invokeMethod(setup_act, "trigger")
        settle(100)
    step("Einrichten-Knopf ruft backend.openSetup", ("setup",) in backend.calls, str(backend.calls))

    # 2. Bereit: Hinweis weg, Textfeld an, Senden nur mit Text
    backend.set_state("ready", configured=True)
    settle()
    inp, send_btn = child("inputField"), child("sendButton")
    shot("ready-empty")
    step("Bereit: Hinweis verschwindet, Textfeld aktiv, Senden ohne Text aus",
         off_box is not None and not off_box.property("visible") and inp is not None and inp.property("enabled")
         and send_btn is not None and not send_btn.property("enabled"),
         f"offBox={off_box and off_box.property('visible')} input={inp and inp.property('enabled')} "
         f"send={send_btn and send_btn.property('enabled')}")

    # 3. Nachricht senden: Textfeld leert sich, backend.send bekommt den Text
    root.typeInput("  Welches Image ist gebootet?  ")
    settle(100)
    send_enabled = send_btn is not None and send_btn.property("enabled")
    sent = root.sendCurrent()
    settle(100)
    step("Senden: Knopf an bei Text, backend.send bekommt den getrimmten Text, Feld leer",
         send_enabled and sent and ("send", "Welches Image ist gebootet?") in backend.calls
         and inp is not None and inp.property("text") == "",
         f"enabled={send_enabled} sent={sent} calls={backend.calls} text={inp and inp.property('text')!r}")

    # 4. Streaming: Zeilen im Verlauf, Stopp-Knopf während busy
    backend._model.append("user", "Welches Image ist gebootet?")
    row = backend._model.append("assistant", "")
    backend.set_busy(True)
    backend.set_state("busy")
    settle()
    busy_stop = send_btn is not None and send_btn.property("text") == "Stopp" and send_btn.property("enabled")
    backend._model.append("tool", "os_status", "started")
    backend._model.set_text(row, "Gebootet ist **hermes-os** `44.20260926`.")
    backend._model.append("tool", "os_status fertig (0.3 s)", "completed")
    settle()
    lv = child("messageList")
    shot("streaming")
    step("Streaming: Stopp-Knopf während der Arbeit, vier Zeilen im Verlauf",
         busy_stop and lv is not None and lv.property("count") == 4 and lv.property("contentHeight") > 0,
         f"stop={busy_stop} count={lv and lv.property('count')} h={lv and lv.property('contentHeight')}")

    # 5. Freigabe: Kasten mit den erlaubten Knöpfen, Klick ruft backend.approve
    backend.set_approval({"request_id": "req-1", "command": "sudo bootc upgrade --check",
                          "description": "Befehl berührt das laufende System",
                          "choices": ["once", "session", "deny"]})
    backend.set_state("asking")
    settle()
    box = child("approvalBox")
    once, sess, always, deny = child("approveOnce"), child("approveSession"), child("approveAlways"), child("approveDeny")
    shot("approval")
    visible_ok = box is not None and box.property("visible") and once is not None and once.property("visible") \
        and sess is not None and sess.property("visible") and always is not None and not always.property("visible") \
        and deny is not None and deny.property("visible")
    text_ok = box is not None and "sudo bootc upgrade --check" in str(box.property("text"))
    if once is not None:
        QMetaObject.invokeMethod(once, "trigger")
        settle(100)
    step("Freigabe: Kasten mit Befehl, Immer-Knopf versteckt, Einmal ruft backend.approve('once')",
         visible_ok and text_ok and ("approve", "once") in backend.calls,
         f"visible={visible_ok} text={text_ok} calls={backend.calls}")
    backend.set_approval({})
    backend.set_busy(False)
    backend.set_state("ready")
    settle()
    step("Freigabe beantwortet: Kasten verschwindet, Senden-Knopf zurück",
         box is not None and not box.property("visible") and send_btn is not None
         and send_btn.property("text") == "Senden",
         f"visible={box and box.property('visible')} btn={send_btn and send_btn.property('text')}")

    # 6. Schlüssel fehlt: Hinweis mit "Gateway starten"
    backend.set_state("nokey", configured=True)
    settle()
    shot("nokey")
    if gw_act is not None:
        QMetaObject.invokeMethod(gw_act, "trigger")
        settle(100)
    step("Schlüssel fehlt: Hinweis mit Gateway-Knopf, Klick ruft backend.startGateway",
         off_box is not None and off_box.property("visible") and gw_act is not None and gw_act.property("visible")
         and setup_act is not None and not setup_act.property("visible") and ("gateway",) in backend.calls,
         f"offBox={off_box and off_box.property('visible')} gw={gw_act and gw_act.property('visible')} "
         f"calls={backend.calls}")

    # 7. Neues Gespräch leert die Liste
    backend.set_state("ready", configured=True)
    settle()
    backend.newConversation()
    settle()
    step("Neues Gespräch: Verlauf leer, Platzhalter darf ohne Warnung erscheinen",
         lv is not None and lv.property("count") == 0, f"count={lv and lv.property('count')}")

    root.close()
    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
