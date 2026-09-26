// hermes-os -- Einrichtungsassistent, Oberfläche.
// Vier Seiten: Willkommen, Anbieter, Schlüssel und Modell, Fertig; dazu die
// Portal-Seite für Anbieter mit Anmeldung statt Schlüssel. Die Seiten sind
// dauerhaft instanziiert und werden nur auf den Stapel geschoben: Eingaben
// bleiben beim Zurückblättern erhalten, und Kirigami muss nichts erzeugen.
// Alles, was Hermes berührt, läuft über `backend` (hermes-os-setup, Python).
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Hermes einrichten"
    width: Kirigami.Units.gridUnit * 38
    height: Kirigami.Units.gridUnit * 30
    minimumWidth: Kirigami.Units.gridUnit * 30
    minimumHeight: Kirigami.Units.gridUnit * 24

    // Zustand des Assistenten
    property var provider: null        // Eintrag aus backend.providers
    property string apiKey: ""
    property string model: ""
    property var models: []
    property var filteredModels: []    // models nach dem Suchfeld gefiltert
    property string keyCheck: ""       // "", "ok", "rejected", "unknown"
    property string lastError: ""

    // Suche in der Modellliste: alle Wörter müssen vorkommen, Groß/Klein egal.
    function filterModels(text) {
        var words = text.toLowerCase().split(/\s+/).filter(function (w) { return w.length > 0 })
        if (words.length === 0) return root.models
        return root.models.filter(function (m) {
            var lower = m.toLowerCase()
            return words.every(function (w) { return lower.indexOf(w) >= 0 })
        })
    }

    pageStack.initialPage: welcomePage
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None

    // Seiten über Namen ansprechen: für tests/setup-gui-check.py, das jede
    // Seite offscreen rendert und das Zurückblättern prüft. Für die
    // Schlüssel-Seite wird der erste Anbieter mit Schlüssel eingesetzt, für
    // die Anmeldeseite der erste Anbieter mit Anmeldung.
    function pageFor(name) {
        var pages = { "welcome": welcomePage, "provider": providerPage, "key": keyPage,
                      "portal": portalPage, "save": savePage }
        return (name in pages) ? pages[name] : null
    }
    function hasPage(name) { return pageFor(name) !== null }
    function goBack() { pageStack.pop() }
    function openModelList() { modelPopup.open() }     // für den Test
    function closeModelList() { modelPopup.close() }
    function modelListOpen() { return modelPopup.opened }
    function typeModelFilter(text) { modelFilter.text = text }
    function prepare(name) {
        if (name === "key" || name === "save") {
            for (var i = 0; i < backend.providers.length; i++)
                if (backend.providers[i].auth === "api_key") { root.provider = backend.providers[i]; break }
        } else if (name === "portal") {
            for (var j = 0; j < backend.providers.length; j++)
                if (backend.providers[j].auth === "oauth") { root.provider = backend.providers[j]; break }
        }
        if (name === "save") { root.apiKey = "test"; root.model = "test/modell" }
    }
    function pushPage(name) {          // wie ein Klick auf Weiter
        var page = pageFor(name)
        if (page === null) return false
        prepare(name)
        pageStack.push(page)
        if (name === "save") savePage.start()
        return true
    }
    function showPage(name) {          // Stapel leeren, Seite allein zeigen
        var page = pageFor(name)
        if (page === null) return false
        prepare(name)
        pageStack.clear()
        pageStack.push(page)
        if (name === "save") savePage.start()
        return true
    }

    // ---- Fußzeile mit Zurück / Weiter, auf jeder Seite gleich ---------------
    component WizardFooter: Controls.ToolBar {
        id: bar
        property alias backVisible: backButton.visible
        property alias nextText: nextButton.text
        property alias nextEnabled: nextButton.enabled
        property alias nextVisible: nextButton.visible
        signal back()
        signal next()
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.largeSpacing
            anchors.rightMargin: Kirigami.Units.largeSpacing
            Controls.Button {
                id: backButton
                text: "Zurück"
                icon.name: "go-previous"
                onClicked: bar.back()
            }
            Item { Layout.fillWidth: true }
            Controls.Button {
                id: nextButton
                text: "Weiter"
                icon.name: "go-next"
                highlighted: true
                onClicked: bar.next()
            }
        }
    }

    // Alle Seiten leben in diesem unsichtbaren Behälter. Kirigamis Seitenstapel
    // löscht beim Zurückblättern Seiten ohne Elternteil; mit Elternteil setzt
    // er sie hierher zurück, und sie lassen sich erneut aufrufen.
    Item {
        id: pageStore
        visible: false

    // ---- Seite 1: Willkommen ------------------------------------------------
    Kirigami.ScrollablePage {
        id: welcomePage
        title: "Willkommen"
        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Heading { text: "Hermes einrichten"; level: 1 }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "Hermes ist der Agent dieses Systems. Er kennt das Image, die Dienste, Apps und Hardware, "
                    + "fragt bei gefährlichen Änderungen nach und lässt sich per Text und Sprache bedienen. "
                    + "Damit er antworten kann, braucht er ein Sprachmodell bei einem Anbieter."
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                visible: backend.hermesVersion !== ""
                text: backend.hermesVersion
                opacity: 0.7
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: backend.configuredProvider !== ""
                type: Kirigami.MessageType.Information
                text: "Es ist bereits ein Anbieter eingerichtet: " + backend.configuredProvider
                    + ". Der Assistent überschreibt Anbieter und Modell, wenn du ihn zu Ende führst."
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: backend.catalogError !== ""
                type: Kirigami.MessageType.Error
                text: "Hermes-Katalog nicht lesbar: " + backend.catalogError
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "Drei Schritte: Anbieter wählen, Schlüssel eintragen und prüfen, Modell wählen. "
                    + "Wer lieber das Terminal nimmt, findet unten den Weg zu hermes setup."
            }
            Controls.Button {
                text: "Lieber im Terminal einrichten"
                icon.name: "utilities-terminal"
                flat: true
                onClicked: { backend.openTerminalSetup(); root.close() }
            }
        }
        footer: WizardFooter {
            backVisible: false
            nextEnabled: backend.providers.length > 0
            onNext: root.pageStack.push(providerPage)
        }
    }

    // ---- Seite 2: Anbieter --------------------------------------------------
    Kirigami.ScrollablePage {
        id: providerPage
        title: "Anbieter"
        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Heading { text: "Welcher Anbieter?"; level: 2 }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "OpenRouter bündelt viele Modelle hinter einem Schlüssel und ist der einfachste Einstieg. "
                    + "Die Liste kommt aus Hermes selbst."
            }
            Repeater {
                model: backend.providers
                delegate: Controls.RadioDelegate {
                    Layout.fillWidth: true
                    required property var modelData
                    text: modelData.label + (modelData.auth === "oauth" ? "  (Anmeldung statt Schlüssel)" : "")
                    checked: root.provider !== null && root.provider.slug === modelData.slug
                    onClicked: root.provider = modelData
                }
            }
        }
        footer: WizardFooter {
            onBack: root.pageStack.pop()
            nextEnabled: root.provider !== null
            onNext: {
                if (root.provider.auth === "oauth") root.pageStack.push(portalPage)
                else root.pageStack.push(keyPage)
            }
        }
    }

    // ---- Seite 3: Schlüssel und Modell -------------------------------------
    Kirigami.ScrollablePage {
        id: keyPage
        title: "Schlüssel"

        Connections {
            target: root
            function onProviderChanged() { keyField.text = "" }
        }
        Connections {
            target: backend
            function onModelsReady(list, preset, check) {
                root.models = list
                root.filteredModels = list
                root.keyCheck = check
                root.lastError = ""
                modelFilter.text = ""
                root.model = preset !== "" ? preset : (list.length > 0 ? list[0] : "")
                modelList.currentIndex = list.indexOf(root.model)
                if (modelList.currentIndex >= 0) modelList.positionViewAtIndex(modelList.currentIndex, ListView.Center)
            }
            function onModelsFailed(message) {
                root.keyCheck = ""
                root.lastError = message
            }
        }
        // Nach dem Einfügen von selbst prüfen: kurz warten, bis nichts mehr
        // kommt, dann losschicken. Der Knopf bleibt für Wiederholungen.
        Timer {
            id: autoCheck
            interval: 900
            onTriggered: if (keyField.text.length >= 16 && !backend.busy && root.keyCheck === "")
                             backend.checkKey(root.provider.slug, keyField.text)
        }

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Heading { text: root.provider ? root.provider.label : ""; level: 2 }

            // Hinweis des Anbieters, etwa bei Anthropic: kein Abo, nur Schlüssel
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.provider !== null && root.provider.hint !== ""
                type: Kirigami.MessageType.Information
                text: root.provider ? root.provider.hint : ""
            }

            // Wo der Schlüssel herkommt
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.provider !== null && root.provider.signup !== ""
                type: Kirigami.MessageType.Information
                text: "Einen Schlüssel bekommst du im Konto des Anbieters: " + (root.provider ? root.provider.signup : "")
                actions: [
                    Kirigami.Action {
                        text: "Adresse kopieren"
                        icon.name: "edit-copy"
                        onTriggered: backend.copyToClipboard(root.provider.signup)
                    },
                    Kirigami.Action {
                        text: "Im Browser öffnen"
                        icon.name: "internet-web-browser"
                        onTriggered: backend.openUrl(root.provider.signup)
                    }
                ]
            }

            Kirigami.FormLayout {
                Layout.fillWidth: true
                Kirigami.PasswordField {
                    id: keyField
                    Kirigami.FormData.label: "API-Schlüssel:"
                    Layout.fillWidth: true
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 26
                    placeholderText: "Schlüssel hier einfügen"
                    onTextChanged: {
                        root.apiKey = text; root.keyCheck = ""; root.models = []; root.filteredModels = []
                        root.model = ""; autoCheck.restart()
                    }
                    onAccepted: if (text.length > 0 && !backend.busy) backend.checkKey(root.provider.slug, text)
                }
                RowLayout {
                    Kirigami.FormData.label: " "
                    Controls.Button {
                        text: backend.busy ? "Prüfe…" : "Schlüssel prüfen"
                        icon.name: "view-refresh"
                        enabled: keyField.text.length > 0 && !backend.busy
                        onClicked: backend.checkKey(root.provider.slug, keyField.text)
                    }
                    Controls.BusyIndicator { running: backend.busy; visible: backend.busy }
                }
                // Aufklappliste mit Suchfeld: die ComboBox liefert Aussehen, Pfeil
                // und die Anzeige der Wahl; die Liste selbst kommt aus dem eigenen
                // Popup mit Suchfeld oben, weil die eingebaute keine Suche kennt.
                Controls.ComboBox {
                    id: modelBox
                    Kirigami.FormData.label: "Modell:"
                    Layout.fillWidth: true
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 26
                    enabled: root.models.length > 0
                    model: []
                    displayText: root.model !== "" ? root.model : (root.models.length > 0 ? "Modell wählen…" : "")
                    popup: Controls.Popup {
                        id: modelPopup
                        y: modelBox.height
                        width: Math.max(modelBox.width, Kirigami.Units.gridUnit * 26)
                        height: Kirigami.Units.gridUnit * 18
                        margins: Kirigami.Units.smallSpacing   // bleibt im Fenster
                        padding: Kirigami.Units.smallSpacing
                        onOpened: {
                            modelFilter.text = ""
                            modelFilter.forceActiveFocus()
                            modelList.currentIndex = root.filteredModels.indexOf(root.model)
                            if (modelList.currentIndex >= 0) modelList.positionViewAtIndex(modelList.currentIndex, ListView.Center)
                        }
                        contentItem: ColumnLayout {
                            spacing: Kirigami.Units.smallSpacing
                            Kirigami.SearchField {
                                id: modelFilter
                                Layout.fillWidth: true
                                placeholderText: "Suchen, z. B. claude sonnet"
                                // Kirigami feuert accepted sonst bei jeder Textänderung;
                                // hier soll nur Enter den ersten Treffer nehmen.
                                autoAccept: false
                                onTextChanged: {
                                    root.filteredModels = root.filterModels(text)
                                    modelList.currentIndex = root.filteredModels.indexOf(root.model)
                                }
                                // Enter nimmt den ersten Treffer, Escape schließt
                                onAccepted: if (root.filteredModels.length > 0) { root.model = root.filteredModels[0]; modelPopup.close() }
                                Keys.onEscapePressed: modelPopup.close()
                                Keys.onDownPressed: modelList.forceActiveFocus()
                            }
                            ListView {
                                id: modelList
                                objectName: "modelList"          // für tests/setup-gui-check.py
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                model: root.filteredModels
                                currentIndex: -1
                                keyNavigationEnabled: true
                                Keys.onReturnPressed: if (currentIndex >= 0) { root.model = root.filteredModels[currentIndex]; modelPopup.close() }
                                Keys.onEscapePressed: modelPopup.close()
                                delegate: Controls.ItemDelegate {
                                    required property int index
                                    required property string modelData
                                    width: ListView.view.width
                                    text: modelData
                                    highlighted: modelData === root.model || ListView.isCurrentItem
                                    onClicked: { root.model = modelData; modelPopup.close() }
                                }
                                Controls.ScrollBar.vertical: Controls.ScrollBar {}
                                Controls.Label {
                                    anchors.centerIn: parent
                                    visible: modelList.count === 0
                                    text: "Kein Modell passt zur Suche."
                                    opacity: 0.7
                                }
                            }
                            Controls.Label {
                                Layout.fillWidth: true
                                text: root.filteredModels.length + " von " + root.models.length + " Modellen"
                                opacity: 0.7
                            }
                        }
                    }
                }
                Controls.Label {
                    Kirigami.FormData.label: " "
                    visible: root.keyCheck === "" && !backend.busy
                    text: "Die Modelle erscheinen, sobald der Schlüssel geprüft ist."
                    opacity: 0.7
                }
            }

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.keyCheck === "ok"
                type: Kirigami.MessageType.Positive
                text: "Schlüssel angenommen. " + root.models.length + " Modelle geladen"
                    + (modelFilter.text !== "" ? ", " + root.filteredModels.length + " passen zur Suche." : ", eines ist vorgewählt.")
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.keyCheck === "rejected"
                type: Kirigami.MessageType.Error
                text: "Der Anbieter hat den Schlüssel abgelehnt. Bitte noch einmal kopieren und einfügen."
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.keyCheck === "unknown"
                type: Kirigami.MessageType.Warning
                text: "Der Schlüssel ließ sich nicht bestätigen, vermutlich fehlt gerade das Netz. "
                    + "Du kannst trotzdem speichern; Hermes meldet sich beim ersten Chat."
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.lastError !== ""
                type: Kirigami.MessageType.Error
                text: "Prüfung fehlgeschlagen: " + root.lastError
            }
        }
        footer: WizardFooter {
            onBack: root.pageStack.pop()
            nextText: "Speichern"
            nextEnabled: root.apiKey.length > 0 && root.model.length > 0
                && root.keyCheck !== "" && root.keyCheck !== "rejected" && !backend.busy
            onNext: { root.pageStack.push(savePage); savePage.start() }
        }
    }

    // ---- Seite 3b: Abo-Anbieter (Anmeldung im Terminal) --------------------
    Kirigami.ScrollablePage {
        id: portalPage
        title: "Anmeldung"
        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Heading { text: "Anmeldung bei " + (root.provider ? root.provider.label : ""); level: 2 }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: root.provider ? root.provider.hint : ""
            }
            Controls.Button {
                text: "Anmeldung im Terminal starten"
                icon.name: "utilities-terminal"
                enabled: root.provider !== null
                onClicked: backend.openLogin(root.provider.slug)
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "Wenn das Terminal fertig gemeldet hat, kannst du dieses Fenster schließen."
                opacity: 0.7
            }
        }
        footer: WizardFooter {
            onBack: root.pageStack.pop()
            nextText: "Schließen"
            onNext: root.close()
        }
    }

    // ---- Seite 4: Speichern und fertig -------------------------------------
    Kirigami.ScrollablePage {
        id: savePage
        title: "Fertig"
        property bool done: false
        property string error: ""
        function start() {
            done = false
            error = ""
            backend.save(root.provider.slug, root.apiKey, root.model)
        }
        Connections {
            target: backend
            function onSaved(provider, model) { savePage.done = true }
            function onSaveFailed(message) { savePage.error = message }
        }
        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Heading { text: savePage.done ? "Hermes ist bereit" : "Speichere…"; level: 2 }
            Controls.BusyIndicator {
                running: !savePage.done && savePage.error === ""
                visible: running
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: savePage.error !== ""
                type: Kirigami.MessageType.Error
                text: "Speichern fehlgeschlagen: " + savePage.error
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                visible: savePage.done
                text: "Anbieter " + (root.provider ? root.provider.label : "") + ", Modell " + root.model + ". "
                    + "Der Schlüssel liegt in ~/.hermes/.env, Anbieter und Modell in ~/.hermes/config.yaml. "
                    + "Das Gateway für Messaging und Cron wird als Nutzerdienst gestartet."
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                visible: savePage.done
                text: "Im Terminal: hermes für den Chat, /voice on für Push-to-Talk, ujust hermes-doctor für die Diagnose."
                opacity: 0.7
            }
            Controls.Button {
                visible: savePage.done
                text: "Chat im Terminal öffnen"
                icon.name: "utilities-terminal"
                onClicked: { backend.openChat(); root.close() }
            }
        }
        footer: WizardFooter {
            backVisible: savePage.error !== ""
            onBack: root.pageStack.pop()
            nextText: "Schließen"
            nextEnabled: savePage.done || savePage.error !== ""
            onNext: root.close()
        }
    }

    } // pageStore
}
