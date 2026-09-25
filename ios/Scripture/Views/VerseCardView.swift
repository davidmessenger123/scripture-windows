import CoreTransferable
import SwiftUI
import UniformTypeIdentifiers
import UIKit

struct VerseCardTransfer: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .png) { item in
            SentTransferredFile(item.url)
        }
    }

    static func write(data: Data, reference: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(filename(for: reference), isDirectory: false)
        try data.write(to: url, options: [.atomic])
        return url
    }

    static func filename(for reference: String) -> String {
        let value = ScriptureReference.cleanProviderText(reference)
        let slug = value
            .unicodeScalars
            .map { scalar -> Character in
                if CharacterSet.alphanumerics.contains(scalar) || scalar.value == 45 {
                    return Character(String(scalar))
                }
                return "-"
            }
            .reduce(into: "") { result, character in
                if result.count < 60 {
                    result.append(character)
                }
            }
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let safeSlug = slug.isEmpty ? "verse" : slug
        return "scripture-verse-\(safeSlug).png"
    }
}

struct VerseCardView: View {
    let passage: Passage
    let fontSize: CGFloat

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.035, green: 0.047, blue: 0.067), .black],
                startPoint: .top,
                endPoint: .bottom
            )
            VStack(spacing: 44) {
                CrossMark(opacity: 0.7, size: 116)
                Text(passage.displayTranslationName.uppercased())
                    .font(.system(size: 24, weight: .bold, design: .rounded))
                    .tracking(5)
                    .foregroundStyle(Color(red: 0.98, green: 0.66, blue: 0.41))
                Text(passage.cardText)
                    .font(.system(size: fontSize, weight: .light, design: .serif))
                    .lineSpacing(size * 0.28)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white)
                    .lineLimit(28)
                    .minimumScaleFactor(0.55)
                    .frame(maxWidth: 880)
                Spacer(minLength: 0)
                Text(passage.displayReference.uppercased())
                    .font(.system(size: 27, weight: .bold, design: .rounded))
                    .tracking(3)
                    .foregroundStyle(Color(red: 0.98, green: 0.66, blue: 0.41))
                Text(passage.displayTranslationName)
                    .font(.system(size: 22, weight: .regular, design: .rounded))
                    .foregroundStyle(.white.opacity(0.55))
            }
            .padding(.horizontal, 100)
            .padding(.vertical, 100)
        }
        .frame(width: 1080, height: 1350)
        .environment(\.colorScheme, .dark)
        .environment(\.locale, Locale(identifier: "en_US_POSIX"))
        .dynamicTypeSize(.large)
    }
}

struct RenderedCardImage: @unchecked Sendable {
    let image: UIImage
}

@MainActor
enum PassageCardRenderer {
    static func renderImage(passage: Passage, fontSize: Double) -> RenderedCardImage? {
        let finiteSize = fontSize.isFinite ? fontSize : 28
        let clampedSize = min(max(finiteSize, 16), 44)
        let size = passage.fullText.count > 450 ? CGFloat(clampedSize) * 0.78 : CGFloat(clampedSize)
        let renderer = ImageRenderer(
            content: VerseCardView(passage: passage, fontSize: size)
        )
        renderer.scale = 1
        renderer.proposedSize = ProposedViewSize(width: 1080, height: 1350)
        guard let image = renderer.uiImage else { return nil }
        return RenderedCardImage(image: image)
    }
}
