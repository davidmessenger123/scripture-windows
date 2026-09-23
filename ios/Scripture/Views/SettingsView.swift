import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var viewModel: ScriptureViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var apiKey = ""
    @State private var translation: Translation = .esv
    @State private var fixedReference = ""
    @State private var hasReminder = false
    @State private var reminderTime = Date()
    @State private var didLoad = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    SecureField("Optional ESV API key", text: $apiKey)
                        .textContentType(.password)
                    Text("Without a key, Scripture uses the World English Bible. The key is stored in the device Keychain.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } header: {
                    Label("Translation", systemImage: "text.book.closed")
                }

                Section {
                    Picker("Version", selection: $translation) {
                        ForEach(Translation.allCases) { option in
                            Text(option.rawValue).tag(option)
                        }
                    }
                    .pickerStyle(.segmented)

                    TextField("John 3:16", text: $fixedReference)
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                } header: {
                    Label("Verse", systemImage: "bookmark")
                } footer: {
                    Text("A fixed verse makes Repeat show this passage instead of drawing another one.")
                }

                Section {
                    Toggle("Daily reminder", isOn: $hasReminder)
                        .onChange(of: hasReminder) { _, enabled in
                            if enabled, reminderTimeString.isEmpty {
                                reminderTime = dateFromTime("07:30") ?? Date()
                            }
                        }
                    if hasReminder {
                        DatePicker("Time", selection: $reminderTime, displayedComponents: .hourAndMinute)
                            .datePickerStyle(.wheel)
                            .labelsHidden()
                    }
                } header: {
                    Label("Reminder", systemImage: "bell")
                } footer: {
                    Text("iOS delivers a local notification at the selected time. It cannot force-open the app while it is in the background.")
                }

                Section {
                    if viewModel.favorites.isEmpty {
                        Text("No favorites yet. Tap the star beside a verse to save it.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(viewModel.favorites, id: \.self) { favorite in
                            HStack {
                                Button {
                                    dismiss()
                                    Task { await viewModel.loadFavorite(favorite) }
                                } label: {
                                    Label(favorite, systemImage: "arrow.up.right")
                                        .foregroundStyle(.primary)
                                }
                                .buttonStyle(.plain)
                                Spacer()
                                Button(role: .destructive) {
                                    viewModel.removeFavorite(favorite)
                                } label: {
                                    Image(systemName: "trash")
                                }
                                .buttonStyle(.borderless)
                                .accessibilityLabel("Remove \(favorite) from favorites")
                            }
                        }
                    }
                } header: {
                    Label("Favorites", systemImage: "star")
                }

                if let notice = viewModel.settingsNotice {
                    Section {
                        Text(notice)
                            .foregroundStyle(viewModel.settingsNoticeIsError ? Color.red : Color.white.opacity(0.6))
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color(red: 0.035, green: 0.047, blue: 0.067))
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task { await save() }
                    }
                    .fontWeight(.semibold)
                }
            }
        }
        .onAppear(perform: loadDraft)
        .onDisappear {
            // The draft is intentionally discarded when cancelled.
        }
    }

    private var reminderTimeString: String {
        ScriptureViewModel.timeComponents(Self.formatter.string(from: reminderTime)) == nil
            ? ""
            : Self.formatter.string(from: reminderTime)
    }

    private func loadDraft() {
        guard !didLoad else { return }
        didLoad = true
        viewModel.clearSettingsNotice()
        let settings = viewModel.settings
        apiKey = settings.apiKey
        translation = settings.translation
        fixedReference = settings.fixedReference
        hasReminder = !settings.autoOpenTime.isEmpty
        reminderTime = dateFromTime(settings.autoOpenTime) ?? dateFromTime("07:30") ?? Date()
    }

    private func save() async {
        viewModel.clearSettingsNotice()
        let draft = AppSettings(
            apiKey: apiKey,
            translation: translation,
            fixedReference: fixedReference,
            autoOpenTime: hasReminder ? Self.formatter.string(from: reminderTime) : ""
        )
        await viewModel.saveSettings(draft)
        if !viewModel.settingsNoticeIsError {
            dismiss()
        }
    }

    private func dateFromTime(_ value: String) -> Date? {
        guard let (hour, minute) = ScriptureViewModel.timeComponents(value) else { return nil }
        var components = DateComponents()
        components.hour = hour
        components.minute = minute
        return Calendar.current.date(from: components)
    }

    private static let formatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()
}
