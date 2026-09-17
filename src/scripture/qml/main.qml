import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

import ScriptureRT 1.0

// Scripture for Windows — the Omarchy Scripture overlay re-implemented on plain
// Qt Quick. The document root is the full-screen overlay Window itself; the
// settings dialog lives in settings.qml, hosted in its own QQuickView window.
// All behavior lives in the Python `app` controller.

Window {
    id: overlay
    objectName: "overlayWindow"
    visible: App.overlayOpen
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"

    onVisibleChanged: if (visible) {
        // Fill the screen geometry manually rather than entering a native
        // full-screen Space. On macOS, Window.FullScreen maps to a Spaces
        // transition, and hiding that window leaves an empty black Space on
        // screen when the overlay is closed. Manual geometry covers the same
        // area on every platform and hides cleanly.
        const scr = overlay.screen
        if (scr) {
            overlay.x = scr.virtualX
            overlay.y = scr.virtualY
            overlay.width = scr.width
            overlay.height = scr.height
        }
        // A frameless always-on-top window does not necessarily become the key
        // window by itself, and without key status the Esc handler never fires.
        // Ask for activation so keyboard dismissal works on every platform.
        requestActivate()
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

    // Decorative Latin cross drawn from rectangles, not text: the vertical stem
    // and horizontal beam share a common horizontal center, so they can never
    // drift apart the way monospace block characters can.
    component CrossMark: Item {
        id: mark
        property color cr: Qt.rgba(1, 1, 1, 0.55)
        property real cellW: 25
        property real cellH: 42

        width: mark.beamW
        height: mark.stemH

        readonly property real beamW: 11 * cellW
        readonly property real stemW: 3 * cellW
        readonly property real beamH: 2 * cellH
        readonly property real stemH: 13 * cellH
        readonly property real beamTop: 3 * cellH

        Rectangle {
            anchors.horizontalCenter: mark.horizontalCenter
            width: mark.stemW
            height: mark.stemH
            color: mark.cr
            radius: mark.stemW / 3
        }
        Rectangle {
            anchors.horizontalCenter: mark.horizontalCenter
            width: mark.beamW
            height: mark.beamH
            y: mark.beamTop
            color: mark.cr
            radius: mark.beamH / 4
        }
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

            // Decorative Latin crosses, fixed to the screen edges.
            CrossMark {
                id: crossLeft
                anchors.left: parent.left
                anchors.leftMargin: 64
                anchors.verticalCenter: parent.verticalCenter
                opacity: App.loading ? 0.45 : 1
                Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
            }

            CrossMark {
                id: crossRight
                anchors.right: parent.right
                anchors.rightMargin: 64
                anchors.verticalCenter: parent.verticalCenter
                cr: Qt.rgba(1, 1, 1, 0.55)
                opacity: App.loading ? 0.45 : 1
                Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
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

                    // E — update chip (self-update: download, then restart to apply)
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 8
                        objectName: "updateChip"
                        visible: Updater.updateAvailable || Updater.downloading || Updater.updateApplied
                                    || Updater.updateError !== ""

                        ColumnLayout {
                            spacing: 3
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: Updater.downloading ? "Downloading update " + Math.round(Updater.updateProgress * 100) + "%" :
                                      Updater.updateApplied ? "Applying update — Scripture will restart\u2026" :
                                      Updater.updateError !== "" ? "Update failed" :
                                      "Update available: " + Updater.updateTag
                                color: Updater.updateError !== "" ? "#ff6b6b" : "#f5c542"
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                                font.bold: true
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                visible: Updater.updateError !== ""
                                text: Updater.updateError
                                color: Qt.rgba(1, 1, 1, 0.6)
                                font.family: "Segoe UI"
                                font.pixelSize: 10
                            }
                        }
                        OverlayButton {
                            text: Updater.downloading ? "Downloading\u2026" :
                                  Updater.updateApplied ? "Restarting\u2026" :
                                  Updater.updateError !== "" ? "Retry" : "Download"
                            tip: Updater.updateError !== "" ? "Retry the self-update" : "Download and install the update automatically"
                            padX: 10
                            fg: "white"
                            enabled: !Updater.downloading && !Updater.updateApplied
                            onClicked: Updater.download()
                        }
                        OverlayButton {
                            text: "Open browser"
                            tip: "Open the release page in your browser"
                            padX: 10
                            fg: Qt.rgba(1, 1, 1, 0.55)
                            enabled: !Updater.downloading
                            onClicked: Updater.open()
                        }
                    }

                    // F — favorites chips (at most 8 + overflow note)
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

            // Explicit, always-visible close affordance. The overlay can also be
            // dismissed with Esc or a bare-scrim click, but neither is reliable
            // when keyboard focus or the click target is not — so the corner
            // button is the guaranteed way out of a full-screen verse. It is a
            // sibling of the scaled cluster (not inside it) so it never shrinks
            // or drifts with the content.
            OverlayButton {
                id: closeButton
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.topMargin: 24
                anchors.rightMargin: 24
                text: "\u2715  Close"
                tip: "Close the overlay (Esc)"
                padX: 16
                padY: 7
                radius: 17
                fg: "white"
                onClicked: App.close_overlay()
            }
        }
}
