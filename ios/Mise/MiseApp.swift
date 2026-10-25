import SwiftUI

@main
struct MiseApp: App {
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(model)
                .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { _, phase in
            model.scenePhaseChanged(phase)
        }
    }
}

struct ContentView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ZStack {
            Color(red: 0.12, green: 0.105, blue: 0.086)
                .ignoresSafeArea()

            // The web view loads behind the overlay so it's ready the moment the model is.
            WebViewContainer(webView: model.web.webView)
                .ignoresSafeArea()

            if model.showsSetupOverlay {
                ModelSetupOverlay()
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.35), value: model.showsSetupOverlay)
        .task { model.start() }
    }
}
