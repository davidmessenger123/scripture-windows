import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

import ScriptureRT 1.0

// Settings dialog, hosted in its own top-level QQuickView window. It is a
// separate window from the Scripture overlay, so it can be opened and edited
// on its own. Visibility is driven from Python (main.py) as the window opens;
// this file only mirrors `App.*` settings state into the form.

Item {
    id: settingsRoot
    implicitWidth: 440
    implicitHeight: 560

    Rectangle {
        anchors.fill: parent
        color: "#111418"
    }

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
                  "The key is stored in protected local storage and never logged. " +
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
            maximumLength: 512
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 4
            Layout.preferredHeight: 1
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

            Button { text: "ESV"; checkable: true; checked: settingsRoot.selTranslation === "ESV"; onClicked: settingsRoot.selTranslation = "ESV" }
            Button { text: "WEB"; checkable: true; checked: settingsRoot.selTranslation === "WEB"; onClicked: settingsRoot.selTranslation = "WEB" }
            Button { text: "KJV"; checkable: true; checked: settingsRoot.selTranslation === "KJV"; onClicked: settingsRoot.selTranslation = "KJV" }
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
                maximumLength: 120
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
            onClicked: App.save_settings(keyField.text, settingsRoot.selTranslation, fixedField.text, autoField.text)
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
            Layout.preferredHeight: 1
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

        Button {
            text: "Close"
            Layout.fillWidth: true
            onClicked: App.settingsOpen = false
        }
    }

    // Refresh the form from the app settings each time the window opens.
    function seedSettings() {
        keyField.text = App.settingsApiKey
        fixedField.text = App.settingsFixedReference
        autoField.text = App.settingsAutoOpenAt
        selTranslation = App.settingsTranslation
    }
    property string selTranslation: "ESV"
}