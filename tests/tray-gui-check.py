#!/usr/bin/python3
# =============================================================================
# hermes-os -- Fenster des Leisten-Symbols offscreen rendern (ohne Display,
# ohne Gateway)
# =============================================================================
# Lädt tray/Main.qml mit einem Stub statt des echten Backends und spielt die
# Zustände durch: Gateway aus, bereit, Nachricht senden, Bilder anhängen und
# entfernen, Streaming mit Bildern in den Blasen, Freigabe mit Knöpfen,
# Schlüssel fehlt, Bibliothek (Einträge, Ablegen, Spiegeln mit Fortschritt, Suche
# mit Trefferliste, Notiz ändern, Schalter der Doku-Server), Protokoll mit Filtern
# und Export, Sprachzustand und Bildschirmausschnitt (Stubs für `voice` und
# `look`). Jede QML-Warnung ist ein Fehler, damit ein kaputtes Binding oder ein
# umbenanntes Kirigami-Element schon im Image-Build auffällt.
#
# Aufruf:
#   tests/tray-gui-check.py [--qml-dir DIR] [--out DIR]
# Exit 0 = alles sauber. Läuft überall, wo PySide6 und Kirigami liegen: im
# Image-Build (80-validate.sh, 7d), in der Test-VM, auf einem Aurora-Desktop.
# =============================================================================
import argparse
import datetime
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

from PySide6.QtCore import (QAbstractListModel, QByteArray, QDeadlineTimer, QMetaObject, QModelIndex,
                            QObject, QUrl, Qt, Property, Signal, Slot, qInstallMessageHandler, QtMsgType)
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

# Harmloses Rauschen ohne Display; alles andere zählt.
IGNORE = ("MESA-EGL", "egl: failed", "Could not register app ID", "QXcbConnection", "dri2 screen", "portal")

# tray/chat_text.py aus dem geprüften Ordner: der Stub setzt Antworten damit wie
# das echte Backend (use_tray_dir, auch aus tests/tray-showcase.py)
CHAT_TEXT = None


def use_tray_dir(path):
    global CHAT_TEXT
    import importlib.util
    spec = importlib.util.spec_from_file_location("chat_text_under_test", os.path.join(path, "chat_text.py"))
    CHAT_TEXT = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CHAT_TEXT)


class StubModel(QAbstractListModel):
    """Dieselben Rollen wie MessageModel in hermes-os-tray."""
    _USER = int(Qt.ItemDataRole.UserRole)
    RoleRole, TextRole, MetaRole, ImagesRole, TimeRole = _USER + 1, _USER + 2, _USER + 3, _USER + 4, _USER + 5

    def __init__(self):
        super().__init__()
        self._rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        return {self.RoleRole: row["role"], self.TextRole: row["text"], self.MetaRole: row["meta"],
                self.ImagesRole: list(row["images"]), self.TimeRole: row["time"]}.get(int(role))

    def roleNames(self):
        return {self.RoleRole: QByteArray(b"role"), self.TextRole: QByteArray(b"text"),
                self.MetaRole: QByteArray(b"meta"), self.ImagesRole: QByteArray(b"images"),
                self.TimeRole: QByteArray(b"time")}

    def append(self, role, text, meta="", images=None, when=""):
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self._rows.append({"role": role, "text": text, "meta": meta, "images": list(images or []), "time": when})
        self.endInsertRows()
        return n

    def set_text(self, row, text, meta=None):
        self._rows[row]["text"] = text
        if meta is not None:
            self._rows[row]["meta"] = meta
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.TextRole, self.MetaRole])

    def set_images(self, row, images):
        self._rows[row]["images"] = list(images or [])
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.ImagesRole])

    def clear(self):
        self.beginResetModel()
        self._rows = []
        self.endResetModel()


class StubAuditModel(QAbstractListModel):
    """Dieselben Rollen wie AuditModel in hermes-os-tray."""
    FIELDS = ("rowId", "date", "time", "kind", "command", "groupLabel", "decisionLabel", "decider",
              "status", "resultText", "output", "changed")
    _USER = int(Qt.ItemDataRole.UserRole)

    def __init__(self):
        super().__init__()
        self._rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=int(Qt.ItemDataRole.DisplayRole)):
        i = int(role) - self._USER - 1
        if not index.isValid() or not 0 <= i < len(self.FIELDS):
            return None
        return self._rows[index.row()][self.FIELDS[i]]

    def roleNames(self):
        return {self._USER + 1 + i: QByteArray(f.encode("ascii")) for i, f in enumerate(self.FIELDS)}

    def replace(self, rows):
        self.beginResetModel()
        self._rows = [dict(r) for r in rows]
        self.endResetModel()


def audit_row(row_id, status, command, changed, output="", date=""):
    return {"rowId": row_id, "date": date or datetime.date.today().strftime("%d.%m.%Y"), "time": "14:03:12",
            "kind": "app" if status == "launched" else "command", "command": command,
            "groupLabel": "Systemdienste", "decisionLabel": "Einmal erlaubt" if changed else "Abgelehnt",
            "decider": "Nutzer im Leisten-Symbol", "status": status,
            "resultText": "Ausgeführt, Exit 0" if changed else "Nicht ausgeführt", "output": output,
            "changed": changed}


AUDIT_ROWS = [
    audit_row("c:1", "ok", "sudo systemctl restart sshd", True, "Job for sshd.service finished.\nok"),
    audit_row("c:2", "denied", "rm -rf /etc/foo", False),
    audit_row("c:3", "error", "sudo systemctl restart foo", True, "Unit foo.service not found.", date="01.01.2026"),
    audit_row("c:4", "launched", "org.mozilla.firefox", False),
    audit_row("c:5", "pending", "sudo bootc upgrade", False),
]


