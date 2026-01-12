import SwiftUI

struct ContentView: View {
    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {

                // ✅ good: text button (usually readable to VoiceOver)
                Button("Continue") {}

                // ❌ bad: icon-only button with no accessibilityLabel
                Button {
                    print("Tapped settings")
                } label: {
                    Image(systemName: "gearshape.fill")
                        .font(.title)
                }

            }
            .navigationTitle("A11y Demo")
        }
    }
}
