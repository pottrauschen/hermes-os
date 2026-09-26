// hermes-os -- Leisten-Symbol, das Fenster.
// Ein Chat wie in einem Messenger: Kopf mit Symbol und Zustand, Verlauf in
// Sprechblasen, Freigabe-Karte, unten die Eingabe als Karte mit Bild-Anhängen.
// Alles, was Hermes berührt, läuft über `backend` (hermes-os-tray, Python):
// backend.messages ist ein Listenmodell mit den Rollen role (user, assistant,
// tool, info, error), text, meta, images (Liste von URLs) und time;
// backend.attachments sind die Bilder, die mit der nächsten Nachricht gehen
// (Dateidialog, Strg+V, ins Fenster gezogen).
// Das Fenster wird von Python gezeigt und versteckt; Schließen versteckt nur.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Hermes"
    width: Kirigami.Units.gridUnit * 30
    height: Kirigami.Units.gridUnit * 36
    minimumWidth: Kirigami.Units.gridUnit * 20
    minimumHeight: Kirigami.Units.gridUnit * 18
    visible: false

    pageStack.initialPage: chatPage
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None

    readonly property int bubbleRadius: Kirigami.Units.largeSpacing + Kirigami.Units.smallSpacing
    readonly property var suggestions: ["Welches Image ist gebootet?", "Gibt es ein Update?", "Starte Firefox"]

    // Farben der Zustände, dieselben wie in den Leisten-Symbolen
    function stateColor(state) {
        if (state === "ready") return "#3daee9"
        if (state === "busy") return "#f67400"
        if (state === "asking") return "#f8b400"
        return Kirigami.Theme.disabledTextColor
    }

    // Für tests/tray-gui-check.py und die Tastatur
    function sendCurrent() {
        var t = inputField.text.trim()
        if (t.length === 0 && backend.attachmentCount === 0) return false
        backend.send(t)
        inputField.text = ""
        return true
    }
    function typeInput(text) { inputField.text = text }
    function allows(choice) {
        var cs = backend.approval.choices
        return cs !== undefined && cs.indexOf(choice) >= 0
    }
    // Delegates aus Repeater und ListView hängen nur im Item-Baum, nicht im
    // QObject-Baum; findChild aus Python sieht sie nicht. Deshalb suchen diese
    // Helfer über `children` und zählen oder klicken Items mit objectName.
    function countNamed(name, item) {
        if (!item) item = root.contentItem       // Python übergibt None, QML undefined
        var n = item.objectName === name ? 1 : 0
        var kids = item.children
        for (var i = 0; i < kids.length; i++) n += countNamed(name, kids[i])
        return n
    }
    function findNamed(name, item) {
        if (!item) item = root.contentItem
        if (item.objectName === name) return item
        var kids = item.children
        for (var i = 0; i < kids.length; i++) {
            var hit = findNamed(name, kids[i])
            if (hit !== null) return hit
        }
        return null
    }
    function clickNamed(name) {
        var item = findNamed(name)
        if (item === null) return false
        item.clicked()
        return true
    }

    onVisibleChanged: if (visible) inputField.forceActiveFocus()

    Shortcut {
        sequence: "Escape"
        onActivated: backend.hideWindow()
    }

    // Ein Bild in einer Sprechblase: so groß wie das Bild, höchstens maxWidth
    // mal maxHeight; ein Klick öffnet es im Bildbetrachter. Kein sourceSize:
    // das würde kleine Bilder hochskalieren; große Bilder liefert Python schon
    // als verkleinerte Vorschau (make_preview in hermes-os-tray).
    component BubbleImage: Item {
        id: holder
        property alias source: picture.source
        property int maxWidth: Kirigami.Units.gridUnit * 16
        property int maxHeight: Kirigami.Units.gridUnit * 18
        width: picture.width
        height: picture.height
        Image {
            id: picture
            objectName: "bubbleImage"
            asynchronous: true
            cache: true
            fillMode: Image.PreserveAspectFit
            readonly property real fit: implicitWidth > 0 && implicitHeight > 0
                ? Math.min(1, holder.maxWidth / implicitWidth, holder.maxHeight / implicitHeight) : 1
            width: implicitWidth > 0 ? Math.max(1, Math.round(implicitWidth * fit))
                                     : Math.min(holder.maxWidth, Kirigami.Units.gridUnit * 8)
            height: implicitHeight > 0 ? Math.max(1, Math.round(implicitHeight * fit)) : Kirigami.Units.gridUnit * 5
            Rectangle {
                anchors.fill: parent
                radius: Kirigami.Units.smallSpacing
                color: picture.status === Image.Ready ? "transparent"
                     : Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.1)
                border.width: 1
                border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.25)
                Kirigami.Icon {
                    anchors.centerIn: parent
                    visible: picture.status === Image.Error
                    source: "image-missing"
                    width: Kirigami.Units.iconSizes.medium
                    height: width
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: backend.openImage("" + picture.source)
            }
        }
    }

    // Die Seite lebt wie beim Assistenten in einem unsichtbaren Behälter und
    // wird nur auf den Stapel geschoben (siehe setup/Main.qml).
    Item {
        id: pageStore
        visible: false

    Kirigami.Page {
        id: chatPage
        padding: 0

        // ---- Kopf: Symbol mit Statuspunkt, Name und Zustand, Knöpfe -------------
        header: Controls.ToolBar {
            contentItem: RowLayout {
                spacing: Kirigami.Units.largeSpacing
                Item {
                    Layout.leftMargin: Kirigami.Units.smallSpacing
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    Kirigami.Icon {
                        anchors.fill: parent
                        source: "hermes-os"
                    }
                    Rectangle {
                        objectName: "stateDot"
                        width: Kirigami.Units.smallSpacing * 3
                        height: width
                        radius: width / 2
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.rightMargin: -2
                        anchors.bottomMargin: -2
                        color: root.stateColor(backend.state)
                        border.width: 2
                        border.color: Kirigami.Theme.backgroundColor
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Kirigami.Heading {
                        Layout.fillWidth: true
                        text: "Hermes"
                        level: 3
                        elide: Text.ElideRight
                    }
                    Controls.Label {
                        objectName: "stateLabel"
                        Layout.fillWidth: true
                        text: backend.stateText
                        elide: Text.ElideRight
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                    }
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

        // ---- Fuß: die Eingabe als Karte mit Anhängen, Textfeld und Knöpfen -----
        footer: Item {
            implicitHeight: composer.height + Kirigami.Units.largeSpacing * 2
            Kirigami.Separator {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
            }
            Rectangle {
                id: composer
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Kirigami.Units.largeSpacing
                height: composerCol.implicitHeight + Kirigami.Units.smallSpacing * 2
                radius: Kirigami.Units.largeSpacing
                Kirigami.Theme.colorSet: Kirigami.Theme.View
                Kirigami.Theme.inherit: false
                color: Kirigami.Theme.backgroundColor
                border.width: 1
                border.color: inputField.activeFocus ? Kirigami.Theme.highlightColor
                            : Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.25)
                Behavior on border.color { ColorAnimation { duration: 120 } }

                ColumnLayout {
                    id: composerCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Kirigami.Units.smallSpacing
                    spacing: Kirigami.Units.smallSpacing

                    // Bilder, die mit der nächsten Nachricht gehen
                    Flow {
                        id: attachmentStrip
                        objectName: "attachmentStrip"
                        Layout.fillWidth: true
                        Layout.leftMargin: Kirigami.Units.smallSpacing
                        Layout.rightMargin: Kirigami.Units.smallSpacing
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        visible: backend.attachmentCount > 0
                        spacing: Kirigami.Units.smallSpacing
                        Repeater {
                            model: backend.attachments
                            delegate: Item {
                                id: thumbItem
                                objectName: "attachmentThumb"
                                required property var modelData
                                required property int index
                                width: Kirigami.Units.gridUnit * 4
                                height: width
                                Image {
                                    anchors.fill: parent
                                    source: thumbItem.modelData.url
                                    asynchronous: true
                                    fillMode: Image.PreserveAspectCrop
                                    sourceSize.width: Kirigami.Units.gridUnit * 8
                                    sourceSize.height: Kirigami.Units.gridUnit * 8
                                    clip: true
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    color: "transparent"
                                    radius: Kirigami.Units.smallSpacing
                                    border.width: 1
                                    border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.3)
                                }
                                Controls.RoundButton {
                                    objectName: "attachmentRemove"
                                    anchors.top: parent.top
                                    anchors.right: parent.right
                                    anchors.margins: 2
                                    padding: 2
                                    icon.name: "dialog-close"
                                    icon.width: Kirigami.Units.iconSizes.small
                                    icon.height: Kirigami.Units.iconSizes.small
                                    display: Controls.AbstractButton.IconOnly
                                    text: "Bild entfernen"
                                    Controls.ToolTip.text: text
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                                    onClicked: backend.removeAttachment(thumbItem.index)
                                }
                            }
                        }
                    }

                    // Textfeld: wächst mit dem Text, ab sieben Zeilen scrollt es
                    Flickable {
                        id: inputFlick
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(contentHeight, Kirigami.Units.gridUnit * 7)
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        Controls.ScrollBar.vertical: Controls.ScrollBar {
                            policy: inputFlick.contentHeight > inputFlick.height
                                ? Controls.ScrollBar.AlwaysOn : Controls.ScrollBar.AlwaysOff
                        }
                        Controls.TextArea.flickable: Controls.TextArea {
                            id: inputField
                            objectName: "inputField"
                            background: null
                            wrapMode: TextEdit.Wrap
                            placeholderText: backend.state === "ready" ? "Frag Hermes …" : backend.stateText
                            enabled: backend.state === "ready" && !backend.busy
                            // Enter sendet, Umschalt+Enter macht eine neue Zeile; Strg+V mit
                            // einem Bild in der Zwischenablage hängt es an statt Text einzufügen.
                            Keys.onPressed: event => {
                                if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                                        && !(event.modifiers & Qt.ShiftModifier)) {
                                    root.sendCurrent()
                                    event.accepted = true
                                } else if (event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier)
                                           && backend.pasteImage()) {
                                    event.accepted = true
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing
                        Controls.ToolButton {
                            objectName: "attachButton"
                            icon.name: "insert-image"
                            display: Controls.AbstractButton.IconOnly
                            text: "Bild anhängen"
                            enabled: backend.state === "ready" && !backend.busy
                            Controls.ToolTip.text: "Bild anhängen: Datei wählen, Strg+V oder ins Fenster ziehen"
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                            onClicked: backend.attachFromDialog()
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
                        Controls.Label {
                            Layout.fillWidth: true
                            text: backend.attachmentCount > 0
                                ? (backend.attachmentCount === 1 ? "1 Bild geht mit" : backend.attachmentCount + " Bilder gehen mit")
                                : "Enter sendet, Umschalt+Enter macht eine neue Zeile"
                            elide: Text.ElideRight
                            font: Kirigami.Theme.smallFont
                            opacity: 0.6
                        }
                        Controls.Button {
                            id: sendButton
                            objectName: "sendButton"
                            text: backend.busy ? "Stopp" : "Senden"
                            icon.name: backend.busy ? "process-stop" : "document-send"
                            highlighted: !backend.busy
                            enabled: backend.busy || (backend.state === "ready"
                                     && (inputField.text.trim().length > 0 || backend.attachmentCount > 0))
                            onClicked: backend.busy ? backend.stopRun() : root.sendCurrent()
                        }
                    }
                }
            }
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // Gateway aus oder Schlüssel fehlt: sagen, was zu tun ist
            Kirigami.InlineMessage {
                id: offBox
                objectName: "offBox"
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.largeSpacing
                Layout.bottomMargin: 0
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

            // ---- Verlauf: Sprechblasen auf einer Fläche in Ansichtsfarben ---------
            Rectangle {
                id: chatArea
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: offBox.visible ? Kirigami.Units.largeSpacing : 0
                Kirigami.Theme.colorSet: Kirigami.Theme.View
                Kirigami.Theme.inherit: false
                color: Kirigami.Theme.backgroundColor
                clip: true
                readonly property color bubbleColor: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.07)
                readonly property color hairline: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)

                ListView {
                    id: messageList
                    objectName: "messageList"
                    anchors.fill: parent
                    leftMargin: Kirigami.Units.largeSpacing
                    // rechts Platz für die Bildlaufleiste, die über dem Inhalt liegt
                    rightMargin: Kirigami.Units.largeSpacing * 2 + Kirigami.Units.smallSpacing
                    topMargin: Kirigami.Units.largeSpacing
                    bottomMargin: Kirigami.Units.largeSpacing
                    clip: true
                    spacing: Kirigami.Units.smallSpacing
                    model: backend.messages
                    boundsBehavior: Flickable.StopAtBounds
                    Controls.ScrollBar.vertical: Controls.ScrollBar {}
                    // Beim Streamen unten bleiben, solange der Nutzer nicht hochgescrollt hat.
                    // atYEnd rechnet den unteren Rand mit ein, positionViewAtEnd nicht;
                    // deshalb gilt "nah am Ende" ab weniger als zwei Rastereinheiten Abstand.
                    property bool followTail: true
                    readonly property bool nearEnd: contentHeight + bottomMargin - (contentY + height) < Kirigami.Units.gridUnit * 2
                    onMovementEnded: followTail = nearEnd
                    onCountChanged: { followTail = true; Qt.callLater(messageList.positionViewAtEnd) }
                    onContentHeightChanged: if (followTail) Qt.callLater(messageList.positionViewAtEnd)
                    add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 150 } }

                    delegate: Item {
                        id: row
                        required property int index
                        required property string role
                        required property string text
                        required property string meta
                        required property var images
                        required property string time
                        readonly property bool mine: role === "user"
                        readonly property bool isBubble: role === "user" || role === "assistant" || role === "error"
                        readonly property var imageList: images ? images : []
                        readonly property int avatarSlot: Kirigami.Units.iconSizes.smallMedium + Kirigami.Units.smallSpacing * 2
                        readonly property int maxBubble: Math.max(Kirigami.Units.gridUnit * 6, Math.round((width - avatarSlot) * 0.84))
                        width: ListView.view ? ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin : 0
                        implicitHeight: isBubble ? bubbleWrap.implicitHeight
                                      : (role === "tool" ? toolRow.implicitHeight : infoPill.implicitHeight)

                        // Sprechblase: Nutzer rechts in Akzentfarbe, Hermes links mit Symbol
                        Item {
                            id: bubbleWrap
                            visible: row.isBubble
                            width: row.width
                            implicitHeight: bubble.height + (timeLabel.visible ? timeLabel.implicitHeight + 2 : 0)

                            Kirigami.Icon {
                                id: avatar
                                visible: !row.mine
                                source: row.role === "error" ? "dialog-error" : "hermes-os"
                                width: Kirigami.Units.iconSizes.smallMedium
                                height: width
                                anchors.left: parent.left
                                anchors.bottom: bubble.bottom
                            }
                            // Unsichtbare Messung: die natürliche Breite des Textes ohne
                            // Umbruch, damit kurze Antworten kurze Blasen bekommen
                            Text {
                                id: measure
                                visible: false
                                text: row.text
                                textFormat: row.role === "assistant" ? Text.MarkdownText : Text.PlainText
                                font: Kirigami.Theme.defaultFont
                            }
                            Rectangle {
                                id: bubble
                                readonly property int pad: Kirigami.Units.largeSpacing
                                readonly property int innerMax: row.maxBubble - pad * 2
                                readonly property int wanted: Math.ceil(Math.max(measure.implicitWidth, imageCol.childrenRect.width,
                                                                                typing.visible ? typing.width : 0))
                                width: Math.min(row.maxBubble, wanted + pad * 2)
                                height: content.implicitHeight + pad * 2
                                x: row.mine ? row.width - width : row.avatarSlot
                                radius: root.bubbleRadius
                                bottomRightRadius: row.mine ? Kirigami.Units.smallSpacing : root.bubbleRadius
                                bottomLeftRadius: row.mine ? root.bubbleRadius : Kirigami.Units.smallSpacing
                                color: row.mine ? Kirigami.Theme.highlightColor
                                     : (row.role === "error" ? Kirigami.Theme.negativeBackgroundColor : chatArea.bubbleColor)
                                border.width: row.mine ? 0 : 1
                                border.color: row.role === "error" ? Kirigami.Theme.negativeTextColor : chatArea.hairline

                                Column {
                                    id: content
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: bubble.pad
                                    spacing: Kirigami.Units.smallSpacing
                                    Column {
                                        id: imageCol
                                        width: parent.width
                                        spacing: Kirigami.Units.smallSpacing
                                        visible: row.imageList.length > 0
                                        Repeater {
                                            model: row.imageList
                                            delegate: BubbleImage {
                                                required property string modelData
                                                source: modelData
                                                maxWidth: bubble.innerMax
                                            }
                                        }
                                    }
                                    // Drei pulsierende Punkte, solange Hermes noch nichts geschrieben hat
                                    Row {
                                        id: typing
                                        visible: row.role === "assistant" && row.text.length === 0
                                                 && row.imageList.length === 0 && backend.busy
                                        spacing: Kirigami.Units.smallSpacing
                                        Repeater {
                                            model: 3
                                            Rectangle {
                                                required property int index
                                                width: Kirigami.Units.smallSpacing * 2
                                                height: width
                                                radius: width / 2
                                                color: Kirigami.Theme.textColor
                                                opacity: 0.3
                                                SequentialAnimation on opacity {
                                                    running: typing.visible
                                                    loops: Animation.Infinite
                                                    PauseAnimation { duration: index * 160 }
                                                    NumberAnimation { to: 1; duration: 320 }
                                                    NumberAnimation { to: 0.3; duration: 320 }
                                                    PauseAnimation { duration: (2 - index) * 160 }
                                                }
                                            }
                                        }
                                    }
                                    Kirigami.SelectableLabel {
                                        id: label
                                        width: parent.width
                                        visible: row.text.length > 0
                                        text: row.text
                                        textFormat: row.role === "assistant" ? TextEdit.MarkdownText : TextEdit.PlainText
                                        wrapMode: TextEdit.Wrap
                                        color: row.mine ? Kirigami.Theme.highlightedTextColor
                                             : (row.role === "error" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor)
                                        onLinkActivated: link => Qt.openUrlExternally(link)
                                    }
                                }
                            }
                            Controls.Label {
                                id: timeLabel
                                visible: row.time.length > 0 && row.role !== "error"
                                text: row.time
                                font: Kirigami.Theme.smallFont
                                opacity: 0.5
                                anchors.top: bubble.bottom
                                anchors.topMargin: 2
                                x: row.mine ? bubble.x + bubble.width - width : bubble.x
                            }
                        }

                        // Werkzeugaufruf: kleine Zeile mit Symbol, in Monospace
                        RowLayout {
                            id: toolRow
                            visible: row.role === "tool"
                            x: row.avatarSlot
                            width: row.width - row.avatarSlot
                            spacing: Kirigami.Units.smallSpacing
                            Kirigami.Icon {
                                source: row.meta === "completed" ? "dialog-ok-apply"
                                      : (row.meta === "error" ? "dialog-error" : "media-playback-start")
                                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                opacity: 0.7
                            }
                            Controls.Label {
                                Layout.fillWidth: true
                                text: row.text
                                elide: Text.ElideRight
                                font: Kirigami.Theme.fixedWidthFont
                                opacity: 0.7
                                color: row.meta === "error" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                            }
                        }

                        // Hinweis: mittig, als kleine Pille
                        Rectangle {
                            id: infoPill
                            visible: row.role === "info"
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.min(row.width, infoLabel.implicitWidth + Kirigami.Units.largeSpacing * 2)
                            implicitHeight: infoLabel.implicitHeight + Kirigami.Units.smallSpacing * 2
                            height: implicitHeight
                            radius: height / 2
                            color: chatArea.bubbleColor
                            Controls.Label {
                                id: infoLabel
                                anchors.centerIn: parent
                                width: Math.min(implicitWidth, row.width - Kirigami.Units.largeSpacing * 2)
                                text: row.text
                                elide: Text.ElideRight
                                font: Kirigami.Theme.smallFont
                                opacity: 0.8
                            }
                        }
                    }
                }

                // Leerer Verlauf: Begrüßung und Vorschläge zum Anklicken
                ColumnLayout {
                    id: welcome
                    visible: messageList.count === 0
                    anchors.centerIn: parent
                    width: Math.min(parent.width - Kirigami.Units.gridUnit * 4, Kirigami.Units.gridUnit * 24)
                    spacing: Kirigami.Units.largeSpacing
                    Kirigami.Icon {
                        source: "hermes-os"
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: Kirigami.Units.iconSizes.huge
                        Layout.preferredHeight: Kirigami.Units.iconSizes.huge
                    }
                    Kirigami.Heading {
                        Layout.fillWidth: true
                        text: "Was kann ich für dich tun?"
                        level: 2
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        opacity: 0.7
                        text: "Ich kenne dieses System: Image, Dienste, Apps und Hardware. Frag mich etwas, "
                            + "zieh ein Bild ins Fenster oder füge einen Screenshot mit Strg+V ein."
                    }
                    Repeater {
                        model: root.suggestions
                        Kirigami.Chip {
                            required property string modelData
                            Layout.alignment: Qt.AlignHCenter
                            text: modelData
                            closable: false
                            checkable: false
                            onClicked: { inputField.text = modelData; inputField.forceActiveFocus() }
                        }
                    }
                }

                // Zurück ans Ende, wenn man hochgescrollt hat
                Controls.RoundButton {
                    icon.name: "go-down"
                    visible: messageList.count > 0 && !messageList.nearEnd
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: Kirigami.Units.largeSpacing * 2
                    onClicked: { messageList.followTail = true; messageList.positionViewAtEnd() }
                }

                // Bilder hineinziehen
                DropArea {
                    id: dropArea
                    anchors.fill: parent
                    keys: ["text/uri-list"]
                    onDropped: drop => {
                        if (drop.hasUrls) {
                            backend.attachFiles(drop.urls)
                            drop.acceptProposedAction()
                        }
                    }
                }
                Rectangle {
                    anchors.fill: parent
                    visible: dropArea.containsDrag
                    color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.highlightColor, 0.25)
                    border.width: 2
                    border.color: Kirigami.Theme.highlightColor
                    Kirigami.PlaceholderMessage {
                        anchors.centerIn: parent
                        width: parent.width - Kirigami.Units.gridUnit * 4
                        icon.name: "insert-image"
                        text: "Bild hier ablegen"
                    }
                }
            }

            // ---- Freigabe: der Dialog aus der Grenze, als Karte mit Knöpfen --------
            Rectangle {
                id: approvalBox
                objectName: "approvalBox"
                property string text: backend.approval.command || ""
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.largeSpacing
                visible: backend.approvalPending
                implicitHeight: approvalCol.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.largeSpacing
                color: Kirigami.Theme.neutralBackgroundColor
                border.width: 1
                border.color: Kirigami.Theme.neutralTextColor

                Kirigami.Action {
                    id: approveOnceAction
                    objectName: "approveOnce"
                    text: "Einmal erlauben"
                    icon.name: "dialog-ok"
                    visible: root.allows("once")
                    onTriggered: backend.approve("once")
                }
                Kirigami.Action {
                    id: approveSessionAction
                    objectName: "approveSession"
                    text: "Für diese Sitzung"
                    visible: root.allows("session")
                    onTriggered: backend.approve("session")
                }
                Kirigami.Action {
                    id: approveAlwaysAction
                    objectName: "approveAlways"
                    text: "Immer erlauben"
                    visible: root.allows("always")
                    onTriggered: backend.approve("always")
                }
                Kirigami.Action {
                    id: approveDenyAction
                    objectName: "approveDeny"
                    text: "Ablehnen"
                    icon.name: "dialog-cancel"
                    onTriggered: backend.approve("deny")
                }

                ColumnLayout {
                    id: approvalCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing
                        Kirigami.Icon {
                            source: "dialog-warning"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                        }
                        Kirigami.Heading {
                            Layout.fillWidth: true
                            level: 4
                            text: "Hermes bittet um Freigabe"
                            elide: Text.ElideRight
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: commandLabel.implicitHeight + Kirigami.Units.smallSpacing * 2
                        radius: Kirigami.Units.smallSpacing
                        color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.08)
                        Kirigami.SelectableLabel {
                            id: commandLabel
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: Kirigami.Units.smallSpacing
                            text: backend.approval.command || ""
                            font: Kirigami.Theme.fixedWidthFont
                            wrapMode: TextEdit.Wrap
                        }
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        visible: (backend.approval.description || "") !== ""
                        text: "Warum: " + (backend.approval.description || "")
                        wrapMode: Text.WordWrap
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        text: "Ohne Antwort läuft der Befehl nicht."
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                        wrapMode: Text.WordWrap
                    }
                    // Knöpfe von rechts: der erste Eintrag sitzt ganz rechts, bei
                    // schmalem Fenster brechen sie um
                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing
                        layoutDirection: Qt.RightToLeft
                        Controls.Button { action: approveOnceAction; visible: approveOnceAction.visible; highlighted: true }
                        Controls.Button { action: approveSessionAction; visible: approveSessionAction.visible }
                        Controls.Button { action: approveAlwaysAction; visible: approveAlwaysAction.visible }
                        Controls.Button { action: approveDenyAction }
                    }
                }
            }
        }
    }
    }
}
