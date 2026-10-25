import Foundation
import OSLog
// The LiteRT-LM Swift wrapper is compiled in Swift 5 mode and its types (Engine's
// Conversation, Message, ConversationConfig...) are not annotated Sendable. @preconcurrency
// keeps Swift 6 from flagging the unavoidable hand-offs to/from the `Engine` actor.
@preconcurrency import LiteRTLM
@preconcurrency import LiteRTFoundation

/// One piece of a user turn, already decoded from the bridge's base64.
enum PromptPart: Sendable {
    case text(String)
    case image(Data)   // JPEG/PNG bytes
    case audio(Data)   // 16 kHz mono WAV bytes
}

/// A single-turn generation request (fresh conversation each time; no hidden history).
struct GenerateRequest: Sendable {
    /// Unique per request (not the JS id, which may repeat); used for cancellation.
    let token: String
    let system: String
    let parts: [PromptPart]
    let maxTokens: Int
    let temperature: Double

    var hasImage: Bool { parts.contains { if case .image = $0 { true } else { false } } }
    var hasAudio: Bool { parts.contains { if case .audio = $0 { true } else { false } } }
}

struct GenerateOutcome: Sendable {
    let text: String
    let cancelled: Bool
}

enum NativeModelError: LocalizedError {
    case notDownloaded
    case notReady
    case emptyPrompt
    case visionUnavailable
    case audioUnavailable
    case insufficientDisk(needed: Int64, available: Int64)

    var errorDescription: String? {
        switch self {
        case .notDownloaded:
            return "The on-device model hasn't been downloaded yet."
        case .notReady:
            return "The on-device model isn't loaded yet."
        case .emptyPrompt:
            return "The request had no text, image or audio."
        case .visionUnavailable:
            return "Image input isn't available with the current on-device engine."
        case .audioUnavailable:
            return "Audio input isn't available with the current on-device engine."
        case .insufficientDisk(let needed, let available):
            let need = ByteCountFormatter.string(fromByteCount: needed, countStyle: .file)
            let have = ByteCountFormatter.string(fromByteCount: available, countStyle: .file)
            return "Not enough free storage for the model: need about \(need), have \(have)."
        }
    }
}

