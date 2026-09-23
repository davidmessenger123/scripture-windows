import Foundation
import UserNotifications

final class NotificationScheduler {
    private let center = UNUserNotificationCenter.current()
    private let identifier = "scripture.daily-verse"

    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    func scheduleDaily(hour: Int, minute: Int) async throws {
        center.removePendingNotificationRequests(withIdentifiers: [identifier])
        let content = UNMutableNotificationContent()
        content.title = "Scripture"
        content.body = "Your verse of the day is ready."
        content.sound = .default

        var components = DateComponents()
        components.hour = hour
        components.minute = minute
        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: true)
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: trigger)
        try await center.add(request)
    }

    func cancelDaily() {
        center.removePendingNotificationRequests(withIdentifiers: [identifier])
    }
}
