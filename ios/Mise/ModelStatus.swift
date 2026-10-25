import Foundation
import os

/// Snapshot of the on-device model's state. Mirrors the `status` object in the JS bridge contract.
struct ModelStatus: Sendable, Equatable {
    var ready = false
    var downloading = false
    /// Engine bring-up in progress (after the download, before `ready`). Extra field, not in the
    /// minimal contract; harmless for the web side to ignore.
    var loading = false
    var progress: Double = 0
    var bytes: Int64 = 0
    var total: Int64 = 0
    var model = AppConfig.modelName
    /// "gpu" or "cpu": the backend in use once ready, or the one we will try first.
    var backend = "gpu"
    var error: String?
    var vision = false
    var audio = false

    /// JSON-ready dictionary for the bridge (only plist/JSON-safe types).
    var jsonObject: [String: Any] {
        var dict: [String: Any] = [
            "ready": ready,
            "downloading": downloading,
            "loading": loading,
            "progress": progress.isFinite ? min(max(progress, 0), 1) : 0,
            "bytes": NSNumber(value: bytes),
            "total": NSNumber(value: total),
            "model": model,
            "backend": backend,
            "vision": vision,
            "audio": audio,
        ]
        if let error { dict["error"] = error }
        return dict
    }
}

/// Thread-safe holder for the current `ModelStatus` that also publishes every change, in order,
/// on `updates` (single consumer: `AppModel`).
final class StatusStore: Sendable {
    private let state = OSAllocatedUnfairLock(initialState: ModelStatus())
    private let continuation: AsyncStream<ModelStatus>.Continuation
    let updates: AsyncStream<ModelStatus>

    init() {
        let (stream, continuation) = AsyncStream<ModelStatus>.makeStream(
            bufferingPolicy: .bufferingNewest(32))
        self.updates = stream
        self.continuation = continuation
    }

    var snapshot: ModelStatus {
        state.withLock { $0 }
    }

    /// Mutates the status under the lock and publishes the result (yield happens inside the lock
    /// so observers always see updates in mutation order).
    func update(_ body: @Sendable (inout ModelStatus) -> Void) {
        let continuation = self.continuation
        state.withLock { status in
            let before = status
            body(&status)
            if status != before { continuation.yield(status) }
        }
    }
}
