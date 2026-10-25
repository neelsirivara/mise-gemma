import Foundation

/// A JS request id, echoed back exactly as received (string or number).
enum BridgeID: Sendable, Hashable {
    case string(String)
    case integer(Int)
    case double(Double)
    case none

    init(_ raw: Any?) {
        switch raw {
        case let s as String:
            self = .string(s)
        case let n as NSNumber:
            let d = n.doubleValue
            if d.isFinite, d == d.rounded(), abs(d) < 9_007_199_254_740_992 {
                self = .integer(n.intValue)
            } else if d.isFinite {
                self = .double(d)
            } else {
                self = .none
            }
        default:
            self = .none
        }
    }

    /// JSON value for replies (`NSNull` when the request had no usable id).
    var jsonValue: Any {
        switch self {
        case .string(let s): return s
        case .integer(let i): return i
        case .double(let d): return d
        case .none: return NSNull()
        }
    }
}

enum BridgeParseError: LocalizedError {
    case badPart(Int, String)
    case tooManyImages(Int)

    var errorDescription: String? {
        switch self {
        case .badPart(let index, let why): return "parts[\(index)]: \(why)"
        case .tooManyImages(let n): return "Too many images (\(n)); the limit is \(AppConfig.maxImagesPerRequest)."
        }
    }
}

enum BridgeMessages {
    /// Builds a `GenerateRequest` from a `{op:"generate", ...}` message body.
    static func generateRequest(from body: [String: Any], token: String) throws -> GenerateRequest {
        let system = body["system"] as? String ?? ""
        let rawParts = body["parts"] as? [Any] ?? []

        var parts: [PromptPart] = []
        var imageCount = 0
        for (index, raw) in rawParts.enumerated() {
            guard let part = raw as? [String: Any] else {
                throw BridgeParseError.badPart(index, "expected an object")
            }
            if let text = part["text"] as? String {
                parts.append(.text(text))
            } else if let image = part["image"] as? String {
                guard let data = decodeBase64(image), !data.isEmpty else {
                    throw BridgeParseError.badPart(index, "image is not valid base64")
                }
                imageCount += 1
                parts.append(.image(data))
            } else if let audio = part["audio"] as? String {
                guard let data = decodeBase64(audio), !data.isEmpty else {
                    throw BridgeParseError.badPart(index, "audio is not valid base64")
                }
                parts.append(.audio(data))
            } else {
                throw BridgeParseError.badPart(index, "expected one of text, image, audio")
            }
        }
        if imageCount > AppConfig.maxImagesPerRequest {
            throw BridgeParseError.tooManyImages(imageCount)
        }

        let requestedMax = (body["maxTokens"] as? NSNumber)?.intValue ?? AppConfig.defaultMaxOutputTokens
        let maxTokens = min(max(requestedMax, 1), AppConfig.maxOutputTokensCap)
        let temperature = (body["temperature"] as? NSNumber)?.doubleValue ?? AppConfig.defaultTemperature

        return GenerateRequest(
            token: token,
            system: system,
            parts: parts,
            maxTokens: maxTokens,
            temperature: temperature
        )
    }

    /// Decodes base64, tolerating an accidental `data:<mime>;base64,` prefix and whitespace.
    static func decodeBase64(_ string: String) -> Data? {
        var payload = Substring(string)
        if payload.hasPrefix("data:"), let comma = payload.firstIndex(of: ",") {
            payload = payload[payload.index(after: comma)...]
        }
        return Data(base64Encoded: String(payload), options: .ignoreUnknownCharacters)
    }

    /// Serializes a reply as a JS expression. JSONSerialization does the escaping; U+2028/2029
    /// are escaped too so the result is a valid script on every JS engine.
    static func javaScriptLiteral(_ object: [String: Any]) -> String? {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object),
              let json = String(data: data, encoding: .utf8) else { return nil }
        return json
            .replacingOccurrences(of: "\u{2028}", with: "\\u2028")
            .replacingOccurrences(of: "\u{2029}", with: "\\u2029")
    }
}
