// campreview - live viewfinder for the iPhone Continuity Camera with a
// capture button. Frames land in --out as JPEGs for cam.py to claim.
import AVFoundation
import AppKit
import CoreImage

// ---------------------------------------------------------------- args
var outDir = FileManager.default.currentDirectoryPath
var wantDevice: String?
var once = false
var autoAfter: Double = 0          // self-test hook: capture after N seconds
var cancelNow = false              // self-test hook: close without capturing

var argv = Array(CommandLine.arguments.dropFirst())
var ai = 0
while ai < argv.count {
    switch argv[ai] {
    case "--out":    ai += 1; if ai < argv.count { outDir = argv[ai] }
    case "--device": ai += 1; if ai < argv.count { wantDevice = argv[ai] }
    case "--once":   once = true
    case "--auto":   ai += 1; if ai < argv.count { autoAfter = Double(argv[ai]) ?? 0 }
    case "--cancel": cancelNow = true
    default: break
    }
    ai += 1
}

func cameras() -> [AVCaptureDevice] {
    var types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera, .external]
    if #available(macOS 14.0, *) { types.append(.continuityCamera) }
    let found = AVCaptureDevice.DiscoverySession(
        deviceTypes: types, mediaType: .video, position: .unspecified).devices
    // Desk View is a cropped downward view - never what you are framing.
    return found.filter { !$0.localizedName.contains("Desk View") }
}

final class PreviewView: NSView {
    var previewLayer: AVCaptureVideoPreviewLayer?
    override var isFlipped: Bool { true }
    override func layout() {
        super.layout()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        previewLayer?.frame = bounds
        CATransaction.commit()
    }
}

