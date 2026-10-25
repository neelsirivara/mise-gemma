import Foundation

/// Where the web UI is loaded from.
enum WebSource: String, Sendable {
    /// The hosted app at https://mise-gemma.vercel.app (default). Falls back to `bundled`
    /// automatically when the network is unreachable.
    case remote
    /// The copy of `web/` bundled into the app, served from `http://localhost:<port>` by
    /// `LocalWebServer` (localhost is a secure context, so camera/mic keep working).
    case bundled
}

/// App-wide constants. Everything tunable lives here.
enum AppConfig {
    static let defaultRemoteURLString = "https://mise-gemma.vercel.app/?engine=native"

    /// Path + query loaded from the bundled server ("/" is rewritten to /mise/index.html,
    /// mirroring web/vercel.json).
    static let bundledPathAndQuery = "/?engine=native"

    /// Fixed loopback port so the bundled page keeps the same origin (and therefore the same
    /// localStorage / IndexedDB) across launches. Falls back to any free port if taken.
    static let localServerPort: UInt16 = 47863

    /// Model identity reported to the web app.
    static let modelName = "gemma-4-E2B-it"

    /// KV-cache size (input + output tokens) for the engine. Gemma 4 E2B handles far more, but
    /// 4096 keeps the working set modest on a phone while leaving room for a long system
    /// prompt, a photo (~280 visual tokens) and a full recipe answer.
    static let maxContextTokens = 4096

    /// Upper bound for a single request's `maxTokens`.
    static let maxOutputTokensCap = 2048
    static let defaultMaxOutputTokens = 1024
    static let defaultTemperature = 0.7

    /// Images allowed in one request (engine default is 1; each costs visual tokens).
    static let maxImagesPerRequest = 8

    /// Hosts whose pages may use the native bridge and get camera/mic without a prompt from us.
    static var trustedHosts: Set<String> {
        var hosts: Set<String> = ["mise-gemma.vercel.app", "localhost", "127.0.0.1"]
        if let host = remoteURL.host() { hosts.insert(host) }
        return hosts
    }

    /// Selected web source: `MISE_WEB_SOURCE` env var (scheme) > Info.plist `MiseWebSource`
    /// (build setting) > `.remote`.
    static var webSource: WebSource {
        if let env = ProcessInfo.processInfo.environment["MISE_WEB_SOURCE"],
           let source = WebSource(rawValue: env.lowercased()) {
            return source
        }
        if let plist = Bundle.main.object(forInfoDictionaryKey: "MiseWebSource") as? String,
           let source = WebSource(rawValue: plist.lowercased()) {
            return source
        }
        return .remote
    }

    /// Hosted page URL (`MISE_REMOTE_URL` env var overrides, e.g. a Vercel preview).
    static var remoteURL: URL {
        if let env = ProcessInfo.processInfo.environment["MISE_REMOTE_URL"],
           let url = URL(string: env), url.scheme == "https" {
            return url
        }
        // A compile-time constant; this cannot fail.
        return URL(string: defaultRemoteURLString)!
    }

    /// The bundled copy of `web/` (folder reference added by project.yml), if present.
    static var bundledWebRoot: URL? {
        guard let url = Bundle.main.url(forResource: "web", withExtension: nil) else { return nil }
        let index = url.appendingPathComponent("mise/index.html")
        return FileManager.default.fileExists(atPath: index.path) ? url : nil
    }
}
