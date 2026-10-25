import SwiftUI

/// First-run screen: downloads Gemma 4 E2B (one time) and starts the engine. Shown until the
/// model is ready (or the user chooses to continue without it).
struct ModelSetupOverlay: View {
    @Environment(AppModel.self) private var model

    private let cream = Color(red: 0.957, green: 0.925, blue: 0.875)
    private let accent = Color(red: 0.851, green: 0.478, blue: 0.255)

    var body: some View {
        ZStack {
            Color(red: 0.12, green: 0.105, blue: 0.086)
                .ignoresSafeArea()

            VStack(spacing: 28) {
                Spacer()

                VStack(spacing: 10) {
                    Image(systemName: "fork.knife.circle.fill")
                        .font(.system(size: 64))
                        .foregroundStyle(accent)
                    Text("Mise")
                        .font(.system(size: 40, weight: .bold, design: .serif))
                        .foregroundStyle(cream)
                    Text("Your sous-chef runs right here on your iPhone.")
                        .font(.callout)
                        .foregroundStyle(cream.opacity(0.7))
                        .multilineTextAlignment(.center)
                }

                stateCard
                    .padding(20)
                    .frame(maxWidth: 420)
                    .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 20, style: .continuous))

                Spacer()

                Button("Continue without on-device AI") {
                    model.overlayDismissed = true
                }
                .font(.footnote)
                .foregroundStyle(cream.opacity(0.55))
                .padding(.bottom, 8)
            }
            .padding(.horizontal, 24)
        }
    }

    @ViewBuilder
    private var stateCard: some View {
        let status = model.status
        if let error = status.error, !status.downloading, !status.loading {
            VStack(spacing: 14) {
                Label("Setup paused", systemImage: "exclamationmark.triangle.fill")
                    .font(.headline)
                    .foregroundStyle(accent)
                Text(error)
                    .font(.subheadline)
                    .foregroundStyle(cream.opacity(0.85))
                    .multilineTextAlignment(.center)
                if status.bytes > 0 && status.progress < 1 {
                    Text("\(bytesText(status.bytes)) of \(bytesText(status.total)) saved; Retry picks up where it stopped.")
                        .font(.footnote)
                        .foregroundStyle(cream.opacity(0.6))
                        .multilineTextAlignment(.center)
                }
                primaryButton("Retry") { model.retry() }
            }
        } else if status.downloading {
            VStack(alignment: .leading, spacing: 12) {
                Text("Downloading Gemma 4")
                    .font(.headline)
                    .foregroundStyle(cream)
                ProgressView(value: status.progress)
                    .tint(accent)
                HStack {
                    Text("\(bytesText(status.bytes)) of \(bytesText(status.total))")
                    Spacer()
                    Text(status.progress, format: .percent.precision(.fractionLength(0)))
                }
                .font(.footnote.monospacedDigit())
                .foregroundStyle(cream.opacity(0.75))
                Label("Wi-Fi recommended. Keep Mise open; this happens only once.", systemImage: "wifi")
                    .font(.footnote)
                    .foregroundStyle(cream.opacity(0.6))
            }
        } else if status.loading {
            VStack(spacing: 12) {
                ProgressView()
                    .tint(cream)
                Text("Starting Gemma on the \(status.backend == "cpu" ? "CPU" : "GPU")…")
                    .font(.headline)
                    .foregroundStyle(cream)
                Text("Takes a few seconds.")
                    .font(.footnote)
                    .foregroundStyle(cream.opacity(0.6))
            }
        } else if model.needsDownloadConsent {
            VStack(spacing: 14) {
                Text("One-time download")
                    .font(.headline)
                    .foregroundStyle(cream)
                Text("Mise needs the Gemma 4 model (about \(bytesText(status.total))). You're on cellular or Low Data Mode. Wi-Fi recommended.")
                    .font(.subheadline)
                    .foregroundStyle(cream.opacity(0.85))
                    .multilineTextAlignment(.center)
                primaryButton("Download now") {
                    Task { await model.loadModel() }
                }
            }
        } else {
            VStack(spacing: 12) {
                ProgressView()
                    .tint(cream)
                Text("Getting ready…")
                    .font(.headline)
                    .foregroundStyle(cream)
            }
        }
    }

    private func primaryButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.borderedProminent)
        .tint(accent)
    }

    private func bytesText(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}
