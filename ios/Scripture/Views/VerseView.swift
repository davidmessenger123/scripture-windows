import SwiftUI

struct VerseView: View {
    @EnvironmentObject private var viewModel: ScriptureViewModel
    @Environment(\.openURL) private var openURL

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.035, green: 0.047, blue: 0.067), .black],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 0) {
                    header
                    Spacer(minLength: 28)
                    passageContent
                    Spacer(minLength: 28)
                    favoritesSection
                    statusMessages
                    footer
                }
                .frame(maxWidth: 900)
                .padding(.horizontal, 24)
                .padding(.top, 18)
                .padding(.bottom, 28)
                .frame(maxWidth: .infinity)
            }
            .scrollIndicators(.hidden)
            .refreshable {
                await viewModel.refresh()
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                primaryControls
                    .padding(.horizontal, 16)
                    .padding(.top, 10)
                    .padding(.bottom, 8)
                    .background(.ultraThinMaterial)
            }

            if viewModel.isLoading && viewModel.passage == nil {
                ProgressView()
                    .tint(.white)
                    .scaleEffect(1.2)
            } else if viewModel.isLoading {
                VStack {
                    HStack {
                        Spacer()
                        ProgressView()
                            .tint(Color(red: 0.98, green: 0.66, blue: 0.41))
                            .padding(.trailing, 24)
                            .padding(.top, 18)
                    }
                    Spacer()
                }
            }
        }
        .task {
            await viewModel.loadInitialIfNeeded()
        }
        .sheet(isPresented: $viewModel.isShowingSettings) {
            SettingsView()
                .environmentObject(viewModel)
        }
        .sheet(isPresented: $viewModel.isShowingJump) {
            JumpView()
                .environmentObject(viewModel)
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 3) {
                Text("SCRIPTURE")
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                    .tracking(3)
                    .foregroundStyle(Color(red: 0.98, green: 0.66, blue: 0.41))
                Text("A verse for today")
                    .font(.system(size: 13, weight: .regular))
                    .foregroundStyle(.white.opacity(0.5))
            }
            Spacer()
            Button {
                viewModel.isShowingSettings = true
            } label: {
                Image(systemName: "gearshape")
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(.white.opacity(0.8))
                    .frame(width: 42, height: 42)
                    .background(Circle().fill(Color.white.opacity(0.08)))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Settings")
        }
    }

    private var revealedText: Text {
        let before = Text(viewModel.visibleBefore)
            .foregroundStyle(.white.opacity(0.55))
        let focal = Text(viewModel.visibleFocal)
            .foregroundStyle(.white)
        let after = Text(viewModel.visibleAfter)
            .foregroundStyle(.white.opacity(0.55))
        let beforeSeparator = viewModel.visibleBefore.isEmpty || viewModel.visibleFocal.isEmpty
            ? Text("")
            : Text(" ")
        let focalSeparator = viewModel.visibleFocal.isEmpty || viewModel.visibleAfter.isEmpty
            ? Text("")
            : Text(" ")
        return before + beforeSeparator + focal + focalSeparator + after
    }

    @ViewBuilder
    private var passageContent: some View {
        if let passage = viewModel.passage {
            let isLongPassage = passage.fullText.count > 450
            VStack(spacing: 20) {
                Text(passage.translationName.uppercased())
                    .font(.system(size: 11, weight: .bold, design: .rounded))
                    .tracking(2.2)
                    .foregroundStyle(.white.opacity(0.55))

                revealedText
                    .font(.system(size: isLongPassage ? 22 : 28, weight: .light, design: .serif))
                    .lineSpacing(isLongPassage ? 5 : 9)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 780)
                    .minimumScaleFactor(0.72)
                    .animation(.easeOut(duration: 0.08), value: viewModel.revealedCharacters)

                Text(passage.reference.uppercased())
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                    .tracking(1.7)
                    .foregroundStyle(Color(red: 0.98, green: 0.66, blue: 0.41))
                    .padding(.top, 2)
            }
            .frame(maxWidth: .infinity)
        } else {
            VStack(spacing: 14) {
                CrossMark(opacity: 0.35, size: 58)
                Text(viewModel.isLoading ? "Preparing your verse…" : "Your verse will appear here")
                    .font(.system(size: 17, weight: .regular, design: .serif))
                    .foregroundStyle(.white.opacity(0.65))
            }
            .frame(maxWidth: .infinity, minHeight: 260)
        }
    }

    private var primaryControls: some View {
        VStack(spacing: 14) {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                ScriptureActionButton(
                    title: "Previous",
                    systemImage: "chevron.left",
                    isDisabled: !viewModel.canGoBack
                ) {
                    Task { await viewModel.goBack() }
                }
                ScriptureActionButton(
                    title: "Next",
                    systemImage: "chevron.right",
                    isDisabled: !viewModel.canGoForward
                ) {
                    Task { await viewModel.goForward() }
                }
                ScriptureActionButton(
                    title: viewModel.settings.fixedReference.isEmpty ? "Another verse" : "Repeat verse",
                    systemImage: "arrow.clockwise",
                    isProminent: true,
                    isDisabled: viewModel.isLoading
                ) {
                    Task { await viewModel.refresh() }
                }
                ScriptureActionButton(
                    title: viewModel.isFavorite ? "Saved" : "Favorite",
                    systemImage: viewModel.isFavorite ? "star.fill" : "star",
                    tint: viewModel.isFavorite ? Color(red: 0.96, green: 0.77, blue: 0.26) : .white,
                    isDisabled: viewModel.currentAnchor.isEmpty || viewModel.isLoading
                ) {
                    viewModel.toggleFavorite()
                }
                ScriptureActionButton(
                    title: "Read online",
                    systemImage: "safari",
                    isDisabled: viewModel.browserURL == nil || viewModel.isLoading
                ) {
                    if let url = viewModel.browserURL {
                        openURL(url)
                    }
                }
                ScriptureActionButton(
                    title: "Jump to verse",
                    systemImage: "text.cursor",
                    isDisabled: viewModel.isLoading
                ) {
                    viewModel.jumpText = ""
                    viewModel.isShowingJump = true
                }
            }
        }
    }

    @ViewBuilder
    private var favoritesSection: some View {
        if !viewModel.favoriteChips.isEmpty {
            VStack(alignment: .leading, spacing: 9) {
                Text("FAVORITES")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .tracking(2)
                    .foregroundStyle(.white.opacity(0.45))
                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(viewModel.favoriteChips, id: \.self) { favorite in
                            Button {
                                Task { await viewModel.loadFavorite(favorite) }
                            } label: {
                                Text(favorite)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(viewModel.currentAnchor == favorite ? .white : .white.opacity(0.65))
                                    .padding(.horizontal, 11)
                                    .padding(.vertical, 8)
                                    .background(
                                        Capsule().fill(Color.white.opacity(viewModel.currentAnchor == favorite ? 0.16 : 0.07))
                                    )
                            }
                            .buttonStyle(.plain)
                        }
                        if viewModel.favoriteOverflow > 0 {
                            Text("+\(viewModel.favoriteOverflow) more")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(.white.opacity(0.45))
                                .padding(.horizontal, 8)
                        }
                    }
                }
                .scrollIndicators(.hidden)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private var statusMessages: some View {
        VStack(spacing: 8) {
            if let notice = viewModel.notice {
                NoticeBanner(text: notice, isError: false)
            }
            if let error = viewModel.errorMessage {
                NoticeBanner(text: error, isError: true)
            }
        }
        .padding(.top, 18)
    }

    private var footer: some View {
        Text("Your daily reminder is managed in Settings.")
            .font(.system(size: 11, weight: .regular))
            .foregroundStyle(.white.opacity(0.35))
            .frame(maxWidth: .infinity)
            .padding(.top, 22)
    }
}
