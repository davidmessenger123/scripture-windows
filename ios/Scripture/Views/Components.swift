import SwiftUI

struct ScriptureActionButton: View {
    let title: String
    var systemImage: String? = nil
    var tint: Color = .white
    var isProminent = false
    var isDisabled = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 7) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: 13, weight: .semibold))
                }
                Text(title)
                    .font(.system(size: 13, weight: .medium))
            }
            .foregroundStyle(tint)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 13, style: .continuous)
                    .fill(isProminent ? Color.white.opacity(0.16) : Color.white.opacity(0.07))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 13, style: .continuous)
                    .stroke(Color.white.opacity(0.18), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.35 : 1)
    }
}

struct CrossMark: View {
    var opacity: Double = 0.4
    var size: CGFloat = 72

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.08, style: .continuous)
                .fill(Color.white.opacity(opacity))
                .frame(width: size * 0.27, height: size * 0.82)
            RoundedRectangle(cornerRadius: size * 0.06, style: .continuous)
                .fill(Color.white.opacity(opacity))
                .frame(width: size * 0.78, height: size * 0.25)
        }
        .accessibilityHidden(true)
    }
}

struct NoticeBanner: View {
    let text: String
    let isError: Bool

    var body: some View {
        Text(text)
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(isError ? Color.red.opacity(0.9) : Color.white.opacity(0.65))
            .multilineTextAlignment(.center)
            .frame(maxWidth: 520)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Color.white.opacity(0.06))
            )
    }
}
