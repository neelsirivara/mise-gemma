import Foundation
import OSLog
@preconcurrency import Network

/// A tiny static-file HTTP/1.1 server on the loopback interface (Network.framework, no deps).
///
/// Used for "bundled" mode and as the offline fallback: the page is served from
/// `http://localhost:<port>`, which WebKit treats as a secure context, so `getUserMedia` keeps
/// working (a custom WKURLSchemeHandler scheme is not reliably a secure context on iOS).
///
/// All mutable state is confined to `queue`.
final class LocalWebServer: @unchecked Sendable {
    private let root: URL
    private let rootPath: String
    private let queue = DispatchQueue(label: "com.example.mise.localserver")
    private let logger = Logger(subsystem: "com.example.mise", category: "LocalWebServer")

    private var listener: NWListener?
    private var readyPort: UInt16?
    private var preferredPort: UInt16

    init(root: URL, preferredPort: UInt16 = AppConfig.localServerPort) {
        self.root = root.standardizedFileURL
        self.rootPath = root.standardizedFileURL.path
        self.preferredPort = preferredPort
    }

    /// Starts the server if needed and returns its port. Safe to call repeatedly (e.g. on every
    /// return to the foreground, since iOS may tear the listener down while suspended).
    func start() async throws -> UInt16 {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<UInt16, Error>) in
            let box = ResumeOnce(continuation)
            queue.async { self.startOnQueue(usePreferredPort: true, box: box) }
        }
    }

    private func startOnQueue(usePreferredPort: Bool, box: ResumeOnce) {
        if let port = readyPort, listener != nil {
            box.resume(.success(port))
            return
        }
        listener?.cancel()
        listener = nil

        let parameters = NWParameters.tcp
        parameters.requiredInterfaceType = .loopback
        parameters.allowLocalEndpointReuse = true

        let port: NWEndpoint.Port = usePreferredPort ? (NWEndpoint.Port(rawValue: preferredPort) ?? .any) : .any
        let newListener: NWListener
        do {
            newListener = try NWListener(using: parameters, on: port)
        } catch {
            if usePreferredPort {
                startOnQueue(usePreferredPort: false, box: box)
            } else {
                box.resume(.failure(error))
            }
            return
        }

        newListener.stateUpdateHandler = { [weak self, weak newListener] state in
            guard let self, let newListener else { return }
            switch state {
            case .ready:
                let actual = newListener.port?.rawValue ?? self.preferredPort
                self.readyPort = actual
                self.preferredPort = actual  // keep the same origin on restarts
                self.logger.info("Serving bundled web app on http://localhost:\(actual)")
                box.resume(.success(actual))
            case .failed(let error):
                self.logger.error("Listener failed: \(error.localizedDescription, privacy: .public)")
                newListener.cancel()
                if self.listener === newListener {
                    self.listener = nil
                    self.readyPort = nil
                }
                if usePreferredPort && !box.isResumed {
                    self.startOnQueue(usePreferredPort: false, box: box)
                } else {
                    box.resume(.failure(error))
                }
            case .cancelled:
                if self.listener === newListener {
                    self.listener = nil
                    self.readyPort = nil
                }
            default:
                break
            }
        }
        newListener.newConnectionHandler = { [weak self] connection in
            self?.accept(connection)
        }
        listener = newListener
        newListener.start(queue: queue)
    }

    // MARK: - Connections

    private func accept(_ connection: NWConnection) {
        connection.start(queue: queue)
        receiveHead(on: connection, buffer: Data())
    }

    private func receiveHead(on connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, isComplete, error in
            guard let self else {
                connection.cancel()
                return
            }
            var buffer = buffer
            if let data { buffer.append(data) }
            if let end = buffer.range(of: Data("\r\n\r\n".utf8)) {
                self.respond(on: connection, head: buffer.subdata(in: buffer.startIndex..<end.lowerBound))
            } else if error != nil || isComplete || buffer.count > 64 * 1024 {
                connection.cancel()
            } else {
                self.receiveHead(on: connection, buffer: buffer)
            }
        }
    }

    private func respond(on connection: NWConnection, head: Data) {
        let headText = String(decoding: head, as: UTF8.self)
        let requestLine = headText.components(separatedBy: "\r\n").first ?? ""
        let pieces = requestLine.split(separator: " ")
        guard pieces.count >= 2 else {
            send(on: connection, status: "400 Bad Request", type: "text/plain", body: Data("Bad Request".utf8))
            return
        }
        let method = String(pieces[0])
        guard method == "GET" || method == "HEAD" else {
            send(on: connection, status: "405 Method Not Allowed", type: "text/plain", body: Data("Method Not Allowed".utf8))
            return
        }

        guard let fileURL = resolve(target: String(pieces[1])),
              let body = try? Data(contentsOf: fileURL, options: .mappedIfSafe) else {
            send(on: connection, status: "404 Not Found", type: "text/plain", body: Data("Not Found".utf8))
            return
        }
        send(on: connection, status: "200 OK", type: Self.mimeType(for: fileURL.pathExtension),
             body: body, headOnly: method == "HEAD")
    }

    /// Maps a request target to a file under `root`, refusing anything that escapes it.
    private func resolve(target: String) -> URL? {
        var path = target
        if let cut = path.firstIndex(where: { $0 == "?" || $0 == "#" }) {
            path = String(path[..<cut])
        }
        guard let decoded = path.removingPercentEncoding, decoded.hasPrefix("/") else { return nil }
        // Mirror web/vercel.json: "/" serves the Mise app.
        let relative = decoded == "/" ? "mise/index.html" : String(decoded.dropFirst())

        var url = root.appendingPathComponent(relative).standardizedFileURL
        guard url.path == rootPath || url.path.hasPrefix(rootPath + "/") else { return nil }

        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) else { return nil }
        if isDirectory.boolValue {
            url = url.appendingPathComponent("index.html")
            guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        }
        return url
    }

    private func send(on connection: NWConnection, status: String, type: String, body: Data, headOnly: Bool = false) {
        let header = [
            "HTTP/1.1 \(status)",
            "Content-Type: \(type)",
            "Content-Length: \(body.count)",
            "Cache-Control: no-cache",
            "Permissions-Policy: camera=(self), microphone=(self)",
            "X-Content-Type-Options: nosniff",
            "Connection: close",
            "",
            "",
        ].joined(separator: "\r\n")
        var payload = Data(header.utf8)
        if !headOnly { payload.append(body) }
        connection.send(content: payload, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private static func mimeType(for ext: String) -> String {
        switch ext.lowercased() {
        case "html", "htm": return "text/html; charset=utf-8"
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "json", "map": return "application/json; charset=utf-8"
        case "webmanifest": return "application/manifest+json; charset=utf-8"
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "gif": return "image/gif"
        case "webp": return "image/webp"
        case "ico": return "image/x-icon"
        case "woff": return "font/woff"
        case "woff2": return "font/woff2"
        case "ttf": return "font/ttf"
        case "otf": return "font/otf"
        case "wav": return "audio/wav"
        case "mp3": return "audio/mpeg"
        case "m4a": return "audio/mp4"
        case "mp4": return "video/mp4"
        case "txt", "md": return "text/plain; charset=utf-8"
        default: return "application/octet-stream"
        }
    }
}

/// Resumes a checked continuation at most once (listener state callbacks can repeat).
private final class ResumeOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<UInt16, Error>?

    init(_ continuation: CheckedContinuation<UInt16, Error>) {
        self.continuation = continuation
    }

    var isResumed: Bool {
        lock.lock()
        defer { lock.unlock() }
        return continuation == nil
    }

    func resume(_ result: Result<UInt16, Error>) {
        lock.lock()
        let pending = continuation
        continuation = nil
        lock.unlock()
        pending?.resume(with: result)
    }
}