class StubBackend(QObject):
    """Dieselbe Schnittstelle wie Backend in hermes-os-tray, ohne Gateway."""
    stateChanged = Signal()
    approvalChanged = Signal()
    busyChanged = Signal()
    waitingChanged = Signal()
    versionChanged = Signal()
    showRequested = Signal()
    hideRequested = Signal()
    attachmentsChanged = Signal()
    libraryChanged = Signal()
    showLibraryRequested = Signal()
    libraryMirrorChanged = Signal()
    librarySearchChanged = Signal()
    libraryMcpChanged = Signal()
    auditChanged = Signal()
    showAuditRequested = Signal()
    modelChanged = Signal()

    def __init__(self):
        super().__init__()
        self._state = "off"
        self._busy = False
        self._waiting = False
        self._approval = {}
        self._configured = False
        self._attachments = []
        self._library = []
        self._mirrors = {}
        self._search_hits = []
        self._search_note = ""
        self._searching = False
        self._mcp = [{"id": "context7", "title": "Context7", "url": "https://mcp.context7.com/mcp",
                      "description": "Doku zu Bibliotheken", "enabled": False},
                     {"id": "deepwiki", "title": "DeepWiki", "url": "https://mcp.deepwiki.com/mcp",
                      "description": "Fragen zu GitHub-Projekten", "enabled": True}]
        self._mcp_message = ""
        self._model = StubModel()
        self._audit = StubAuditModel()
        self._audit_rows = []
        self._audit_period = "today"
        self._audit_changes = False
        self.audit_source = list(AUDIT_ROWS)
        # Modell und Denkaufwand wie model_choice.py: ein Endpunkt auf diesem Rechner mit Liste
        self._choice_model = "claude-sonnet-5"
        self._choice_effort = ""
        self._choice_options = [{"id": "claude-sonnet-5", "label": "Sonnet 5"},
                                {"id": "claude-opus-5-5", "label": "Opus 5.5"}]
        self.calls = []

    # Modell und Denkaufwand wie im echten Backend
    @Property(bool, notify=modelChanged)
    def modelAvailable(self):
        return True

    @Property(str, notify=modelChanged)
    def modelText(self):
        label = next((o["label"] for o in self._choice_options if o["id"] == self._choice_model), self._choice_model)
        effort = {"": "Vorgabe", "low": "wenig", "medium": "mittel", "high": "gründlich"}.get(self._choice_effort, "?")
        return f"{label} · {effort}"

    @Property(bool, notify=modelChanged)
    def modelSwitchable(self):
        return bool(self._choice_options)

    @Property("QVariantList", notify=modelChanged)
    def modelOptions(self):
        return [dict(o, checked=o["id"] == self._choice_model) for o in self._choice_options]

    @Property("QVariantList", notify=modelChanged)
    def effortOptions(self):
        return [{"value": v, "label": label, "checked": v == self._choice_effort}
                for v, label in (("", "Vorgabe"), ("low", "wenig"), ("medium", "mittel"), ("high", "gründlich"))]

    @Slot()
    def refreshModels(self):
        self.calls.append(("refreshModels",))

    @Slot(str)
    def setModel(self, model):
        self.calls.append(("setModel", model))
        self._choice_model = model
        self.modelChanged.emit()

    @Slot(str)
    def setEffort(self, effort):
        self.calls.append(("setEffort", effort))
        self._choice_effort = effort
        self.modelChanged.emit()

    # Protokoll wie im echten Backend: Model, Filter, Export
    @Property(bool, constant=True)
    def auditAvailable(self):
        return True

    @Property(QObject, constant=True)
    def auditModel(self):
        return self._audit

    @Property(int, notify=auditChanged)
    def auditCount(self):
        return len(self._audit_rows)

    @Property(str, notify=auditChanged)
    def auditPeriod(self):
        return self._audit_period

    @Property(bool, notify=auditChanged)
    def auditChangesOnly(self):
        return self._audit_changes

    @Property(str, constant=True)
    def auditPath(self):
        return "/tmp/audit.jsonl"

    @Slot(bool)
    def auditSetActive(self, active):
        self.calls.append(("auditactive", bool(active)))

    @Slot()
    def auditReload(self):
        self.calls.append(("auditreload",))
        rows = [r for r in self.audit_source if r["changed"] or not self._audit_changes]
        if self._audit_period == "today":
            rows = [r for r in rows if r["date"] == datetime.date.today().strftime("%d.%m.%Y")]
        self._audit_rows = rows
        self._audit.replace(rows)
        self.auditChanged.emit()

    @Slot(str, bool)
    def auditSetFilter(self, period, changes_only):
        self.calls.append(("auditfilter", period, bool(changes_only)))
        self._audit_period = period
        self._audit_changes = bool(changes_only)
        self.auditReload()

    @Slot(result=str)
    def auditExport(self):
        self.calls.append(("auditexport",))
        return "Gespeichert: /tmp/hermes-protokoll.txt"

    @Slot()
    def showAudit(self):
        self.calls.append(("auditshow",))
        self.showAuditRequested.emit()

    # Bibliothek wie im echten Backend: Liste von {"id", "kind", "source", "title", "note", "added"}
    @Property(bool, constant=True)
    def libraryAvailable(self):
        return True

    @Property("QVariantList", notify=libraryChanged)
    def library(self):
        return [dict(e) for e in self._library]

    @Property(int, notify=libraryChanged)
    def libraryCount(self):
        return len(self._library)

    @Slot()
    def libraryReload(self):
        self.calls.append(("libreload",))
        self.libraryChanged.emit()

    @Slot(str, str, str, result=str)
    def libraryAdd(self, source, title, note):
        self.calls.append(("libadd", source, title, note))
        if source == "kaputt":
            return "Weder eine http(s)-Adresse noch eine vorhandene Datei oder ein Ordner: kaputt"
        kind = "url" if source.startswith("http") else "file"
        self._library.append({"id": f"e{len(self._library) + 1}", "kind": kind, "source": source,
                              "title": title or source, "note": note, "added": ""})
        self.libraryChanged.emit()
        return ""

    @Slot(str)
    def libraryRemove(self, entry_id):
        self.calls.append(("libremove", entry_id))
        self._library = [e for e in self._library if e["id"] != entry_id]
        self.libraryChanged.emit()

    @Slot(result=str)
    def libraryPickFile(self):
        self.calls.append(("libfile",))
        return ""

    @Slot(result=str)
    def libraryPickFolder(self):
        self.calls.append(("libfolder",))
        return ""

    @Slot(str)
    def libraryOpen(self, entry_id):
        self.calls.append(("libopen", entry_id))

    @Slot()
    def showLibrary(self):
        self.calls.append(("libshow",))
        self.showLibraryRequested.emit()

    # Stufe zwei wie im echten Backend: Spiegel, Suche, Ablegen, Notiz, Doku-Server
    @Property("QVariantMap", notify=libraryMirrorChanged)
    def libraryMirror(self):
        return {k: dict(v) for k, v in self._mirrors.items()}

    @Property(bool, notify=libraryMirrorChanged)
    def libraryMirrorRunning(self):
        return any(v.get("running") for v in self._mirrors.values())

    @Slot(str)
    def libraryMirrorStart(self, entry_id):
        self.calls.append(("libmirror", entry_id))
        self._mirrors[entry_id] = {"status": "running", "pages": 1, "running": True, "errorCount": 0,
                                   "current": "https://docs.kde.org/a.html", "text": "Spiegel läuft: 1 Seite bisher. https://docs.kde.org/a.html"}
        self.libraryMirrorChanged.emit()

    @Slot(str)
    def libraryMirrorCancel(self, entry_id):
        self.calls.append(("libmirrorcancel", entry_id))

    def finish_mirror(self, entry_id):
        self._mirrors[entry_id] = {"status": "done", "pages": 5, "running": False, "errorCount": 1,
                                   "current": "", "text": "Spiegel: 5 Seiten, Stand 26.09.2026 14:02, 1 Fehler."}
        self.libraryMirrorChanged.emit()

    @Property("QVariantList", notify=librarySearchChanged)
    def librarySearchHits(self):
        return [dict(h) for h in self._search_hits]

    @Property(str, notify=librarySearchChanged)
    def librarySearchNote(self):
        return self._search_note

    @Property(bool, notify=librarySearchChanged)
    def librarySearching(self):
        return self._searching

    @Slot(str)
    def librarySearch(self, query):
        self.calls.append(("libsearch", query))
        if query == "":
            self._search_hits, self._search_note = [], ""
        else:
            self._search_hits = [{"title": "Versteckte Dateien", "source": "https://docs.kde.org/b.html", "entryId": "e1",
                                  "entryTitle": "KDE-Handbücher", "snippet": "Mit Alt+Punkt zeigt Dolphin [versteckte] Dateien."},
                                 {"title": "Notiz", "source": "/home/tina/notiz.txt", "entryId": "e2",
                                  "entryTitle": "Unterlagen", "snippet": "…[versteckte] Einstellungen…"}]
            self._search_note = f"2 Treffer für „{query}“."
        self.librarySearchChanged.emit()

    @Slot(str, str, str, result=str)
    def libraryUpdate(self, entry_id, title, note):
        self.calls.append(("libupdate", entry_id, title, note))
        for e in self._library:
            if e["id"] == entry_id:
                e["title"], e["note"] = title or e["title"], note
        self.libraryChanged.emit()
        return ""

    @Slot(list, str, result=str)
    def libraryDrop(self, urls, text):
        sources = [u.toString() if hasattr(u, "toString") else str(u) for u in urls]
        self.calls.append(("libdrop", sources, text))
        for src in sources:
            self._library.append({"id": f"e{len(self._library) + 1}", "kind": "url" if src.startswith("http") else "file",
                                  "source": src, "title": src, "note": "", "added": ""})
        self.libraryChanged.emit()
        return "Eingetragen: " + ", ".join(sources)

    @Slot(str)
    def libraryOpenSource(self, source):
        self.calls.append(("libopensource", source))

    @Property("QVariantList", notify=libraryMcpChanged)
    def libraryMcp(self):
        return [dict(m) for m in self._mcp]

    @Property(str, notify=libraryMcpChanged)
    def libraryMcpMessage(self):
        return self._mcp_message

    @Slot(str, bool, result=str)
    def libraryMcpSet(self, server_id, enabled):
        self.calls.append(("mcpset", server_id, bool(enabled)))
        for m in self._mcp:
            if m["id"] == server_id:
                m["enabled"] = bool(enabled)
        self._mcp_message = f"{server_id} {'eingetragen' if enabled else 'ausgetragen'}. Das Gateway übernimmt das von selbst."
        self.libraryMcpChanged.emit()
        return self._mcp_message

    # Steuerung durch den Test
    def set_state(self, state, configured=None):
        self._state = state
        if configured is not None:
            self._configured = configured
        self.stateChanged.emit()

    def set_busy(self, value):
        self._busy = value
        self.busyChanged.emit()

    def set_waiting(self, value):
        self._waiting = value
        self.waitingChanged.emit()

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

    @Property(bool, notify=waitingChanged)
    def waiting(self):
        return self._waiting

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

    # Anhänge wie im echten Backend: Liste von {"path", "url", "name"}
    @Property("QVariantList", notify=attachmentsChanged)
    def attachments(self):
        return [dict(a) for a in self._attachments]

    @Property(int, notify=attachmentsChanged)
    def attachmentCount(self):
        return len(self._attachments)

    @Slot(list)
    def attachFiles(self, urls):
        for value in urls or []:
            if isinstance(value, QUrl):
                path = value.toLocalFile()
            elif str(value).startswith("file:"):
                path = QUrl(str(value)).toLocalFile()
            else:
                path = str(value)
            self.calls.append(("attach", os.path.basename(path)))
            self._attachments.append({"path": path, "url": QUrl.fromLocalFile(path).toString(),
                                      "name": os.path.basename(path)})
        self.attachmentsChanged.emit()

    @Slot()
    def attachFromDialog(self):
        self.calls.append(("dialog",))

    @Slot(result=bool)
    def pasteImage(self):
        self.calls.append(("paste",))
        return False

    @Slot(int)
    def removeAttachment(self, index):
        self.calls.append(("remove", index))
        if 0 <= index < len(self._attachments):
            del self._attachments[index]
            self.attachmentsChanged.emit()

    @Slot()
    def clearAttachments(self):
        self._attachments = []
        self.attachmentsChanged.emit()

    @Slot(str)
    def openImage(self, url):
        self.calls.append(("open", url))

    @Slot(str, float, result=str)
    def chatHtml(self, text, point_size):
        return CHAT_TEXT.to_html(text, point_size) if CHAT_TEXT is not None and text else ""

    @Slot(str)
    def send(self, text):
        self.calls.append(("send", text))
        self.clearAttachments()

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


