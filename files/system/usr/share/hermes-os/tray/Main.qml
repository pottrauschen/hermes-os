// hermes-os -- Leisten-Symbol, das Fenster.
// Ein kompakter Chat: Zustand oben, Verlauf in der Mitte, Freigabe-Kasten und
// Textfeld unten. Alles, was Hermes berührt, läuft über `backend`
// (hermes-os-tray, Python): backend.messages ist ein Listenmodell mit den
// Rollen role (user, assistant, tool, info, error), text und meta.
// Das Fenster wird von Python gezeigt und versteckt; Schließen versteckt nur.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Hermes"
    width: Kirigami.Units.gridUnit * 28
    height: Kirigami.Units.gridUnit * 34
    minimumWidth: Kirigami.Units.gridUnit * 20
    minimumHeight: Kirigami.Units.gridUnit * 18
    visible: false

    pageStack.initialPage: chatPage
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None

    // Für tests/tray-gui-check.py und die Tastatur
    function sendCurrent() {
        var t = inputField.text.trim()
        if (t.length === 0) return false
        backend.send(t)
        inputField.text = ""
        return true
    }
    function typeInput(text) { inputField.text = text }
    function allows(choice) {
        var cs = backend.approval.choices
        return cs !== undefined && cs.indexOf(choice) >= 0
    }

    onVisibleChanged: if (visible) inputField.forceActiveFocus()

    Shortcut {
        sequence: "Escape"
        onActivated: backend.hideWindow()
    }

    // Die Seite lebt wie beim Assistenten in einem unsichtbaren Behälter und
    // wird nur auf den Stapel geschoben (siehe setup/Main.qml).
    Item {
        id: pageStore
        visible: false

    Kirigami.Page {
        id: chatPage
        padding: Kirigami.Units.smallSpacing

        // ---- Kopf: Zustand, neues Gespräch, Einrichtung ------------------------
        header: Controls.ToolBar {
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Kirigami.Units.smallSpacing
                anchors.rightMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing
                Kirigami.Icon {
                    source: backend.stateIcon
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                }
                Controls.Label {
                    objectName: "stateLabel"
                    Layout.fillWidth: true
                    text: backend.stateText
                    elide: Text.ElideRight
                }
                Controls.BusyIndicator {
                    running: backend.busy
                    visible: backend.busy
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                }
                Controls.ToolButton {
                    icon.name: "list-add"
                    display: Controls.AbstractButton.IconOnly
                    text: "Neues Gespräch"
                    Controls.ToolTip.text: text
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                    onClicked: backend.newConversation()
                }
                Controls.ToolButton {
                    icon.name: "configure"
                    display: Controls.AbstractButton.IconOnly
                    text: "Hermes einrichten"
                    Controls.ToolTip.text: text
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                    onClicked: backend.openSetup()
                }
            }
        }

        // ---- Fuß: Textfeld, Mikrofon, Senden oder Stopp ------------------------
        footer: Controls.ToolBar {
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Kirigami.Units.smallSpacing
                anchors.rightMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing
                Controls.TextField {
                    id: inputField
                    objectName: "inputField"
                    Layout.fillWidth: true
                    placeholderText: backend.state === "ready" ? "Frag Hermes …" : backend.stateText
                    enabled: backend.state === "ready" && !backend.busy
                    onAccepted: root.sendCurrent()
                }
                Controls.ToolButton {
                    icon.name: "audio-input-microphone"
                    enabled: false
                    text: "Sprache kommt in der nächsten Stufe"
                    display: Controls.AbstractButton.IconOnly
                    Controls.ToolTip.text: text
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                }
                Controls.Button {
                    id: sendButton
                    objectName: "sendButton"
                    text: backend.busy ? "Stopp" : "Senden"
                    icon.name: backend.busy ? "process-stop" : "document-send"
                    highlighted: !backend.busy
                    enabled: backend.busy || (backend.state === "ready" && inputField.text.trim().length > 0)
                    onClicked: backend.busy ? backend.stopRun() : root.sendCurrent()
                }
            }
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            // Gateway aus oder Schlüssel fehlt: sagen, was zu tun ist
            Kirigami.InlineMessage {
                id: offBox
                objectName: "offBox"
                Layout.fillWidth: true
                visible: backend.state === "off" || backend.state === "nokey"
                type: Kirigami.MessageType.Warning
                text: backend.state === "nokey"
                    ? "Das Gateway läuft, aber in ~/.hermes/.env fehlt der Schlüssel für das Leisten-Symbol. "
                      + "„Gateway starten“ legt ihn an und startet das Gateway neu."
                    : (backend.configured
                        ? "Das Hermes-Gateway läuft nicht."
                        : "Hermes ist noch nicht eingerichtet: Anbieter, Schlüssel und Modell fehlen.")
                actions: [
                    Kirigami.Action {
                        objectName: "setupAction"
                        text: "Hermes einrichten"
                        icon.name: "configure"
                        visible: !backend.configured
                        onTriggered: backend.openSetup()
                    },
                    Kirigami.Action {
                        objectName: "gatewayAction"
                        text: "Gateway starten"
                        icon.name: "media-playback-start"
                        visible: backend.configured
                        onTriggered: backend.startGateway()
                    }
                ]
            }

            // ---- Verlauf --------------------------------------------------------
            ListView {
                id: messageList
                objectName: "messageList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: Kirigami.Units.smallSpacing
                model: backend.messages
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar {}
                // Beim Streamen unten bleiben, solange der Nutzer nicht hochgescrollt hat
                property bool followTail: true
                onMovementEnded: followTail = atYEnd
                onCountChanged: { followTail = true; Qt.callLater(messageList.positionViewAtEnd) }
                onContentHeightChanged: if (followTail) Qt.callLater(messageList.positionViewAtEnd)

                Kirigami.PlaceholderMessage {
                    anchors.centerIn: parent
                    width: parent.width - Kirigami.Units.gridUnit * 4
                    visible: messageList.count === 0
                    icon.name: "hermes-os"
                    text: "Frag Hermes etwas"
                    explanation: "Zum Beispiel: Welches Image ist gebootet? Gibt es ein Update? Starte Firefox."
                }

                delegate: Item {
                    id: row
                    required property string role
                    required property string text
                    required property string meta
                    width: ListView.view ? ListView.view.width : 0
                    implicitHeight: bubble.height
                    Rectangle {
                        id: bubble
                        readonly property bool mine: row.role === "user"
                        readonly property bool small: row.role !== "user" && row.role !== "assistant"
                        readonly property int pad: small ? Kirigami.Units.smallSpacing : Kirigami.Units.largeSpacing
                        x: mine ? row.width - width : 0
                        width: small ? row.width : Math.round(row.width * 0.85)
                        height: label.implicitHeight + pad * 2
                        radius: Kirigami.Units.smallSpacing * 2
                        color: mine ? Kirigami.Theme.highlightColor
                             : (small ? "transparent" : Kirigami.Theme.alternateBackgroundColor)
                        Controls.Label {
                            id: label
                            anchors.fill: parent
                            anchors.margins: bubble.pad
                            text: row.text
                            wrapMode: Text.Wrap
                            textFormat: row.role === "assistant" ? Text.MarkdownText : Text.PlainText
                            color: bubble.mine ? Kirigami.Theme.highlightedTextColor
                                 : (row.role === "error" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor)
                            opacity: bubble.small && row.role !== "error" ? 0.75 : 1
                            font: bubble.small ? Kirigami.Theme.smallFont : Kirigami.Theme.defaultFont
                            onLinkActivated: link => Qt.openUrlExternally(link)
                        }
                    }
                }
            }

            // ---- Freigabe: der Dialog aus der Grenze, hier mit Knöpfen ----------
            Kirigami.InlineMessage {
                id: approvalBox
                objectName: "approvalBox"
                Layout.fillWidth: true
                visible: backend.approvalPending
                type: Kirigami.MessageType.Warning
                text: "Hermes will einen Befehl ausführen, der deine Freigabe braucht:\n"
                    + (backend.approval.command || "")
                    + (backend.approval.description ? "\n\nWarum: " + backend.approval.description : "")
                    + "\n\nOhne Antwort läuft der Befehl nicht."
                actions: [
                    Kirigami.Action {
                        objectName: "approveOnce"
                        text: "Einmal erlauben"
                        icon.name: "dialog-ok"
                        visible: root.allows("once")
                        onTriggered: backend.approve("once")
                    },
                    Kirigami.Action {
                        objectName: "approveSession"
                        text: "Für diese Sitzung"
                        visible: root.allows("session")
                        onTriggered: backend.approve("session")
                    },
                    Kirigami.Action {
                        objectName: "approveAlways"
                        text: "Immer erlauben"
                        visible: root.allows("always")
                        onTriggered: backend.approve("always")
                    },
                    Kirigami.Action {
                        objectName: "approveDeny"
                        text: "Ablehnen"
                        icon.name: "dialog-cancel"
                        onTriggered: backend.approve("deny")
                    }
                ]
            }
        }
    }
    }
}
