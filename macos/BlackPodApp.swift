// Native, local-only presentation for the BlackPod shadow research station.
// The independent user LaunchAgent owns collection; closing this window does
// not stop it. This application has no broker, policy, or trading controls.
import AppKit
import Foundation
import WebKit

final class StationDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var tabs: NSSegmentedControl!
    private var starter: Process?
    private var ready = false
    private let addresses = [
        "http://127.0.0.1:5181/?view=research",
        "http://127.0.0.1:5182/dashboard.html",
        "http://127.0.0.1:5183/",
        "http://127.0.0.1:5183/sentry"
    ]

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit BlackPod Window", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        NSApplication.shared.mainMenu = menu

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "BlackPod · Shadow Research"
        window.minSize = NSSize(width: 720, height: 500)
        window.center()
        let content = NSView()
        window.contentView = content
        tabs = NSSegmentedControl(labels: ["Experiment", "Historical baseline", "Station status", "Sentry"], trackingMode: .selectOne, target: self, action: #selector(selectTab))
        tabs.selectedSegment = 0
        tabs.translatesAutoresizingMaskIntoConstraints = false
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(tabs)
        content.addSubview(webView)
        NSLayoutConstraint.activate([
            tabs.topAnchor.constraint(equalTo: content.topAnchor, constant: 12),
            tabs.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            webView.topAnchor.constraint(equalTo: tabs.bottomAnchor, constant: 12),
            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor)
        ])
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        showMessage("Starting the research station…", detail: "The dashboards and frozen observational collector run independently of this window.")
        startStation()
    }

    private func showMessage(_ title: String, detail: String) {
        // Both strings are fixed application text, never provider or shell output.
        webView.loadHTMLString("<!doctype html><meta name='viewport' content='width=device-width'><style>body{font:18px -apple-system,sans-serif;background:#101827;color:#e6edf7;margin:10%;line-height:1.6}h1{font-size:27px}p{max-width:650px;color:#acbad0}</style><h1>\(title)</h1><p>\(detail)</p>", baseURL: nil)
    }

    private func startStation() {
        guard let info = Bundle.main.infoDictionary,
              let python = info["BlackPodStationPython"] as? String,
              let repository = info["BlackPodStationRepository"] as? String,
              let config = info["BlackPodStationConfig"] as? String,
              [python, repository, config].allSatisfy({ $0.hasPrefix("/") && !$0.contains("\u{0}") }) else {
            showMessage("Station setup is incomplete", detail: "Rebuild or reinstall the local BlackPod app from its documented station command.")
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", "blackpod_build_week.shadow_station", "open", "--config", config, "--no-browser"]
        process.currentDirectoryURL = URL(fileURLWithPath: repository)
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = repository + "/src"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        process.terminationHandler = { [weak self] completed in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.ready = completed.terminationStatus == 0
                if self.ready {
                    self.selectTab()
                } else {
                    self.showMessage("The station needs attention", detail: "The local station could not start or its health checks failed. Check the station status command and local logs. Auto-trading has not been enabled.")
                }
            }
        }
        starter = process
        do {
            try process.run()
        } catch {
            showMessage("The station could not start", detail: "The repository or Python environment may have moved. Use the documented station checks before rebuilding the app.")
        }
    }

    @objc private func selectTab() {
        guard ready, addresses.indices.contains(tabs.selectedSegment), let url = URL(string: addresses[tabs.selectedSegment]) else { return }
        webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        // Internal start/error HTML is allowed. External links, custom schemes,
        // remote hosts, and unrecognized local services never open in the app.
        if url.absoluteString == "about:blank" { decisionHandler(.allow); return }
        if url.scheme == "https" && url.host != nil && url.user == nil && url.password == nil && navigationAction.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        let allowed = url.scheme == "http" && url.host == "127.0.0.1" && [5181, 5182, 5183].contains(url.port ?? 0) && url.user == nil && url.password == nil
        if allowed {
            tabs.selectedSegment = url.port == 5181 ? 0 : url.port == 5182 ? 1 : url.path == "/sentry" ? 3 : 2
            if navigationAction.targetFrame == nil {
                webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
                decisionHandler(.cancel)
                return
            }
        }
        decisionHandler(allowed ? .allow : .cancel)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        // Only the presentation process exits. launchd keeps the station alive.
        return true
    }
}

let application = NSApplication.shared
let delegate = StationDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
