import AppKit
import WebKit

private let appName = "Age of Collapse Balance Lab"

final class BalanceLab: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKDownloadDelegate {
    private var window: NSWindow!
    private var server: Process?
    private var origin: URL?
    private var portOutput = Data()
    private var shuttingDown = false
    private var failed = false
    private var downloads: [ObjectIdentifier: (temporary: URL, destination: URL)] = [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1240, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false
        )
        window.title = appName
        window.minSize = NSSize(width: 540, height: 460)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        let loading = NSTextField(labelWithString: "Starting the balance lab…")
        loading.alignment = .center
        loading.translatesAutoresizingMaskIntoConstraints = false
        if let content = window.contentView {
            content.addSubview(loading)
            NSLayoutConstraint.activate([
                loading.centerXAnchor.constraint(equalTo: content.centerXAnchor),
                loading.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            ])
        }
        do {
            try startServer()
        } catch {
            showFailure(error.localizedDescription)
        }
    }

    private func startServer() throws {
        let files = FileManager.default
        let resources = Bundle.main.resourceURL!
        #if arch(arm64)
        let architecture = "arm64"
        #else
        let architecture = "x86_64"
        #endif
        let support = try files.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                    appropriateFor: nil, create: true)
        let data = ProcessInfo.processInfo.environment["AOC_DESKTOP_DATA_DIR"].map {
            URL(fileURLWithPath: $0, isDirectory: true)
        } ?? support.appendingPathComponent(appName, isDirectory: true)
        try files.createDirectory(at: data, withIntermediateDirectories: true)
        let log = data.appendingPathComponent("server.log")
        if !files.fileExists(atPath: log.path) {
            try Data().write(to: log, options: .atomic)
        }
        let logOutput = try FileHandle(forWritingTo: log)
        try logOutput.truncate(atOffset: 0)

        let child = Process()
        child.executableURL = resources.appendingPathComponent("Runtimes/Python-\(architecture)/bin/python3.13")
        child.arguments = ["-I", "-B", "-u", resources.appendingPathComponent("Simulator/server_entry.py").path,
                           "--parent", String(ProcessInfo.processInfo.processIdentifier)]
        child.currentDirectoryURL = data
        child.environment = ["AOC_STUDIES_DIR": data.appendingPathComponent("Studies").path]
        child.standardError = logOutput
        let port = Pipe()
        child.standardOutput = port
        port.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            if bytes.isEmpty { handle.readabilityHandler = nil }
            DispatchQueue.main.async { self?.readPort(bytes, from: handle) }
        }
        child.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self, !self.shuttingDown else { return }
                self.showFailure("The local server stopped (exit \(process.terminationStatus)).\n\(log.path)")
            }
        }
        try child.run()
        server = child
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            guard let self, self.origin == nil, !self.shuttingDown else { return }
            self.showFailure("The local server did not start. See \(log.path).")
        }
    }

    private func readPort(_ bytes: Data, from handle: FileHandle) {
        guard origin == nil, !failed, !bytes.isEmpty else { return }
        portOutput.append(bytes)
        guard let newline = portOutput.firstIndex(of: 10) else { return }
        handle.readabilityHandler = nil
        guard let text = String(data: portOutput[..<newline], encoding: .utf8),
              let port = Int(text), (1...65535).contains(port),
              let url = URL(string: "http://127.0.0.1:\(port)/") else {
            showFailure("The local server did not return a valid address.")
            return
        }
        origin = url
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = self
        window.contentView = view
        view.load(URLRequest(url: url))
    }

    private func showFailure(_ message: String) {
        guard !failed, !shuttingDown else { return }
        failed = true
        let alert = NSAlert()
        alert.messageText = "The balance lab could not run"
        alert.informativeText = message
        alert.addButton(withTitle: "Quit")
        alert.beginSheetModal(for: window) { _ in NSApp.terminate(nil) }
    }

    private func isLocal(_ url: URL?) -> Bool {
        guard let url, let origin else { return false }
        return url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload &&
            (isLocal(action.request.url) || action.request.url?.scheme == "blob") {
            decisionHandler(.download)
        } else {
            decisionHandler(isLocal(action.request.url) ? .allow : .cancel)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        guard isLocal(response.response.url) else { decisionHandler(.cancel); return }
        let disposition = (response.response as? HTTPURLResponse)?
            .value(forHTTPHeaderField: "Content-Disposition")?.lowercased()
        decisionHandler(response.canShowMIMEType && disposition?.hasPrefix("attachment") != true
                        ? .allow : .download)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let destination = panel.url else {
                completionHandler(nil)
                return
            }
            // WebKit needs a new path. Stage beside the chosen file so an
            // approved overwrite can replace it on the same volume.
            let temporary = destination.deletingLastPathComponent()
                .appendingPathComponent(".balance-lab-\(UUID().uuidString)")
            self.downloads[ObjectIdentifier(download)] = (temporary, destination)
            completionHandler(temporary)
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let paths = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        let files = FileManager.default
        do {
            if files.fileExists(atPath: paths.destination.path) {
                _ = try files.replaceItemAt(paths.destination, withItemAt: paths.temporary)
            } else {
                try files.moveItem(at: paths.temporary, to: paths.destination)
            }
        } catch {
            try? files.removeItem(at: paths.temporary)
            showExportError(error)
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        guard let paths = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        try? FileManager.default.removeItem(at: paths.temporary)
        showExportError(error)
    }

    private func showExportError(_ error: Error) {
        let alert = NSAlert(error: error)
        alert.messageText = "The export could not be saved"
        alert.beginSheetModal(for: window)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        shuttingDown = true
        if let server, server.isRunning { server.terminate() }
        for paths in downloads.values { try? FileManager.default.removeItem(at: paths.temporary) }
    }

    private func installMenu() {
        let bar = NSMenu()
        let app = NSMenuItem()
        app.submenu = NSMenu(title: appName)
        app.submenu?.addItem(withTitle: "Quit \(appName)", action: #selector(NSApplication.terminate(_:)),
                             keyEquivalent: "q")
        bar.addItem(app)
        let edit = NSMenuItem()
        edit.submenu = NSMenu(title: "Edit")
        for (title, selector, key) in [
            ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"),
            ("Select All", "selectAll:", "a"),
        ] {
            edit.submenu?.addItem(withTitle: title, action: NSSelectorFromString(selector), keyEquivalent: key)
        }
        bar.addItem(edit)
        NSApp.mainMenu = bar
    }
}

let application = NSApplication.shared
let delegate = BalanceLab()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
