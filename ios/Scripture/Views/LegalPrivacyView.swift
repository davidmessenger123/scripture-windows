import SwiftUI

struct LegalPrivacyView: View {
    @EnvironmentObject private var viewModel: ScriptureViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var isPerformingAction = false
    @State private var actionMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    sectionTitle("Provider requests", systemImage: "arrow.up.right.square")
                    Text("WEB and KJV: the app sends the selected Scripture reference to bible-api.com to retrieve the passage; the returned passage is processed on this device.")
                    Text("ESV: when a key is configured, the app sends the selected Scripture reference to api.esv.org and sends the key in the request Authorization header. The returned passage is processed on this device, and the key is never sent to bible-api.com.")
                    Text("These requests are used only to retrieve the selected Scripture passage. Provider terms and service information:")
                    if let url = URL(string: "https://bible-api.com/") {
                        Link(destination: url) {
                            Label("bible-api.com terms and service information", systemImage: "arrow.up.right.square")
                        }
                    }
                    if let url = URL(string: "https://api.esv.org/") {
                        Link(destination: url) {
                            Label("ESV API terms and documentation", systemImage: "arrow.up.right.square")
                        }
                    }
                    if let url = URL(string: "https://www.crossway.org/permissions/") {
                        Link(destination: url) {
                            Label("Crossway permissions", systemImage: "arrow.up.right.square")
                        }
                    }

                    sectionTitle("Cache and key retention", systemImage: "externaldrive")
                    Text("Successful passages are stored locally in Library/Caches/Scripture with canonical verse IDs. The cache is excluded from backup, protected until first unlock, and bounded for ESV by 500 verses and half of each book. It remains until the app evicts it, the system clears caches, or you delete it below.")
                    Text("The optional ESV API key is stored in the device-only Keychain. It is not stored in UserDefaults, the passage cache, the clipboard, or notification content. Delete the key below to remove it from the Keychain and clear the passage cache.")

                    sectionTitle("Favorites and session history", systemImage: "star")
                    Text("Favorites are persisted on-device in Application Support/Scripture/favorites.json. Application Support is normally eligible for device backup, so favorites may be included in an encrypted device backup; the app does not control system backup inclusion.")
                    Text("Session history is kept in memory only for the current app session. It is not written to disk, cached, backed up, or sent to Scripture providers, and it is cleared when the app process or session ends.")
                    Text("The trash button beside an individual favorite removes that favorite. Delete All Favorites removes every persisted favorite from the device.")

                    sectionTitle("Analytics", systemImage: "chart.bar.xaxis")
                    Text("No analytics or advertising SDK is included, and the app does not use either to track users.")

                    sectionTitle("Clipboard and sharing", systemImage: "doc.on.doc")
                    Text("Copy stays local to this device, is marked local-only, and expires after five minutes. Verse cards are encoded as temporary PNG files only when requested and shared through the system share sheet.")

                    sectionTitle("Controls", systemImage: "trash")
                    Button(role: .destructive) {
                        guard !isPerformingAction else { return }
                        isPerformingAction = true
                        Task { @MainActor in
                            let success = viewModel.deleteAllFavorites()
                            actionMessage = success
                                ? "All favorites deleted."
                                : (viewModel.errorMessage ?? "The action could not be completed.")
                            isPerformingAction = false
                        }
                    } label: {
                        Label("Delete All Favorites", systemImage: "trash")
                    }
                    .disabled(isPerformingAction)
                    Button(role: .destructive) {
                        guard !isPerformingAction else { return }
                        isPerformingAction = true
                        Task { @MainActor in
                            let success = await viewModel.deletePassageCache()
                            actionMessage = success ? "Passage cache deleted." : "The action could not be completed."
                            isPerformingAction = false
                        }
                    } label: {
                        Label("Delete passage cache", systemImage: "trash")
                    }
                    .disabled(isPerformingAction)
                    Button(role: .destructive) {
                        guard !isPerformingAction else { return }
                        isPerformingAction = true
                        Task { @MainActor in
                            let success = await viewModel.deleteAPIKey()
                            actionMessage = success
                                ? "ESV API key and passage cache deleted."
                                : (viewModel.settingsNotice ?? "The action could not be completed.")
                            isPerformingAction = false
                        }
                    } label: {
                        Label("Delete ESV API key", systemImage: "key.slash")
                    }
                    .disabled(isPerformingAction)
                    if let actionMessage {
                        Text(actionMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                    Text("Passage surfaces show the passage, its reference, and a compact translation label such as ESV, WEB, or KJV. Provider legal notices are not copied into the overlay, clipboard, card, or notification output.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Text("Scripture 0.2.0")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: 700, alignment: .leading)
                .padding(24)
            }
            .navigationTitle("Legal & Privacy")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func sectionTitle(_ title: String, systemImage: String) -> some View {
        Label(title, systemImage: systemImage)
            .font(.headline)
            .foregroundStyle(Color(red: 0.98, green: 0.66, blue: 0.41))
    }
}
