import SwiftUI

struct JumpView: View {
    @EnvironmentObject private var viewModel: ScriptureViewModel
    @Environment(\.dismiss) private var dismiss
    @FocusState private var isFocused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("John 3:16", text: $viewModel.jumpText)
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                        .focused($isFocused)
                } header: {
                    Text("Scripture reference")
                } footer: {
                    Text("Enter a book, chapter, and verse, such as John 3:16.")
                }
            }
            .navigationTitle("Jump to a verse")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Go") {
                        Task { await viewModel.submitJump() }
                    }
                    .disabled(viewModel.jumpText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
        .onAppear { isFocused = true }
    }
}
