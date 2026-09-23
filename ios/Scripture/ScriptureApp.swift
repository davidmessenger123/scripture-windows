import SwiftUI

@main
@MainActor
struct ScriptureApp: App {
    @StateObject private var viewModel = ScriptureViewModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            VerseView()
                .environmentObject(viewModel)
                .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { _, phase in
            viewModel.handleScenePhase(phase)
        }
    }
}