/// Owns the model file, the LiteRT-LM `Engine`, and the one-at-a-time generation.
///
/// Built on john-rocky/swift-litert-lm 0.2.0:
/// - download: `LiteRTChat.ensureModel(_:storageDirectory:onProgress:)` (chunked, resumable,
///   single-flight, stores in Application Support/LiteRTModels, excluded from backup)
/// - inference: the vendored official wrapper (`Engine`, `EngineConfig`, `ConversationConfig`,
///   `Conversation.sendMessageStream`). We don't use `LiteRTChat` for generation because it
///   keeps one conversation with history; the bridge needs a fresh conversation per request with
///   its own system prompt.
actor ModelService {
    private let logger = Logger(subsystem: "com.example.mise", category: "ModelService")
    private let catalogModel = LiteRTModel.gemma4_E2B
    let store: StatusStore

    private var engine: Engine?
    private var loadTask: Task<Void, Error>?

    // The generation in flight (the bridge guarantees at most one).
    private var activeToken: String?
    private var activeConversation: Conversation?
    private var cancelledTokens: Set<String> = []

    init(store: StatusStore) {
        self.store = store
        if let url = Self.modelFileURL, let size = Self.fileSize(url) {
            store.update {
                $0.bytes = size
                $0.total = size
                $0.progress = 1
            }
        } else {
            store.update { $0.total = LiteRTModel.gemma4_E2B.approximateBytes }
        }
    }

    // MARK: - Model file

    /// Application Support/LiteRTModels/gemma-4-E2B-it.litertlm (the package's default location).
    static var modelFileURL: URL? {
        guard let dir = try? LiteRTChat.defaultStorageDirectory() else { return nil }
        return dir.appendingPathComponent(LiteRTModel.gemma4_E2B.fileName)
    }

    nonisolated func isModelOnDisk() -> Bool {
        guard let url = Self.modelFileURL else { return false }
        return FileManager.default.fileExists(atPath: url.path)
    }

    var isReady: Bool { engine != nil }

    // MARK: - Load (download if needed, then bring up the engine)

    /// Idempotent and single-flight: concurrent callers share one load.
    func ensureLoaded() async throws {
        if engine != nil { return }
        if let loadTask {
            try await loadTask.value
            return
        }
        let task = Task { try await self.performLoad() }
        loadTask = task
        do {
            try await task.value
        } catch {
            loadTask = nil
            throw error
        }
    }

    private func performLoad() async throws {
        store.update { $0.error = nil }

        let path: String
        do {
            path = try await downloadIfNeeded()
        } catch {
            let message = "Model download failed: \(error.localizedDescription)"
            logger.error("\(message, privacy: .public)")
            store.update {
                $0.downloading = false
                $0.error = message
            }
            throw error
        }

        store.update { $0.loading = true }
        do {
            let (engine, backend) = try await startEngine(modelPath: path)
            self.engine = engine
            store.update {
                $0.loading = false
                $0.ready = true
                $0.backend = backend
                $0.vision = true
                $0.audio = true
                $0.error = nil
            }
            logger.info("Engine ready on \(backend, privacy: .public)")
        } catch {
            let message = "Couldn't start Gemma on this iPhone: \(error.localizedDescription)"
            logger.error("\(message, privacy: .public)")
            store.update {
                $0.loading = false
                $0.error = message
            }
            throw error
        }
    }

    private func downloadIfNeeded() async throws -> String {
        let model = catalogModel
        let dir = try LiteRTChat.defaultStorageDirectory()
        Self.excludeFromBackup(dir)
        let dest = dir.appendingPathComponent(model.fileName)

        if let size = Self.fileSize(dest) {
            store.update {
                $0.downloading = false
                $0.bytes = size
                $0.total = size
                $0.progress = 1
            }
            return dest.path
        }

        // Rough free-space check (the .partial file from an interrupted run counts as progress).
        let partial = Self.fileSize(dest.appendingPathExtension("partial")) ?? 0
        let needed = max(model.approximateBytes - partial, 0) + 300_000_000
        if let available = Self.availableCapacity(at: dir), available < needed {
            throw NativeModelError.insufficientDisk(needed: needed, available: available)
        }

        store.update {
            $0.downloading = true
            $0.total = model.approximateBytes
        }
        let store = self.store
        let path = try await LiteRTChat.ensureModel(model, storageDirectory: dir) { progress in
            store.update {
                $0.downloading = true
                $0.bytes = progress.completedBytes
                $0.total = progress.totalBytes
                $0.progress = progress.fraction
            }
        }
        let size = Self.fileSize(dest) ?? model.approximateBytes
        store.update {
            $0.downloading = false
            $0.bytes = size
            $0.total = size
            $0.progress = 1
        }
        return path
    }

    /// GPU first (retried once: bring-up can fail transiently right after a relaunch while the
    /// previous process's memory is reclaimed), then CPU. Vision and audio encoders always run
    /// on CPU: the Gemma 4 E2B .litertlm pins audio to CPU, and the Metal delegate can't prepare
    /// the vision encoder on iOS (both device-verified by swift-litert-lm).
    private func startEngine(modelPath: String) async throws -> (Engine, String) {
        ExperimentalFlags.optIntoExperimentalAPIs()
        // The MTP drafter is flaky on this runtime build and gives no speedup (per the package).
        ExperimentalFlags.enableSpeculativeDecoding = false

        let cacheDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?.path
        let attempts: [(backend: Backend, label: String)] = [(.gpu, "gpu"), (.gpu, "gpu"), (.cpu(), "cpu")]
        var lastError: Error = NativeModelError.notReady

        for (index, attempt) in attempts.enumerated() {
            if index > 0 { try? await Task.sleep(for: .seconds(2.5)) }
            store.update { $0.backend = attempt.label }
            do {
                let config = try EngineConfig(
                    modelPath: modelPath,
                    backend: attempt.backend,
                    visionBackend: .cpu(),
                    audioBackend: .cpu(),
                    maxNumTokens: AppConfig.maxContextTokens,
                    cacheDir: cacheDir,
                    maxNumImages: AppConfig.maxImagesPerRequest
                )
                let engine = Engine(engineConfig: config)
                try await engine.initialize()
                // Creating a conversation is where a bad tower/backend combination surfaces
                // (INTERNAL errors), so verify it here instead of on the first real request.
                _ = try await engine.createConversation(
                    with: ConversationConfig(visualTokenBudget: catalogModel.defaultVisualTokenBudget))
                return (engine, attempt.label)
            } catch {
                logger.error("Engine start on \(attempt.label, privacy: .public) failed: \(error.localizedDescription, privacy: .public)")
                lastError = error
            }
        }
        throw lastError
    }

    // MARK: - Generate

    /// Runs one single-turn generation, calling `onDelta` for each streamed text piece.
    /// Returns the full text. A cancelled request returns what was generated so far.
    func generate(
        _ request: GenerateRequest,
        onDelta: @Sendable (String) -> Void
    ) async throws -> GenerateOutcome {
        guard let engine else { throw NativeModelError.notReady }
        let status = store.snapshot
        if request.hasImage && !status.vision { throw NativeModelError.visionUnavailable }
        if request.hasAudio && !status.audio { throw NativeModelError.audioUnavailable }

        let contents: [Content] = request.parts.compactMap { part -> Content? in
            switch part {
            case .text(let text): return text.isEmpty ? nil : .text(text)
            case .image(let data): return .imageData(data)
            case .audio(let data): return .audioData(data)
            }
        }
        guard !contents.isEmpty else { throw NativeModelError.emptyPrompt }

        let trimmedSystem = request.system.trimmingCharacters(in: .whitespacesAndNewlines)
        let systemMessage: Message? = trimmedSystem.isEmpty ? nil : Message(trimmedSystem, role: .system)
        let sampler = try Self.sampler(temperature: request.temperature)
        let config = ConversationConfig(
            systemMessage: systemMessage,
            samplerConfig: sampler,
            visualTokenBudget: request.hasImage ? catalogModel.defaultVisualTokenBudget : nil
        )

        let conversation = try await engine.createConversation(with: config)
        activeToken = request.token
        activeConversation = conversation
        defer {
            activeToken = nil
            activeConversation = nil
        }
        if cancelledTokens.contains(request.token) {
            cancelledTokens.remove(request.token)
            return GenerateOutcome(text: "", cancelled: true)
        }

        let message = Message(contents: contents, role: .user)
        let maxOutput = request.maxTokens > 0 ? request.maxTokens : nil
        var full = ""
        do {
            for try await chunk in conversation.sendMessageStream(message, maxOutputTokens: maxOutput) {
                let delta = chunk.toString
                if !delta.isEmpty {
                    full += delta
                    onDelta(delta)
                }
            }
        } catch {
            if cancelledTokens.remove(request.token) != nil || Task.isCancelled {
                return GenerateOutcome(text: full, cancelled: true)
            }
            throw error
        }
        let cancelled = cancelledTokens.remove(request.token) != nil || Task.isCancelled
        return GenerateOutcome(text: full, cancelled: cancelled)
    }

    /// Asks the native engine to stop the generation with this token (no-op if it isn't running).
    func cancel(token: String) {
        guard activeToken == token else { return }
        cancelledTokens.insert(token)
        try? activeConversation?.cancel()
    }

    // MARK: - Helpers

    private static func sampler(temperature: Double) throws -> SamplerConfig {
        let t = temperature.isFinite ? min(max(temperature, 0), 2) : AppConfig.defaultTemperature
        if t < 0.01 {
            // Greedy: top-k 1 makes the temperature irrelevant (and avoids a zero divisor).
            return try SamplerConfig(topK: 1, topP: 1, temperature: 0.1)
        }
        return try SamplerConfig(topK: 64, topP: 0.95, temperature: Float(t))
    }

    private static func fileSize(_ url: URL) -> Int64? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attrs[.size] as? NSNumber else { return nil }
        return size.int64Value
    }

    private static func availableCapacity(at url: URL) -> Int64? {
        let values = try? url.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage
    }

    private static func excludeFromBackup(_ url: URL) {
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var target = url
        try? target.setResourceValues(values)
    }
}
