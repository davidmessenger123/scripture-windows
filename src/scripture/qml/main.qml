import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

import ScriptureRT 1.0

// Scripture for Windows — the Omarchy Scripture overlay re-implemented on plain
// Qt Quick. The document root is the full-screen overlay Window itself; the
// settings window is a second Window nested inside it, so both are children of
// the root component (and settings is never shown without the overlay). All
// behavior lives in the Python `app` controller.

Window {
    id: overlay
    objectName: "overlayWindow"
    visible: App.overlayOpen
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"

    onVisibleChanged: if (visible) {
        visibility = Window.FullScreen
        Qt.callLater(function () { keyCatcher.forceActiveFocus() })
    }

    // ------------------------------------------------------------------ UI fragments

    component OverlayButton: Button {
        id: cell
        property color fg: "white"
        property int padX: 14
        property int padY: 4
        property string tip: ""
        property real radius: 6

        font.family: "Segoe UI"
        font.pixelSize: 11
        implicitWidth: contentItem.implicitWidth + padX * 2
        implicitHeight: contentItem.implicitHeight + padY * 2
        opacity: enabled ? 1 : 0.25

        background: Rectangle {
            radius: cell.radius
            color: "transparent"
            border.color: cell.enabled ? Qt.rgba(1, 1, 1, 0.35) : Qt.rgba(1, 1, 1, 0.12)
            border.width: 1
        }

        contentItem: Text {
            text: cell.text
            color: cell.enabled ? cell.fg : Qt.rgba(1, 1, 1, 0.25)
            font: cell.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        ToolTip.visible: cell.hovered && cell.tip !== ""
        ToolTip.text: cell.tip
        ToolTip.delay: 500
        hoverEnabled: true
    }

    // ------------------------------------------------------------------ Overlay content

    Item {
            id: keyCatcher
            anchors.fill: parent
            focus: true

            Keys.onEscapePressed: App.close_overlay()
            Keys.onReturnPressed: if (!App.loading) App.refresh()

            // Deep scrim — same 78% black as the Omarchy speed-test overlay.
            Rectangle {
                id: scrim
                anchors.fill: parent
                color: Qt.rgba(0, 0, 0, 0.78)
            }

            // Bare-scrim click dismisses; everything inside the cluster is swallowed.
            MouseArea {
                anchors.fill: parent
                onClicked: App.close_overlay()
            }

            // Decorative block crosses, fixed to the screen edges.
            Text {
                id: crossLeft
                anchors.left: parent.left
                anchors.leftMargin: 64
                anchors.verticalCenter: parent.verticalCenter
                text: [
                    "      ███",
                    "      ███",
                    "      ███",
                    "  ███████████",
                    "  ███████████",
                    "      ███",
                    "      ███",
                    "      ███",
                    "      ███",
                    "      ███",
                    "      ███",
                    "      ███",
                    "      ███"
                ].join("\n")
                font.family: "monospace"
                font.pixelSize: 42
                lineHeight: 1.0
                color: Qt.rgba(1, 1, 1, 0.55)
                opacity: App.loading ? 0.45 : 1
                Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                textFormat: Text.PlainText
            }

            Text {
                id: crossRight
                anchors.right: parent.right
                anchors.rightMargin: 64
                anchors.verticalCenter: parent.verticalCenter
                text: crossLeft.text
                font.family: "monospace"
                font.pixelSize: 42
                lineHeight: 1.0
                color: Qt.rgba(1, 1, 1, 0.55)
                opacity: App.loading ? 0.45 : 1
                Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                textFormat: Text.PlainText
            }

            // Content cluster, auto-scaled to fit the screen.
            Item {
                id: cluster
                anchors.centerIn: parent
                width: content.width
                height: content.height
                scale: Math.min(
                    1,
                    (keyCatcher.width - 32) / Math.max(1, content.implicitWidth),
                    (keyCatcher.height - 32) / Math.max(1, content.implicitHeight))
                transformOrigin: Item.Center

                // Swallows clicks on blank cluster area so only the bare scrim dismisses.
                MouseArea { anchors.fill: parent }

                ColumnLayout {
                    id: content
                    width: implicitWidth
                    spacing: 18

                    // A — translation name
                    Text {
                        Layout.fillWidth: true
                        visible: App.translationLabel !== ""
                        text: App.translationLabel
                        color: Qt.rgba(1, 1, 1, 0.55)
                        font.family: "Segoe UI"
                        font.pixelSize: 10
                        font.bold: true
                        font.letterSpacing: 2
                        horizontalAlignment: Text.AlignHCenter
                    }

                    // B — verse text with typewriter reveal (rich text)
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: Math.min(keyCatcher.width - 96, 760)
                        text: App.displayText
                        textFormat: Text.RichText
                        color: "white"
                        font.family: "Segoe UI"
                        font.pixelSize: 28
                        font.weight: Font.Light
                        lineHeight: 1.55
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                        opacity: App.loading ? 0.45 : 1
                        Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                    }

                    // C — verse reference (the only accent on the overlay)
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        visible: App.verseReference !== ""
                        text: App.verseReference
                        color: "#faa968"
                        font.family: "Segoe UI"
                        font.pixelSize: 11
                        font.bold: true
                        font.letterSpacing: 1.5
                        horizontalAlignment: Text.AlignHCenter
                    }

                    // D — toolbar
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 8

                        OverlayButton {
                            text: "◀"
                            tip: "Previous verse in this session"
                            enabled: App.histCanBack
                            onClicked: App.back()
                        }
                        OverlayButton {
                            text: "▶"
                            tip: "Next verse in this session"
                            enabled: App.histCanForward
                            onClicked: App.forward()
                        }
                        OverlayButton {
                            text: App.fixedReference !== "" ? "Repeat" : "Another Verse"
                            tip: App.fixedReference !== "" ? "Show the fixed verse again" : "Get a different random verse"
                            padX: 14
                            fg: "white"
                            enabled: !App.loading
                            onClicked: App.refresh()
                            opacity: App.loading ? 0 : 1
                            Behavior on opacity { NumberAnimation { duration: 240 } }
                        }
                        OverlayButton {
                            text: App.starSymbol
                            tip: App.isFavorite ? "Remove from favorites" : "Save to favorites"
                            fg: App.isFavorite ? "#f5c542" : Qt.rgba(1, 1, 1, 0.55)
                            enabled: App.anchor !== "" && !App.loading
                            onClicked: App.toggle_favorite()
                        }
                        OverlayButton {
                            text: App.translationId === "esv" ? "Open on esv.org" : "Open in browser"
                            tip: "Read the passage online"
                            fg: Qt.rgba(1, 1, 1, 0.55)
                            enabled: App.verseReference !== ""
                            onClicked: App.open_in_browser(App.verseReference)
                        }
                    }

                    // E — favorites chips (at most 8 + overflow note)
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: keyCatcher.width - 96
                        visible: App.favoritesOverflow + (App.favoritesChips.length > 0 ? 1 : 0) > 0
                        spacing: 6

                        Repeater {
                            model: App.favoritesChips
                            OverlayButton {
                                text: modelData
                                tip: "Open " + modelData
                                padX: 8
                                padY: 2
                                fg: App.anchor === modelData ? "white" : Qt.rgba(1, 1, 1, 0.55)
                                onClicked: App.load_reference(modelData)
                            }
                        }

                        Text {
                            visible: App.favoritesOverflow > 0
                            text: "+" + App.favoritesOverflow + " more"
                            color: Qt.rgba(1, 1, 1, 0.55)
                            font.family: "Segoe UI"
                            font.pixelSize: 10
                        }
                    }

                    // F — jump to any reference
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 8

                        Text {
                            text: "JUMP TO"
                            color: Qt.rgba(1, 1, 1, 0.55)
                            font.family: "Segoe UI"
                            font.pixelSize: 10
                            font.bold: true
                            font.letterSpacing: 2
                            verticalAlignment: Text.AlignVCenter
                        }

                        Rectangle {
                            width: 240
                            height: 34
                            radius: 6
                            color: Qt.rgba(1, 1, 1, 0.12)
                            border.color: Qt.rgba(1, 1, 1, 0.35)

                            TextInput {
                                id: jumpField
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: Text.AlignVCenter
                                color: "white"
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                                selectByMouse: true
                                onAccepted: {
                                    App.load_reference(text)
                                    text = ""
                                }
                            }

                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: Text.AlignVCenter
                                visible: jumpField.text === ""
                                text: "e.g. John 3:16"
                                color: Qt.rgba(1, 1, 1, 0.25)
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                            }
                        }

                        OverlayButton {
                            text: "Go"
                            tip: "Jump to that reference"
                            padX: 12
                            fg: Qt.rgba(1, 1, 1, 0.55)
                            onClicked: {
                                App.load_reference(jumpField.text)
                                jumpField.text = ""
                            }
                        }
                    }

                    // G — fetch notice / H — error
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: 440
                        visible: App.fetchNotice !== ""
                        text: App.fetchNotice
                        color: Qt.rgba(1, 1, 1, 0.55)
                        font.family: "Segoe UI"
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: 440
                        visible: App.errorText !== ""
                        text: App.errorText
                        color: "#ff6b6b"
                        font.family: "Segoe UI"
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
        }