final class Controller: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate,
                        NSWindowDelegate, NSApplicationDelegate {
    let session = AVCaptureSession()
    let videoOut = AVCaptureVideoDataOutput()
    let frameQueue = DispatchQueue(label: "cam.frames")
    let ciContext = CIContext()
    let lock = NSLock()
    var latest: CVPixelBuffer?

    var window: NSWindow!
    var preview: PreviewView!
    var status: NSTextField!
    var picker: NSPopUpButton!
    var devices: [AVCaptureDevice] = []
    var shots = 0

    // ------------------------------------------------------------ capture
    func captureOutput(_ o: AVCaptureOutput, didOutput sb: CMSampleBuffer,
                       from c: AVCaptureConnection) {
        guard let pb = CMSampleBufferGetImageBuffer(sb) else { return }
        lock.lock(); latest = pb; lock.unlock()
    }

    @objc func snap() {
        lock.lock(); let pb = latest; lock.unlock()
        guard let pb else {
            flash("no frame yet - waiting for the camera…")
            DispatchQueue.global(qos: .userInitiated).async {
                let deadline = Date().addingTimeInterval(45)
                while Date() < deadline {
                    self.lock.lock(); let ready = self.latest != nil; self.lock.unlock()
                    if ready { DispatchQueue.main.async { self.snap() }; return }
                    Thread.sleep(forTimeInterval: 0.2)
                }
                self.flash("camera never delivered a frame - is the phone awake?")
            }
            return
        }
        let img = CIImage(cvPixelBuffer: pb)
        guard let data = ciContext.jpegRepresentation(
                of: img, colorSpace: CGColorSpaceCreateDeviceRGB(),
                options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.92])
        else { flash("encode failed"); return }
        let name = String(format: "%.6f", Date().timeIntervalSince1970)
            .replacingOccurrences(of: ".", with: "") + ".jpg"
        let url = URL(fileURLWithPath: outDir).appendingPathComponent(name)
        do {
            try data.write(to: url)
            shots += 1
            flash("captured \(shots) - \(Int(img.extent.width))x\(Int(img.extent.height))")
            NSSound(named: "Pop")?.play()
            if once { finish() }
        } catch { flash("write failed: \(error.localizedDescription)") }
    }

    func flash(_ s: String) {
        DispatchQueue.main.async { self.status.stringValue = s }
    }

    @objc func finish() {
        session.stopRunning()
        NSApp.terminate(nil)
    }

    // ------------------------------------------------------------ session
    func start(device: AVCaptureDevice) {
        session.beginConfiguration()
        for i in session.inputs { session.removeInput(i) }
        for p in [AVCaptureSession.Preset.photo, .high, .medium]
        where session.canSetSessionPreset(p) { session.sessionPreset = p; break }
        if let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) {
            session.addInput(input)
        } else {
            flash("could not open \(device.localizedName)")
        }
        if session.outputs.isEmpty {
            videoOut.alwaysDiscardsLateVideoFrames = true
            videoOut.setSampleBufferDelegate(self, queue: frameQueue)
            if session.canAddOutput(videoOut) { session.addOutput(videoOut) }
        }
        session.commitConfiguration()
        if !session.isRunning {
            DispatchQueue.global(qos: .userInitiated).async { self.session.startRunning() }
        }
        flash("connecting to \(device.localizedName)…")
    }

    @objc func pickDevice(_ sender: NSPopUpButton) {
        let d = devices[sender.indexOfSelectedItem]
        lock.lock(); latest = nil; lock.unlock()
        start(device: d)
    }

    // ------------------------------------------------------------ ui
    func applicationDidFinishLaunching(_ n: Notification) {
        devices = cameras()
        guard !devices.isEmpty else {
            FileHandle.standardError.write("campreview: no cameras found\n".data(using: .utf8)!)
            exit(3)
        }
        var chosen = devices[0]
        if let want = wantDevice,
           let m = devices.first(where: { $0.localizedName.localizedCaseInsensitiveContains(want) }) {
            chosen = m
        } else if let iphone = devices.first(where: { $0.localizedName.contains("iPhone") })
                    ?? devices.first(where: { !$0.localizedName.contains("MacBook") }) {
            chosen = iphone   // prefer the phone over the built-in FaceTime camera
        }

        let rect = NSRect(x: 0, y: 0, width: 900, height: 720)
        window = NSWindow(contentRect: rect,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Cam - live view"
        window.delegate = self
        window.center()
        window.isReleasedWhenClosed = false

        let root = NSView(frame: rect)
        root.autoresizingMask = [.width, .height]

        let barH: CGFloat = 56
        preview = PreviewView(frame: NSRect(x: 0, y: barH, width: rect.width, height: rect.height - barH))
        preview.autoresizingMask = [.width, .height]
        preview.wantsLayer = true
        preview.layer?.backgroundColor = NSColor.black.cgColor
        let pl = AVCaptureVideoPreviewLayer(session: session)
        pl.videoGravity = .resizeAspect
        pl.frame = preview.bounds
        preview.layer?.addSublayer(pl)
        preview.previewLayer = pl
        root.addSubview(preview)

        let bar = NSView(frame: NSRect(x: 0, y: 0, width: rect.width, height: barH))
        bar.autoresizingMask = [.width]

        picker = NSPopUpButton(frame: NSRect(x: 12, y: 13, width: 250, height: 28))
        picker.addItems(withTitles: devices.map { $0.localizedName })
        picker.selectItem(withTitle: chosen.localizedName)
        picker.target = self
        picker.action = #selector(pickDevice(_:))
        bar.addSubview(picker)

        status = NSTextField(labelWithString: "starting…")
        status.frame = NSRect(x: 272, y: 18, width: rect.width - 272 - 300, height: 20)
        status.autoresizingMask = [.width]
        status.textColor = .secondaryLabelColor
        bar.addSubview(status)

        let snapBtn = NSButton(title: "Capture  (space)", target: self, action: #selector(snap))
        snapBtn.frame = NSRect(x: rect.width - 290, y: 12, width: 150, height: 30)
        snapBtn.autoresizingMask = [.minXMargin]
        snapBtn.bezelStyle = .rounded
        snapBtn.keyEquivalent = " "
        bar.addSubview(snapBtn)

        let doneBtn = NSButton(title: "Send to Claude", target: self, action: #selector(finish))
        doneBtn.frame = NSRect(x: rect.width - 132, y: 12, width: 120, height: 30)
        doneBtn.autoresizingMask = [.minXMargin]
        doneBtn.bezelStyle = .rounded
        doneBtn.keyEquivalent = "\r"
        bar.addSubview(doneBtn)

        root.addSubview(bar)
        window.contentView = root
        window.level = .floating          // a viewfinder is useless behind a terminal
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        NSApp.activate(ignoringOtherApps: true)

        AVCaptureDevice.requestAccess(for: .video) { ok in
            DispatchQueue.main.async {
                if ok { self.start(device: chosen) }
                else { self.flash("camera permission denied - grant it in System Settings > Privacy") }
            }
        }

        if cancelNow {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { self.finish() }
        }

        if autoAfter > 0 {
            // Count down from the first real frame, not from launch - a cold
            // Continuity link can take ~40s to deliver anything.
            DispatchQueue.global(qos: .userInitiated).async {
                let deadline = Date().addingTimeInterval(75)
                while Date() < deadline {
                    self.lock.lock(); let ready = self.latest != nil; self.lock.unlock()
                    if ready { break }
                    Thread.sleep(forTimeInterval: 0.2)
                }
                Thread.sleep(forTimeInterval: autoAfter)
                DispatchQueue.main.async { self.snap(); self.finish() }
            }
        }
    }

    func windowWillClose(_ n: Notification) { finish() }
}

let app = NSApplication.shared
let ctrl = Controller()
app.delegate = ctrl
app.setActivationPolicy(.regular)
app.run()
