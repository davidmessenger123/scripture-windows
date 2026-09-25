import CryptoKit
import Foundation
import UserNotifications

enum NotificationReconcileResult: Equatable {
    case disabled
    case unchanged
    case scheduled
    case unauthorized
    case failed(String)
}

enum NotificationSchedulerError: LocalizedError {
    case invalidTime
    case notAuthorized
    case requestFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidTime:
            return "The daily reminder time is invalid."
        case .notAuthorized:
            return "Notifications are not authorized for Scripture."
        case let .requestFailed(message):
            return message
        }
    }
}

@MainActor
final class NotificationScheduler {
    static let dailyIdentifier = "scripture.daily-verse"
    static let maximumNotificationBodyBytes = 500

    private let center: UNUserNotificationCenter
    private let defaults: UserDefaults
    private let dedupeKey = "scripture.daily-verse.dedupe"
    private var scheduling = false
    private var schedulingWaiters: [CheckedContinuation<Void, Never>] = []

    init(
        center: UNUserNotificationCenter = .current(),
        defaults: UserDefaults = .standard
    ) {
        self.center = center
        self.defaults = defaults
    }

    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    func scheduleDaily(hour: Int, minute: Int, passage: Passage? = nil) async throws {
        let result = await reconcileDaily(hour: hour, minute: minute, passage: passage)
        switch result {
        case .disabled, .unchanged, .scheduled:
            return
        case .unauthorized:
            throw NotificationSchedulerError.notAuthorized
        case let .failed(message):
            throw NotificationSchedulerError.requestFailed(message)
        }
    }

    func reconcileDaily(
        hour: Int?,
        minute: Int?,
        passage: Passage?
    ) async -> NotificationReconcileResult {
        await acquireSchedulingLock()
        defer { releaseSchedulingLock() }

        guard let hour, let minute else {
            cancelPendingDaily()
            return .disabled
        }
        guard (0...23).contains(hour), (0...59).contains(minute) else {
            return .failed(NotificationSchedulerError.invalidTime.localizedDescription)
        }

        let status = await authorizationStatus()
        guard isAuthorized(status) else {
            cancelPendingDaily()
            return .unauthorized
        }

        let body = Self.notificationBody(for: passage)
        let reference = passage?.displayReference ?? ""
        let fingerprint = Self.dedupeFingerprint(hour: hour, minute: minute, body: body)
        let requests = center.pendingNotificationRequests()
        let existing = requests.first { $0.identifier == Self.dailyIdentifier }
        if let existing, requestMatches(
            existing,
            body: body,
            reference: reference,
            hour: hour,
            minute: minute
        ) {
            defaults.set(fingerprint, forKey: dedupeKey)
            return .unchanged
        }

        center.removePendingNotificationRequests(withIdentifiers: [Self.dailyIdentifier])
        let request = makeRequest(
            hour: hour,
            minute: minute,
            body: body,
            reference: reference
        )
        do {
            try await center.add(request)
            defaults.set(fingerprint, forKey: dedupeKey)
            return .scheduled
        } catch {
            if let existing {
                try? await center.add(existing)
            }
            return .failed(error.localizedDescription)
        }
    }

    func updateDailyContent(hour: Int, minute: Int, passage: Passage) async {
        _ = await reconcileDaily(hour: hour, minute: minute, passage: passage)
    }

    func cancelDaily() async {
        await acquireSchedulingLock()
        defer { releaseSchedulingLock() }
        cancelPendingDaily()
    }

    nonisolated static func dedupeFingerprint(hour: Int, minute: Int, body: String) -> String {
        let value = Data("\(hour):\(minute)|\(body)".utf8)
        return SHA256.hash(data: value)
            .map { String(format: "%02x", Int($0)) }
            .joined()
    }

    nonisolated static func notificationBody(for passage: Passage?) -> String {
        guard let passage else { return "Your verse of the day is ready." }
        let referencePrefix = "\n\n"
        let labelSuffix = "\n\(passage.displayTranslationName)"
        let referenceBudget = max(
            0,
            maximumNotificationBodyBytes
                - referencePrefix.utf8.count
                - labelSuffix.utf8.count
        )
        let reference = truncateUTF8(
            passage.displayReference,
            maximumBytes: referenceBudget
        )
        let metadata = referencePrefix + reference + labelSuffix
        let textBudget = max(0, maximumNotificationBodyBytes - metadata.utf8.count)
        let text = truncateUTF8(passage.fullText, maximumBytes: textBudget)
        return text + metadata
    }

    nonisolated static func truncateUTF8(_ value: String, maximumBytes: Int) -> String {
        guard maximumBytes > 0 else { return "" }
        var result = ""
        for character in value {
            let candidate = result + String(character)
            if candidate.utf8.count > maximumBytes {
                break
            }
            result = candidate
        }
        return result
    }

    private func acquireSchedulingLock() async {
        if !scheduling {
            scheduling = true
            return
        }
        await withCheckedContinuation { continuation in
            schedulingWaiters.append(continuation)
        }
    }

    private func releaseSchedulingLock() {
        guard !schedulingWaiters.isEmpty else {
            scheduling = false
            return
        }
        let next = schedulingWaiters.removeFirst()
        next.resume()
    }

    private func authorizationStatus() async -> UNAuthorizationStatus {
        await withCheckedContinuation { (continuation: CheckedContinuation<UNAuthorizationStatus, Never>) in
            center.getNotificationSettings { settings in
                continuation.resume(returning: settings.authorizationStatus)
            }
        }
    }

    private func isAuthorized(_ status: UNAuthorizationStatus) -> Bool {
        switch status {
        case .authorized, .provisional, .ephemeral:
            return true
        default:
            return false
        }
    }

    private func makeRequest(
        hour: Int,
        minute: Int,
        body: String,
        reference: String
    ) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = "Scripture"
        content.body = body
        content.sound = .default
        content.userInfo = ["reference": reference]

        var components = DateComponents()
        components.hour = hour
        components.minute = minute
        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: true)
        return UNNotificationRequest(
            identifier: Self.dailyIdentifier,
            content: content,
            trigger: trigger
        )
    }

    private func requestMatches(
        _ request: UNNotificationRequest,
        body: String,
        reference: String,
        hour: Int,
        minute: Int
    ) -> Bool {
        let expectedComponents = DateComponents()
        expectedComponents.hour = hour
        expectedComponents.minute = minute
        guard request.content.title == "Scripture",
              request.content.body == body,
              (request.content.userInfo["reference"] as? String) == reference,
              let trigger = request.trigger as? UNCalendarNotificationTrigger,
              trigger.repeats,
              trigger.timeZone == nil,
              trigger.dateComponents == expectedComponents else {
            return false
        }
        return true
    }

    private func cancelPendingDaily() {
        center.removePendingNotificationRequests(withIdentifiers: [Self.dailyIdentifier])
        defaults.removeObject(forKey: dedupeKey)
    }
}
