import Foundation
import OSLog
import WebKit

/// The JS <-> native bridge (`window.MiseNative`).
///
/// JS -> native: `webkit.messageHandlers.mise.postMessage({op, id, ...})`
/// native -> JS: `window.MiseNative.onMessage(obj)` via `evaluateJavaScript`, JSON-encoded with
/// JSONSerialization (never string-concatenated).
///
/// Generations run strictly one at a time in FIFO order; the engine is exclusive.
@MainActor
final class NativeBridge: NSObject {
    static let handlerName = "mise"

    /// Injected at document start in the main frame of every page.
    static let userScriptSource = """
    (function () {
      if (window.MiseNative && window.MiseNative.available) { return; }
      window.MiseNative = {
        available: true,
        platform: "ios",
        post: function (msg) { window.webkit.messageHandlers.mise.postMessage(msg); }
      };
    })();
    """

    private let logger = Logger(subsystem: "com.example.mise", category: "Bridge")
    private let service: ModelService
    private let store: StatusStore
    weak var webView: WKWebView?

    private struct Job {
        let id: BridgeID
        let request: GenerateRequest
    }

    private var pending: [Job] = []
    private var isRunning = false
    private var currentJob: Job?
    private var currentProducer: Task<GenerateOutcome, Error>?

    init(service: ModelService, store: StatusStore) {
        self.service = service
        self.store = store
        super.init()
    }

    // MARK: - Native -> JS

    func send(_ object: [String: Any]) {
        guard let webView else { return }
        guard let literal = BridgeMessages.javaScriptLiteral(object) else {
            logger.error("Dropping a bridge message that isn't valid JSON")
            return
        }
        let script = "window.MiseNative && typeof window.MiseNative.onMessage === 'function' && window.MiseNative.onMessage(\(literal));"
        webView.evaluateJavaScript(script, completionHandler: nil)
    }

    func broadcast(_ status: ModelStatus) {
        send(["type": "status", "status": status.jsonObject])
    }

    // MARK: - JS -> native

    fileprivate func handle(_ message: WKScriptMessage) {
        guard message.name == Self.handlerName else { return }
        // Only our own pages, main frame only.
        guard message.frameInfo.isMainFrame,
              AppConfig.trustedHosts.contains(message.frameInfo.securityOrigin.host) else {
            logger.error("Ignoring bridge message from untrusted origin \(message.frameInfo.securityOrigin.host, privacy: .public)")
            return
        }
        guard let body = message.body as? [String: Any], let op = body["op"] as? String else {
            logger.error("Ignoring malformed bridge message")
            return
        }
        let id = BridgeID(body["id"])

        switch op {
        case "status":
            send(["id": id.jsonValue, "ok": true, "status": store.snapshot.jsonObject])

        case "load":
            Task {
                do {
                    try await service.ensureLoaded()
                    send(["id": id.jsonValue, "ok": true, "status": store.snapshot.jsonObject])
                } catch {
                    sendError(id, error)
                }
            }

        case "generate":
            do {
                let request = try BridgeMessages.generateRequest(from: body, token: UUID().uuidString)
                pending.append(Job(id: id, request: request))
                pump()
            } catch {
                sendError(id, error)
            }

        case "cancel":
            cancel(id)

        default:
            send(["id": id.jsonValue, "type": "error", "message": "Unknown op \"\(op)\""])
        }
    }

    // MARK: - Queue

    private func pump() {
        guard !isRunning, !pending.isEmpty else { return }
        isRunning = true
        let job = pending.removeFirst()
        Task {
            await run(job)
            isRunning = false
            pump()
        }
    }

    private func run(_ job: Job) async {
        currentJob = job
        defer {
            currentJob = nil
            currentProducer = nil
        }
        do {
            if !(await service.isReady) {
                // Wait for an in-progress load, but never start a 2.6 GB download from a generate.
                guard service.isModelOnDisk() else { throw NativeModelError.notDownloaded }
                try await service.ensureLoaded()
            }

            let (deltas, continuation) = AsyncStream<String>.makeStream()
            let service = self.service
            let request = job.request
            let producer = Task { () async throws -> GenerateOutcome in
                defer { continuation.finish() }
                return try await service.generate(request) { delta in
                    continuation.yield(delta)
                }
            }
            currentProducer = producer

            for await delta in deltas {
                send(["id": job.id.jsonValue, "type": "chunk", "text": delta])
            }
            let outcome = try await producer.value

            var done: [String: Any] = ["id": job.id.jsonValue, "type": "done", "text": outcome.text]
            if outcome.cancelled { done["cancelled"] = true }
            send(done)
        } catch {
            sendError(job.id, error)
        }
    }

    /// Cancels a queued generation (finishes it immediately) or stops the running one. A cancelled
    /// generation ends with `{id, type:"done", text:<partial>, cancelled:true}`.
    private func cancel(_ id: BridgeID) {
        if let index = pending.firstIndex(where: { $0.id == id }) {
            let job = pending.remove(at: index)
            send(["id": job.id.jsonValue, "type": "done", "text": "", "cancelled": true])
            return
        }
        guard let job = currentJob, job.id == id else { return }
        stopRunning(job)
    }

    /// Stops everything (e.g. the app is going to the background, where iOS forbids GPU work).
    func cancelAll() {
        let queued = pending
        pending.removeAll()
        for job in queued {
            send(["id": job.id.jsonValue, "type": "done", "text": "", "cancelled": true])
        }
        if let job = currentJob { stopRunning(job) }
    }

    private func stopRunning(_ job: Job) {
        let token = job.request.token
        let service = self.service
        Task { await service.cancel(token: token) }
        // Watchdog: if the native stream hasn't wound down shortly after the engine-level cancel,
        // stop waiting for it so the queue can't wedge.
        Task {
            try? await Task.sleep(for: .seconds(3))
            if let current = currentJob, current.request.token == token {
                currentProducer?.cancel()
            }
        }
    }

    private func sendError(_ id: BridgeID, _ error: Error) {
        let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        send(["id": id.jsonValue, "type": "error", "message": message])
    }
}

/// Forwards script messages to the bridge without WKUserContentController retaining it.
@MainActor
final class WeakScriptMessageHandler: NSObject, @preconcurrency WKScriptMessageHandler {
    weak var bridge: NativeBridge?

    init(_ bridge: NativeBridge) {
        self.bridge = bridge
        super.init()
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        bridge?.handle(message)
    }
}
