import Foundation
import Observation
import os
@preconcurrency import Network
import SwiftUI

/// App-level state: owns the model service, the web host, and what the setup overlay shows.
@MainActor
@Observable
final class AppModel {
    private(set) var status: ModelStatus
    /// On cellular (or another "expensive" network) we ask before pulling 2.6 GB.
    private(set) var needsDownloadConsent = false
    /// The user chose to use the web app without the on-device model for now.
    var overlayDismissed = false

    let store: StatusStore
    let service: ModelService
    let web: WebHost
    @ObservationIgnored private var started = false

    var showsSetupOverlay: Bool { !status.ready && !overlayDismissed }

    init() {
        let store = StatusStore()
        let service = ModelService(store: store)
        self.store = store
        self.service = service
        self.web = WebHost(service: service, store: store)
        self.status = store.snapshot
        Task { await self.observeStatus() }
    }

    private func observeStatus() async {
        for await next in store.updates {
            status = next
            web.bridge.broadcast(next)
        }
    }

    /// Called once when the UI appears: load the page and start the model.
    func start() {
        guard !started else { return }
        started = true
        web.loadInitialPage()
        Task {
            if service.isModelOnDisk() {
                await loadModel()
                return
            }
            switch await NetworkCheck.current() {
            case .unmetered:
                await loadModel()
            case .expensive:
                needsDownloadConsent = true
            case .offline:
                store.update { $0.error = "No internet connection. Connect to Wi-Fi to download the on-device model (one time, about 2.6 GB)." }
            }
        }
    }

    func loadModel() async {
        needsDownloadConsent = false
        do {
            try await service.ensureLoaded()
        } catch {
            // ModelService already put a readable message into `status.error`.
        }
    }

    func retry() {
        Task { await loadModel() }
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        switch phase {
        case .background:
            // iOS doesn't allow GPU work in the background; stop generating cleanly.
            web.bridge.cancelAll()
        case .active:
            web.appDidBecomeActive()
        default:
            break
        }
    }
}

/// One-shot check of the current network path.
enum NetworkCheck {
    enum Kind: Sendable { case unmetered, expensive, offline }

    static func current() async -> Kind {
        await withCheckedContinuation { (continuation: CheckedContinuation<Kind, Never>) in
            let monitor = NWPathMonitor()
            let once = OSAllocatedUnfairLock(initialState: false)
            monitor.pathUpdateHandler = { path in
                let first = once.withLock { done -> Bool in
                    if done { return false }
                    done = true
                    return true
                }
                guard first else { return }
                monitor.cancel()
                if path.status != .satisfied {
                    continuation.resume(returning: .offline)
                } else if path.isExpensive || path.isConstrained {
                    continuation.resume(returning: .expensive)
                } else {
                    continuation.resume(returning: .unmetered)
                }
            }
            monitor.start(queue: DispatchQueue(label: "com.example.mise.pathcheck"))
        }
    }
}
