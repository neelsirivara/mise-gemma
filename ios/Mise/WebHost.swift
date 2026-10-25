import OSLog
import SwiftUI
import UIKit
import WebKit

/// Owns the full-screen WKWebView, its JS bridge, and (for bundled/offline mode) the local server.
@MainActor
final class WebHost: NSObject {
    let webView: WKWebView
    let bridge: NativeBridge

    private let logger = Logger(subsystem: "com.example.mise", category: "WebHost")
    private let messageHandler: WeakScriptMessageHandler
    private var server: LocalWebServer?
    private var didLoad = false
    private var fellBackToBundled = false

    init(service: ModelService, store: StatusStore) {
        let bridge = NativeBridge(service: service, store: store)
        let handler = WeakScriptMessageHandler(bridge)

        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.websiteDataStore = .default()
        configuration.applicationNameForUserAgent = "MiseiOS/1.0"
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: NativeBridge.userScriptSource,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        configuration.userContentController.add(handler, name: NativeBridge.handlerName)

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 0.12, green: 0.105, blue: 0.086, alpha: 1)
        webView.scrollView.backgroundColor = webView.backgroundColor
        // The page uses viewport-fit=cover + env(safe-area-inset-*); let it own the insets.
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.allowsBackForwardNavigationGestures = false
        #if DEBUG
        webView.isInspectable = true  // Safari > Develop > [iPhone] > Mise
        #endif

        self.webView = webView
        self.bridge = bridge
        self.messageHandler = handler
        super.init()

        bridge.webView = webView
        webView.uiDelegate = self
        webView.navigationDelegate = self
    }

    // MARK: - Loading

    func loadInitialPage() {
        guard !didLoad else { return }
        didLoad = true
        switch AppConfig.webSource {
        case .remote:
            loadRemote()
        case .bundled:
            Task { await loadBundled() }
        }
    }

    private func loadRemote() {
        let request = URLRequest(
            url: AppConfig.remoteURL,
            cachePolicy: .useProtocolCachePolicy,
            timeoutInterval: 20
        )
        webView.load(request)
    }

    private func loadBundled() async {
        guard let root = AppConfig.bundledWebRoot else {
            showErrorPage("The bundled copy of the web app is missing from this build.")
            return
        }
        do {
            let server = self.server ?? LocalWebServer(root: root)
            self.server = server
            let port = try await server.start()
            guard let url = URL(string: "http://localhost:\(port)\(AppConfig.bundledPathAndQuery)") else {
                showErrorPage("Couldn't build the local URL.")
                return
            }
            webView.load(URLRequest(url: url))
        } catch {
            showErrorPage("Couldn't start the local web server: \(error.localizedDescription)")
        }
    }

    /// Call when returning to the foreground: iOS may have torn down the loopback listener.
    func appDidBecomeActive() {
        guard let server else { return }
        Task { _ = try? await server.start() }
    }

    private func showErrorPage(_ message: String) {
        let escaped = message
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        let retry = AppConfig.remoteURL.absoluteString.replacingOccurrences(of: "\"", with: "%22")
        let html = """
        <!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{font:17px -apple-system,system-ui;background:#1f1b16;color:#f4ecdf;display:flex;
        min-height:100vh;align-items:center;justify-content:center;margin:0;padding:24px;box-sizing:border-box;text-align:center}
        a{color:#d97a41;font-weight:600}</style></head>
        <body><div><h2>Mise couldn't load</h2><p>\(escaped)</p><p><a href="\(retry)">Try again</a></p></div></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    private func isAppURL(_ url: URL) -> Bool {
        guard let host = url.host() else { return url.scheme == "about" }
        return AppConfig.trustedHosts.contains(host)
    }

    private func handleLoadFailure(_ error: Error) {
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled { return }
        logger.error("Page load failed: \(nsError.domain, privacy: .public) \(nsError.code)")
        guard nsError.domain == NSURLErrorDomain else { return }

        // Offline (or the host is unreachable): serve the bundled copy so Mise still works.
        if AppConfig.webSource == .remote, !fellBackToBundled, AppConfig.bundledWebRoot != nil {
            fellBackToBundled = true
            Task { await loadBundled() }
        } else {
            showErrorPage(nsError.localizedDescription)
        }
    }
}

// MARK: - WKNavigationDelegate

extension WebHost: @preconcurrency WKNavigationDelegate {
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handleLoadFailure(error)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        // Usually memory pressure (the model is big). Reload the page; the model stays loaded.
        logger.error("Web content process terminated; reloading")
        webView.reload()
    }
}

// MARK: - WKUIDelegate

extension WebHost: @preconcurrency WKUIDelegate {
    /// Camera + microphone for getUserMedia: granted for our own pages (iOS still shows its
    /// one-time system permission prompt using the Info.plist usage strings).
    func webView(
        _ webView: WKWebView,
        requestMediaCapturePermissionFor origin: WKSecurityOrigin,
        initiatedByFrame frame: WKFrameInfo,
        type: WKMediaCaptureType
    ) async -> WKPermissionDecision {
        AppConfig.trustedHosts.contains(origin.host) ? .grant : .deny
    }

    /// target=_blank / window.open: our pages stay in the web view, everything else opens in Safari.
    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url {
            if isAppURL(url) {
                webView.load(navigationAction.request)
            } else if url.scheme == "https" || url.scheme == "http" {
                UIApplication.shared.open(url)
            }
        }
        return nil
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo
    ) async {
        _ = await presentDialog(message: message, cancellable: false)
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo
    ) async -> Bool {
        await presentDialog(message: message, cancellable: true)
    }

    private func presentDialog(message: String, cancellable: Bool) async -> Bool {
        guard let presenter = topViewController() else { return false }
        return await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            if cancellable {
                alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in
                    continuation.resume(returning: false)
                })
            }
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in
                continuation.resume(returning: true)
            })
            presenter.present(alert, animated: true)
        }
    }

    private func topViewController() -> UIViewController? {
        var top = webView.window?.rootViewController
        while let presented = top?.presentedViewController { top = presented }
        return top
    }
}

// MARK: - SwiftUI wrapper

struct WebViewContainer: UIViewRepresentable {
    let webView: WKWebView

    func makeUIView(context: Context) -> WKWebView { webView }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