class StubVoice(QObject):
    """Dieselbe Schnittstelle wie VoiceBackend in tray/voice.py, ohne Mikrofon."""
    stateChanged = Signal()

    def __init__(self):
        super().__init__()
        self._state = "idle"
        self.calls = []

    def set_state(self, state):
        self._state = state
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Property(str, notify=stateChanged)
    def stateText(self):
        return {"recording": "Hermes hört zu …", "transcribing": "Hermes versteht …",
                "asking": "Hermes denkt nach …", "speaking": "Hermes spricht …"}.get(self._state, "")

    @Property(str, notify=stateChanged)
    def iconName(self):
        return {"recording": "hermes-os-tray-listening", "speaking": "hermes-os-tray-speaking"}.get(self._state, "")

    @Property(bool, constant=True)
    def available(self):
        return True

    @Property(str, constant=True)
    def unavailableReason(self):
        return ""

    @Property(str, notify=stateChanged)
    def shortcutText(self):
        return "Meta+Space"

    @Slot()
    def toggle(self):
        self.calls.append(("toggle",))

    @Slot()
    def cancel(self):
        self.calls.append(("cancel",))


class StubLook(QObject):
    """Dieselbe Schnittstelle wie LookBackend in tray/screenshot.py, ohne Spectacle."""
    busyChanged = Signal()

    def __init__(self):
        super().__init__()
        self.calls = []

    @Property(bool, constant=True)
    def available(self):
        return True

    @Property(bool, notify=busyChanged)
    def busy(self):
        return False

    @Property(str, constant=True)
    def shortcutText(self):
        return "Meta+Shift+H"

    @Slot()
    def capture(self):
        self.calls.append(("capture",))