// ------------------------------------------------------------------ Settings window

    Window {
        id: settingsWin
        objectName: "settingsWindow"
        visible: App.settingsOpen
        title: "Scripture Settings"
        width: 440
        height: 560
        minimumWidth: 400
        minimumHeight: 480
        color: "#111418"

        onVisibleChanged: if (visible) seedSettings()
        onClosing: function (close) { close.accepted = true; App.settingsOpen = false }
        Connections {
            target: App
            function onSettingsChanged() {
                if (settingsWin.visible) settingsWin.seedSettings()
            }
        }

        function seedSettings() {
            keyField.text = App.settingsApiKey
            fixedField.text = App.settingsFixedReference
            autoField.text = App.settingsAutoOpenAt
            selTranslation = App.settingsTranslation
        }
        property string selTranslation: "ESV"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            Text {
                text: "ESV API KEY"
                color: "#faa968"
                font.family: "Segoe UI"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 2
            }

            Text {
                text: "A free api.esv.org key enables the English Standard Version. " +
                      "Without one the ESV falls back to the World English Bible."
                color: "#9aa0a6"
                font.family: "Segoe UI"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            TextField {
                id: keyField
                Layout.fillWidth: true
                placeholderText: "Paste your ESV API key (optional)"
                echoMode: TextInput.Password
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 4
                height: 1
                color: "#2a2f35"
            }

            Text {
                text: "VERSE & SCHEDULE"
                color: "#faa968"
                font.family: "Segoe UI"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 2
            }

            RowLayout {
                spacing: 6

                Text {
                    text: "Translation"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                Button { text: "ESV"; checkable: true; checked: settingsWin.selTranslation === "ESV"; onClicked: settingsWin.selTranslation = "ESV" }
                Button { text: "WEB"; checkable: true; checked: settingsWin.selTranslation === "WEB"; onClicked: settingsWin.selTranslation = "WEB" }
                Button { text: "KJV"; checkable: true; checked: settingsWin.selTranslation === "KJV"; onClicked: settingsWin.selTranslation = "KJV" }
            }

            RowLayout {
                spacing: 8

                Text {
                    text: "Fixed verse"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                TextField {
                    id: fixedField
                    Layout.preferredWidth: 150
                    placeholderText: "e.g. John 3:16"
                }
            }

            RowLayout {
                spacing: 8

                Text {
                    text: "Auto-open (HH:MM)"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                TextField {
                    id: autoField
                    Layout.preferredWidth: 120
                    placeholderText: "07:30"
                    maximumLength: 5
                }
            }

            Button {
                text: "Apply"
                Layout.fillWidth: true
                onClicked: App.save_settings(keyField.text, settingsWin.selTranslation, fixedField.text, autoField.text)
            }

            Text {
                visible: App.settingsNotice !== ""
                text: App.settingsNotice
                color: App.settingsNoticeError ? "#ff6b6b" : "#9aa0a6"
                font.family: "Segoe UI"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 4
                height: 1
                color: "#2a2f35"
            }

            Text {
                text: "FAVORITES"
                color: "#faa968"
                font.family: "Segoe UI"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 2
            }

            Text {
                visible: App.favorites.length === 0
                text: "No favorites yet — tap ☆ on any verse to save it."
                color: "#9aa0a6"
                font.family: "Segoe UI"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(App.favorites.length * 34, 170)
                visible: App.favorites.length > 0
                color: "transparent"
                clip: true

                Flickable {
                    anchors.fill: parent
                    contentHeight: favCol.implicitHeight
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds

                    ColumnLayout {
                        id: favCol
                        width: parent.width
                        spacing: 0

                        Repeater {
                            model: App.favorites

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                spacing: 6

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData
                                    color: "#e8eaed"
                                    font.family: "Segoe UI"
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }

                                Button {
                                    text: "▶"
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Load " + modelData
                                    onClicked: {
                                        App.settingsOpen = false
                                        App.load_reference(modelData)
                                    }
                                }

                                Button {
                                    text: "×"
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Remove " + modelData + " from favorites"
                                    onClicked: App.remove_favorite(modelData)
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }
}