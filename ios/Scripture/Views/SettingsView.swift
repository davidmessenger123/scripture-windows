import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var viewModel: ScriptureViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var apiKey = ""
    @State private var translation: Translation = .esv
    @State private var fixedReference = ""
    @State private var bookFilter = ""
    @State private var topicFilter: ScriptureTopic = .all
    @State private var verseFontSize: Double = 28
    @State private var scrimOpacity: Double = 0.12
    @State private var revealSpeed: Double = 0.5
    @State private var hasReminder = false
    @State private var reminderTime = Date()
    @State private var didLoad = false
    @State private var isShowingLegal = false

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
                    Picker("Book", selection: $bookFilter) {
                        Text("All books").tag("")
                        ForEach(viewModel.availableBooks, id: \.self) { book in
                            Text(book).tag(book)
                        }
                    }
                    Picker("Topic", selection: $topicFilter) {
                        ForEach(viewModel.availableTopics) { topic in
                            Text(topic.displayName).tag(topic)
                        }
                    }
                } header: {
                    Label("Filters", systemImage: "line.3.horizontal.decrease.circle")
                } footer: {
                    Text("Filters apply to Another verse only. Fixed verses, favorites, history, and Jump to verse always use the selected reference.")
                }

                Section {
                    Toggle("Daily verse notification", isOn: $hasReminder)
                        .onChange(of: hasReminder) { _, enabled in
                            if enabled, reminderTimeString.isEmpty {
                                reminderTime = dateFromTime("07:30") ?? Date()
                            }
                        }
                    if hasReminder {
                        DatePicker("Time", selection: $reminderTime, displayedComponents: .hourAndMinute)
                            .datePickerStyle(.wheel)
                            .labelsHidden()
                        Text(viewModel.reminderDesiredTime.isEmpty
                            ? "Save the desired time to request scheduling."
                            : (viewModel.reminderStatusMessage ?? "Scheduled and active."))
                            .font(.footnote)
                            .foregroundStyle(viewModel.reminderStatusIsError ? Color.red : Color.secondary)
                    } else {
                        Text("Reminder is off.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Label("Reminder", systemImage: "bell")
                } footer: {
                    Text("iOS delivers a local notification at the selected time. It cannot force-open the app while it is in the background.")
                }

                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Verse size")
                            Spacer()
                            Text("\(Int(verseFontSize)) pt")
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $verseFontSize, in: 16...44, step: 1)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Scrim opacity")
                            Spacer()
                            Text("\(Int(scrimOpacity * 100))%")
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $scrimOpacity, in: 0...0.95, step: 0.01)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Animation / reveal speed")
                            Spacer()
                            Text("\(Int(revealSpeed * 100))%")
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $revealSpeed, in: 0...1, step: 0.05)
                    }
                } header: {
                    Label("Appearance", systemImage: "textformat.size")
                } footer: {
                    Text("A zero scrim is fully off. A zero animation speed shows each passage immediately; higher values reveal it faster.")
                }

                Section {
                    Button {
                        isShowingLegal = true
                    } label: {
                        Label("Legal & Privacy", systemImage: "hand.raised")
                    }
                    .accessibilityHint("Opens legal, privacy, cache, and clipboard information")
                } header: {
                    Label("About", systemImage: "info.circle")
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
        .onChange(of: viewModel.settings.apiKey) { _, value in
            apiKey = value
        }
        .sheet(isPresented: $isShowingLegal) {
            LegalPrivacyView()
                .environmentObject(viewModel)
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
        let settings = viewModel.settings
        apiKey = settings.apiKey
        translation = settings.translation
        fixedReference = settings.fixedReference
        bookFilter = settings.bookFilter
        topicFilter = settings.topicFilter
        verseFontSize = settings.verseFontSize
        scrimOpacity = settings.scrimOpacity
        revealSpeed = settings.revealSpeed
        hasReminder = !settings.autoOpenTime.isEmpty
        reminderTime = dateFromTime(settings.autoOpenTime) ?? dateFromTime("07:30") ?? Date()
    }

    private func save() async {
        viewModel.clearSettingsNotice()
        let draft = AppSettings(
            apiKey: apiKey,
            translation: translation,
            fixedReference: fixedReference,
            autoOpenTime: hasReminder ? Self.formatter.string(from: reminderTime) : "",
            bookFilter: bookFilter,
            topicFilter: topicFilter,
            verseFontSize: verseFontSize,
            scrimOpacity: scrimOpacity,
            revealSpeed: revealSpeed
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