def make_pictures(folder):
    """Zwei kleine PNGs als Anhänge und Bilder im Verlauf."""
    paths = []
    for i, (w, h, color) in enumerate(((96, 64, "#3daee9"), (48, 80, "#f67400"))):
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor(color))
        path = os.path.join(folder, f"bild{i}.png")
        img.save(path)
        paths.append(path)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qml-dir", default=os.environ.get("HERMES_OS_TRAY_DIR", "/usr/share/hermes-os/tray"))
    ap.add_argument("--out", default="", help="PNG je Schritt hierhin (optional)")
    args = ap.parse_args()
    main_qml = os.path.join(args.qml_dir, "Main.qml")
    if not os.path.isfile(main_qml):
        print(f"FEHL  {main_qml} fehlt")
        return 1
    use_tray_dir(args.qml_dir)

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
    voice = StubVoice()
    look = StubLook()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("voice", voice)
    engine.rootContext().setContextProperty("look", look)
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

    def count(name):
        # Delegates aus Repeater und ListView findet nur die QML-Seite (root.countNamed);
        # PySide verlangt beide Parameter, None steht für den Fensterinhalt
        return int(root.countNamed(name, None))

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

    # 2. Bereit: Hinweis weg, Textfeld an, Senden nur mit Text oder Bild
    backend.set_state("ready", configured=True)
    settle()
    inp, send_btn, attach_btn = child("inputField"), child("sendButton"), child("attachButton")
    shot("ready-empty")
    # Das leere Feld muss gleich nach dem Start eine Zeile hoch sein (VM 112: Höhe 0 bis zum ersten Text)
    inp_h = float(inp.property("height") or 0) if inp is not None else 0.0
    step("Bereit: Hinweis verschwindet, Textfeld sichtbar und aktiv, Anhängen aktiv, Senden ohne Text aus",
         off_box is not None and not off_box.property("visible") and inp is not None and inp.property("enabled")
         and inp_h >= 12
         and attach_btn is not None and attach_btn.property("enabled")
         and send_btn is not None and not send_btn.property("enabled"),
         f"offBox={off_box and off_box.property('visible')} input={inp and inp.property('enabled')} h={inp_h:.0f} "
         f"attach={attach_btn and attach_btn.property('enabled')} send={send_btn and send_btn.property('enabled')}")

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

    # 3b. Modell und Denkaufwand: Knopf mit Stand, Auswahl öffnet sich, Klick stellt um
    model_btn, popup = child("modelButton"), child("choicePopup")
    btn_text = str(model_btn.property("text")) if model_btn is not None else ""
    if model_btn is not None:
        QMetaObject.invokeMethod(model_btn, "clicked")
        settle(300)
    opened = popup is not None and popup.property("visible")
    # Popups hängen auf der Overlay-Ebene, nicht unter root.contentItem: im Popup suchen
    content = popup.property("contentItem") if popup is not None else None
    options = int(root.countNamed("modelOption", content)) if content is not None else 0
    efforts = int(root.countNamed("effortOption", content)) if content is not None else 0
    # je Teil genau ein Punkt: Sonnet 5 bei den Modellen, Vorgabe beim Denkaufwand
    checked = str(root.checkedNames(content)) if content is not None else ""
    shot("model-choice")
    first = root.findNamed("modelOption", content) if opened and content is not None else None
    picked = first is not None
    if picked:
        QMetaObject.invokeMethod(first, "clicked")
    settle(600)
    # opened springt mit close() um, visible erst nach der Ausblend-Animation
    closed = popup is not None and not popup.property("opened")
    step("Modellwahl: Knopf zeigt Modell und Denkaufwand, Auswahl mit Modellen und Stufen, Klick ruft setModel",
         model_btn is not None and model_btn.property("visible") and btn_text.startswith("Sonnet 5 · Vorgabe")
         and opened and options == 2 and efforts == 4 and ("refreshModels",) in backend.calls
         and checked == "modelOption:Sonnet 5|effortOption:Vorgabe"
         and picked and closed and any(c[0] == "setModel" for c in backend.calls),
         f"text={btn_text!r} opened={opened} closed={closed} options={options} efforts={efforts} checked={checked!r} "
         f"calls={backend.calls[-4:]}")
    if popup is not None and popup.property("visible"):
        QMetaObject.invokeMethod(popup, "close")
        settle(100)

    # 4. Bilder anhängen: Streifen mit Vorschauen, Senden auch ohne Text, Entfernen,
    #    Senden räumt den Streifen weg
    folder = tempfile.mkdtemp(prefix="hermes-tray-")
    pics = make_pictures(folder)
    backend.attachFiles([QUrl.fromLocalFile(pics[0]), pics[1]])
    settle()
    strip = child("attachmentStrip")
    thumbs = count("attachmentThumb")
    shot("attachments")
    step("Anhänge: Streifen sichtbar mit zwei Vorschauen, Senden ohne Text möglich",
         strip is not None and strip.property("visible") and thumbs == 2
         and send_btn is not None and send_btn.property("enabled"),
         f"strip={strip and strip.property('visible')} thumbs={thumbs} send={send_btn and send_btn.property('enabled')}")
    clicked = root.clickNamed("attachmentRemove")
    settle(200)
    thumbs = count("attachmentThumb")
    step("Anhang entfernen: Knopf ruft backend.removeAttachment, eine Vorschau bleibt",
         clicked and ("remove", 0) in backend.calls and thumbs == 1,
         f"clicked={clicked} calls={backend.calls} thumbs={thumbs}")
    root.typeInput("Was ist auf dem Bild?")
    settle(100)
    sent = root.sendCurrent()
    settle(200)
    step("Senden mit Bild: backend.send bekommt den Text, Streifen verschwindet",
         sent and ("send", "Was ist auf dem Bild?") in backend.calls and strip is not None
         and not strip.property("visible"),
         f"sent={sent} calls={backend.calls} strip={strip and strip.property('visible')}")

    # 5. Streaming: Zeilen im Verlauf, Bilder in beiden Blasen, Stopp-Knopf während busy
    backend._model.append("user", "Was zeigt dieser Screenshot?", images=[QUrl.fromLocalFile(pics[0]).toString()],
                          when="14:02")
    row = backend._model.append("assistant", "", when="14:02")
    backend.set_busy(True)
    backend.set_state("busy")
    backend.set_waiting(True)
    settle()
    shot("typing")
    dots = root.findNamed("typingDots", None)
    step("Tippende Punkte am Ende, solange Hermes noch nichts schreibt; Uhrzeit unter der Frage",
         dots is not None and dots.property("visible") and count("messageTime") >= 1,
         f"dots={dots and dots.property('visible')} times={count('messageTime')}")
    backend.set_waiting(False)
    busy_stop = send_btn is not None and send_btn.property("text") == "Stopp" and send_btn.property("enabled")
    # Wie hermes-os-tray: eine Zeile je Werkzeugaufruf, am Ende mit Dauer abgeschlossen
    tool_row = backend._model.append("tool", "os_status", "started")
    backend._model.set_text(row, "Gebootet ist **hermes-os** `44.20260926`. Hier ein Bild dazu:")
    backend._model.set_images(row, [QUrl.fromLocalFile(pics[1]).toString()])
    backend._model.set_text(tool_row, "os_status · 0,3 s", "completed")
    settle()
    lv = child("messageList")
    images = count("bubbleImage")
    shot("streaming")
    step("Streaming: Stopp-Knopf während der Arbeit, drei Zeilen im Verlauf, zwei Bilder in Blasen",
         busy_stop and lv is not None and lv.property("count") == 3 and lv.property("contentHeight") > 0
         and images == 2,
         f"stop={busy_stop} count={lv and lv.property('count')} h={lv and lv.property('contentHeight')} "
         f"images={images}")

    # 5b. Antworten von Hermes als HTML mit Zeilenhöhe (tray/chat_text.py), die Frage als
    #     schlichter Text; unter der Antwort steht „Hermes · Uhrzeit“
    def items_named(item, name, out):
        if item.objectName() == name:
            out.append(item)
        for c in item.childItems():
            items_named(c, name, out)
        return out
    # textFormat liest PySide nicht (kein Konverter für die Aufzählung): am Inhalt erkennen.
    # Jede Zeile hat ein Textfeld, auch die Werkzeugzeile (leer); das Textfeld gibt HTML
    # mit eigenem Kopf zurück, die Zeilenhöhe aus chat_text.py bleibt darin stehen.
    texts = [str(t.property("text")) for t in items_named(root.contentItem(), "messageText", [])]
    rich = [t for t in texts if "line-height" in t]
    plain = [t for t in texts if t and "<" not in t]
    metas = [str(t.property("text")) for t in items_named(root.contentItem(), "messageTime", [])]
    step("Antwort als HTML mit Zeilenhöhe, Frage als Text, Absender unter der Antwort",
         len(rich) == 1 and "Was zeigt dieser Screenshot?" in plain and any(m.startswith("Hermes") for m in metas),
         f"texts={len(texts)} rich={len(rich)} plain={len(plain)} metas={metas}")

    # 6. Freigabe: Karte mit den erlaubten Knöpfen, Klick ruft backend.approve
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
    step("Freigabe: Karte mit Befehl, Immer-Knopf versteckt, Einmal ruft backend.approve('once')",
         visible_ok and text_ok and ("approve", "once") in backend.calls,
         f"visible={visible_ok} text={text_ok} calls={backend.calls}")
    backend._model.append("info", "Freigabe: Einmal erlauben")
    backend.set_approval({})
    backend.set_busy(False)
    backend.set_state("ready")
    settle()
    shot("answered")
    step("Freigabe beantwortet: Karte verschwindet, Senden-Knopf zurück, Hinweis im Verlauf",
         box is not None and not box.property("visible") and send_btn is not None
         and send_btn.property("text") == "Senden" and lv is not None and lv.property("count") == 4,
         f"visible={box and box.property('visible')} btn={send_btn and send_btn.property('text')} "
         f"count={lv and lv.property('count')}")

    # 7. Schlüssel fehlt: Hinweis mit "Gateway starten"
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

    # 8. Neues Gespräch leert die Liste
    backend.set_state("ready", configured=True)
    settle()
    backend.newConversation()
    settle()
    step("Neues Gespräch: Verlauf leer, Begrüßung darf ohne Warnung erscheinen",
         lv is not None and lv.property("count") == 0, f"count={lv and lv.property('count')}")

    # 9. Bibliothek: Seite öffnen, Eintrag anlegen, Fehler anzeigen, entfernen, zurück
    opened = root.openLibrary()
    settle()
    shot("library-empty")
    step("Bibliothek: Seite öffnet sich und ist leer, Liste wurde neu gelesen",
         bool(opened) and root.libraryOpen() and count("libraryRow") == 0 and ("libreload",) in backend.calls,
         f"opened={opened} open={root.libraryOpen()} rows={count('libraryRow')}")
    root.typeLibrary("https://docs.kde.org/", "KDE-Handbücher", "deutsch unter stable_kf6/de")
    settle(100)
    added = root.libraryAddCurrent()
    settle()
    src_field = child("librarySource")
    shot("library")
    step("Bibliothek: Eintrag anlegen, backend.libraryAdd bekommt die Felder, Zeile erscheint, Felder leer",
         added and ("libadd", "https://docs.kde.org/", "KDE-Handbücher", "deutsch unter stable_kf6/de") in backend.calls
         and count("libraryRow") == 1 and src_field is not None and src_field.property("text") == "",
         f"added={added} calls={backend.calls[-2:]} rows={count('libraryRow')}")
    root.typeLibrary("kaputt", "", "")
    settle(100)
    added2 = root.libraryAddCurrent()
    settle(200)
    err_label = child("libraryError")
    step("Bibliothek: Fehler des Backends wird angezeigt, kein Eintrag dazu",
         not added2 and err_label is not None and err_label.property("visible")
         and "kaputt" in str(err_label.property("text")) and count("libraryRow") == 1,
         f"added={added2} err={err_label and err_label.property('text')!r} rows={count('libraryRow')}")
    clicked = root.clickNamed("libraryRemove")
    settle(200)
    step("Bibliothek: Entfernen ruft backend.libraryRemove, Zeile verschwindet",
         clicked and ("libremove", "e1") in backend.calls and count("libraryRow") == 0,
         f"clicked={clicked} calls={backend.calls[-1:]} rows={count('libraryRow')}")
    backend.showLibrary()
    settle(200)
    still_open = root.libraryOpen()
    root.closeLibrary()
    settle()
    step("Bibliothek: Signal aus dem Menü hält die Seite offen, Zurück zeigt wieder den Chat",
         still_open and not root.libraryOpen() and inp is not None and inp.property("enabled"),
         f"still_open={still_open} open={root.libraryOpen()}")

    # 9b. Bibliothek, Stufe zwei: Ablegen, Spiegeln mit Fortschritt, Suche mit
    #     Trefferliste, Titel und Notiz ändern, Schalter der Doku-Server
    root.openLibrary()
    settle()
    dropped = root.libraryDropped([QUrl("https://docs.kde.org/"), QUrl.fromLocalFile("/tmp/notiz.txt")], "")
    settle()
    msg = child("libraryMessage")
    shot("library-dropped")
    step("Bibliothek: Ablegen legt Einträge an und zeigt die Meldung",
         ("libdrop", ["https://docs.kde.org/", "file:///tmp/notiz.txt"], "") in backend.calls and count("libraryRow") == 2
         and msg is not None and msg.property("visible") and "Eingetragen" in str(dropped),
         f"calls={backend.calls[-1:]} rows={count('libraryRow')} msg={dropped!r}")
    mirror_text = root.findNamed("libraryMirrorText", None)   # Delegate: nur die QML-Seite findet ihn
    before = str(mirror_text.property("text")) if mirror_text is not None else ""
    clicked = root.clickNamed("libraryMirrorButton")
    settle(200)
    mirror_btn = root.findNamed("libraryMirrorButton", None)
    running_text = str(mirror_text.property("text")) if mirror_text is not None else ""
    shot("library-mirroring")
    step("Bibliothek: Spiegeln startet backend.libraryMirrorStart, Zeile zeigt den Fortschritt, Knopf wird zu Abbrechen",
         clicked and ("libmirror", "e1") in backend.calls and before.startswith("Kein Spiegel") and "läuft" in running_text
         and mirror_btn is not None and "abbrechen" in str(mirror_btn.property("text")),
         f"clicked={clicked} before={before!r} running={running_text!r} btn={mirror_btn and mirror_btn.property('text')!r}")
    backend.finish_mirror("e1")
    settle(200)
    done_text = str(mirror_text.property("text")) if mirror_text is not None else ""
    step("Bibliothek: fertiger Spiegel zeigt Seitenzahl und Zeitpunkt, Knopf heißt wieder Spiegeln",
         "5 Seiten" in done_text and mirror_btn is not None and str(mirror_btn.property("text")) == "Spiegeln",
         f"text={done_text!r} btn={mirror_btn and mirror_btn.property('text')!r}")
    root.typeLibrarySearch("versteckte")
    root.librarySearchCurrent()
    settle(200)
    note = child("librarySearchNote")
    shot("library-search")
    step("Bibliothek: Suche ruft backend.librarySearch, zwei Treffer mit Ausschnitt, Hinweis sichtbar",
         ("libsearch", "versteckte") in backend.calls and count("librarySearchHit") == 2 and note is not None
         and note.property("visible") and "2 Treffer" in str(note.property("text")),
         f"calls={backend.calls[-1:]} hits={count('librarySearchHit')}")
    opened_hit = root.clickNamed("librarySearchOpen")
    settle(100)
    step("Bibliothek: Öffnen am Treffer ruft backend.libraryOpenSource mit der Quelle",
         opened_hit and ("libopensource", "https://docs.kde.org/b.html") in backend.calls, f"calls={backend.calls[-1:]}")
    root.typeLibrarySearch("")
    root.librarySearchCurrent()
    settle(100)
    step("Bibliothek: leere Suche räumt die Treffer weg", count("librarySearchHit") == 0, f"hits={count('librarySearchHit')}")
    edit_clicked = root.clickNamed("libraryEdit")
    settle(200)
    title_field, note_field = root.findNamed("libraryEditTitle", None), root.findNamed("libraryEditNote", None)
    fields_visible = title_field is not None and title_field.property("visible") and note_field is not None
    if fields_visible:
        title_field.setProperty("text", "KDE-Handbücher")
        note_field.setProperty("text", "deutsch unter stable_kf6/de")
    saved = root.clickNamed("librarySave")
    settle(200)
    shot("library-edited")
    step("Bibliothek: Bearbeiten öffnet die Felder, Speichern ruft backend.libraryUpdate, Notiz steht in der Zeile",
         edit_clicked and fields_visible and saved and ("libupdate", "e1", "KDE-Handbücher", "deutsch unter stable_kf6/de") in backend.calls
         and root.findNamed("libraryEditTitle", None) is not None
         and not root.findNamed("libraryEditTitle", None).property("visible"),
         f"edit={edit_clicked} fields={fields_visible} saved={saved} calls={backend.calls[-1:]}")
    mcp_rows = count("libraryMcpRow")
    toggled = root.toggleNamed("libraryMcpSwitch")
    settle(200)
    mcp_msg = child("libraryMcpMessage")
    shot("library-mcp")
    step("Bibliothek: zwei Doku-Server mit Schalter, Umschalten ruft backend.libraryMcpSet und zeigt den Hinweis",
         mcp_rows == 2 and toggled and ("mcpset", "context7", True) in backend.calls and mcp_msg is not None
         and mcp_msg.property("visible") and "Gateway" in str(mcp_msg.property("text")),
         f"rows={mcp_rows} toggled={toggled} calls={backend.calls[-1:]}")
    root.closeLibrary()
    settle()

    # 10. Protokoll: Seite öffnen, Zeilen mit Symbol je Ergebnis, Ausgabe aufklappen,
    #     Filter Zeitraum und Änderungen, Export, zurück
    opened = root.openAudit()
    settle()
    shot("audit-today")
    rows_today = count("auditRow")
    step("Protokoll: Seite öffnet sich, meldet sich an und zeigt die Zeilen von heute mit Symbol",
         bool(opened) and root.auditOpen() and ("auditactive", True) in backend.calls and rows_today == 4
         and count("auditStatusIcon") == 4,
         f"opened={opened} rows={rows_today} icons={count('auditStatusIcon')} calls={backend.calls[-3:]}")
    clicked = root.clickNamed("auditOutputToggle")
    settle(200)
    out = root.findNamed("auditOutput", None)
    step("Protokoll: Ausgabe klappt auf",
         clicked and out is not None and out.property("visible"), f"clicked={clicked}")
    root.setAuditFilter("all", False)
    settle()
    step("Protokoll: Zeitraum alles zeigt auch ältere Einträge",
         ("auditfilter", "all", False) in backend.calls and count("auditRow") == 5, f"rows={count('auditRow')}")
    changes = child("auditChangesOnly")
    root.toggleAuditChanges()
    settle()
    shot("audit-changes")
    step("Protokoll: Häkchen nur Änderungen filtert auf gelaufene Systembefehle",
         ("auditfilter", "all", True) in backend.calls and count("auditRow") == 2
         and changes is not None and changes.property("checked"),
         f"rows={count('auditRow')} calls={backend.calls[-2:]}")
    period_box = child("auditPeriod")
    step("Protokoll: Zeitraum-Auswahl folgt dem Backend",
         period_box is not None and period_box.property("currentIndex") == 2,
         f"index={period_box and period_box.property('currentIndex')}")
    exported = root.clickNamed("auditExport")
    settle(200)
    msg = child("auditMessage")
    step("Protokoll: Export ruft backend.auditExport und zeigt die Meldung",
         exported and ("auditexport",) in backend.calls and msg is not None and msg.property("visible")
         and "Gespeichert" in str(msg.property("text")), f"exported={exported}")
    backend.audit_source = []
    root.setAuditFilter("today", False)
    settle()
    shot("audit-empty")
    step("Protokoll: leer ohne Warnung", count("auditRow") == 0, f"rows={count('auditRow')}")
    root.closeAudit()
    settle()
    backend.showAudit()
    settle(200)
    via_menu = root.auditOpen()
    backend.showLibrary()
    settle(200)
    switched = root.libraryOpen() and not root.auditOpen()
    root.closeLibrary()
    settle()
    step("Protokoll: Menü öffnet die Seite, Bibliothek löst sie ab, zurück zum Chat meldet ab",
         via_menu and switched and ("auditactive", False) in backend.calls and not root.auditOpen()
         and not root.libraryOpen(), f"menu={via_menu} switched={switched}")

    # 11. Sehen und Hören: Knöpfe rufen look.capture und voice.toggle, der Zustand
    #     von Push-to-Talk steht im Kopf und macht den Mikrofon-Knopf zum Stopp
    backend.set_state("ready", configured=True)
    settle()
    look_btn, voice_btn, indicator = child("lookButton"), child("voiceButton"), child("voiceIndicator")
    look_clicked = root.clickNamed("lookButton")
    voice_clicked = root.clickNamed("voiceButton")
    settle(100)
    step("Sehen und Hören: Knöpfe sichtbar, Klick ruft look.capture und voice.toggle",
         look_btn is not None and look_btn.property("visible") and look_btn.property("enabled")
         and voice_btn is not None and voice_btn.property("enabled") and look_clicked and voice_clicked
         and ("capture",) in look.calls and ("toggle",) in voice.calls
         and indicator is not None and not indicator.property("visible"),
         f"look={look.calls} voice={voice.calls}")
    state_label = child("stateLabel")
    voice.set_state("recording")
    settle(300)
    shot("voice-recording")
    step("Hört zu: Kopf zeigt den Sprachzustand, Mikrofon-Symbol sichtbar, Knopf wird zu Stopp",
         state_label is not None and state_label.property("text") == "Hermes hört zu …"
         and indicator is not None and indicator.property("visible")
         and voice_btn is not None and voice_btn.property("text") == "Aufnahme beenden" and voice_btn.property("enabled"),
         f"label={state_label and state_label.property('text')!r} btn={voice_btn and voice_btn.property('text')!r}")
    voice.set_state("transcribing")
    settle(200)
    step("Versteht: Knopf aus, Symbol weg, Kopf sagt es",
         voice_btn is not None and not voice_btn.property("enabled") and not indicator.property("visible")
         and state_label.property("text") == "Hermes versteht …",
         f"enabled={voice_btn and voice_btn.property('enabled')} label={state_label.property('text')!r}")
    voice.set_state("speaking")
    settle(200)
    shot("voice-speaking")
    speaking_ok = (voice_btn.property("enabled") and voice_btn.property("text") == "Vorlesen abbrechen"
                   and indicator.property("visible"))
    voice.set_state("idle")
    settle(200)
    step("Spricht: Knopf bricht das Vorlesen ab; danach wieder der Zustand des Gateways",
         speaking_ok and state_label.property("text") == backend.stateText and not indicator.property("visible"),
         f"speaking={speaking_ok} label={state_label.property('text')!r}")

    root.close()
    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
