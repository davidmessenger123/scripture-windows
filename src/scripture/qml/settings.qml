import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

import ScriptureRT 1.0

Item {
    id: settingsRoot
    implicitWidth: 520
    implicitHeight: 700

    readonly property var books: App.availableBooks
    readonly property var topics: App.availableTopics
    property string selTranslation: "ESV"
    property string selBook: ""
    property string selTopic: ""

    Rectangle {
        anchors.fill: parent
        color: "#111418"
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        ColumnLayout {
            id: form
            width: settingsRoot.width
            spacing: 10

            Item { width: 1; height: 8 }

            Text {
                text: "ESV API KEY"
                color: "#faa968"
                font.family: "Segoe UI"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 2
            }

            Text {
                text: "A free api.esv.org key enables the English Standard Version. The key is stored in protected local storage and never logged. Without one the ESV falls back to the World English Bible."
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
                Layout.fillWidth: true

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
                Layout.fillWidth: true

                Text {
                    text: "Fixed verse"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                TextField {
                    id: fixedField
                    Layout.preferredWidth: 180
                    placeholderText: "e.g. John 3:16"
                    maximumLength: 120
                }
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true

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

            CheckBox {
                id: notificationCheck
                text: "Show a daily tray notification"
                checked: false
                Layout.fillWidth: true
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true
                enabled: notificationCheck.checked

                Text {
                    text: "Notification (HH:MM)"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                TextField {
                    id: notificationField
                    Layout.preferredWidth: 120
                    placeholderText: "07:30"
                    maximumLength: 5
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 4
                Layout.preferredHeight: 1
                color: "#2a2f35"
            }

            Text {
                text: "RANDOM SELECTION"
                color: "#faa968"
                font.family: "Segoe UI"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 2
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true

                Text {
                    text: "Book"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.preferredWidth: 70
                }

                ComboBox {
                    id: bookFilter
                    Layout.fillWidth: true
                    model: ["All books"].concat(settingsRoot.books)
                    onActivated: settingsRoot.selBook = currentIndex === 0 ? "" : settingsRoot.books[currentIndex - 1]
                }
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true

                Text {
                    text: "Topic"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.preferredWidth: 70
                }

                ComboBox {
                    id: topicFilter
                    Layout.fillWidth: true
                    model: ["All topics"].concat(settingsRoot.topics)
                    onActivated: settingsRoot.selTopic = currentIndex === 0 ? "" : settingsRoot.topics[currentIndex - 1]
                }
            }

            Text {
                text: "Fixed verses, favorites, and direct jumps do not use these filters."
                color: "#7f8790"
                font.family: "Segoe UI"
                font.pixelSize: 10
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
                text: "APPEARANCE"
                color: "#faa968"
                font.family: "Segoe UI"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 2
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true

                Text {
                    text: "Verse font"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                SpinBox {
                    id: fontField
                    from: 18
                    to: 56
                    editable: true
                    Layout.preferredWidth: 110
                }

                Text {
                    text: "px"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                }
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true

                Text {
                    text: "Scrim opacity"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.preferredWidth: 100
                }

                Slider {
                    id: opacitySlider
                    from: 0.35
                    to: 0.98
                    stepSize: 0.01
                    Layout.fillWidth: true
                }

                Text {
                    text: Math.round(opacitySlider.value * 100) + "%"
                    color: "#e8eaed"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.preferredWidth: 42
                }
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true

                Text {
                    text: "Animation speed"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.preferredWidth: 100
                }

                Slider {
                    id: speedSlider
                    from: 0
                    to: 4
                    stepSize: 0.25
                    Layout.fillWidth: true
                }

                Text {
                    text: speedSlider.value === 0 ? "Off" : speedSlider.value.toFixed(2) + "×"
                    color: "#e8eaed"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    Layout.preferredWidth: 48
                }
            }

            Button {
                text: "Apply"
                Layout.fillWidth: true
                onClicked: App.save_settings(
                    keyField.text,
                    settingsRoot.selTranslation,
                    fixedField.text,
                    autoField.text,
                    notificationField.text,
                    settingsRoot.selBook,
                    settingsRoot.selTopic,
                    notificationCheck.checked,
                    String(fontField.value),
                    opacitySlider.value.toFixed(2),
                    speedSlider.value.toFixed(2)
                )
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

            Text {
                visible: App.actionNotice !== ""
                text: App.actionNotice
                color: "#9aa0a6"
                font.family: "Segoe UI"
                font.pixelSize: 10
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 4
                Layout.preferredHeight: 1
                color: "#2a2f35"
            }

            RowLayout {
                spacing: 8
                Layout.fillWidth: true

                Text {
                    text: "OFFLINE CACHE"
                    color: "#faa968"
                    font.family: "Segoe UI"
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 2
                    Layout.fillWidth: true
                }

                Text {
                    text: App.passageCacheSize + " passages"
                    color: "#9aa0a6"
                    font.family: "Segoe UI"
                    font.pixelSize: 10
                }
            }

            Button {
                text: "Clear cached passages"
                Layout.fillWidth: true
                onClicked: App.clear_passage_cache()
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
                Layout.preferredHeight: App.favorites.length > 0 ? Math.min(App.favorites.length * 34, 170) : 0
                visible: App.favorites.length > 0
                color: "transparent"
                clip: true

                Flickable {
                    anchors.fill: parent
                    contentHeight: favoriteColumn.implicitHeight
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds

                    ColumnLayout {
                        id: favoriteColumn
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

            Item { width: 1; height: 8 }

            Button {
                text: "Close"
                Layout.fillWidth: true
                onClicked: App.settingsOpen = false
            }

            Item { width: 1; height: 8 }
        }
    }

    function seedSettings() {
        keyField.text = App.settingsApiKey
        fixedField.text = App.settingsFixedReference
        autoField.text = App.settingsAutoOpenAt
        notificationField.text = App.settingsNotificationTime
        notificationCheck.checked = App.settingsNotificationEnabled
        selTranslation = App.settingsTranslation
        selBook = App.settingsBookFilter
        selTopic = App.settingsTopicFilter
        bookFilter.currentIndex = selBook === "" ? 0 : settingsRoot.books.indexOf(selBook) + 1
        topicFilter.currentIndex = selTopic === "" ? 0 : settingsRoot.topics.indexOf(selTopic) + 1
        fontField.value = App.settingsVerseFontPx
        opacitySlider.value = App.settingsScrimOpacity
        speedSlider.value = App.settingsAnimationSpeed
    }
}
