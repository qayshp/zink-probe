import Foundation
import ExternalAccessory

/// Thin EASession binding. All IO and delegate callbacks use the main run loop.
private final class EADuplex: NSObject, AccessoryDuplex, StreamDelegate {
    private let session: EASession
    private let input: InputStream
    private let output: OutputStream
    private var handler: ((AccessoryIOEvent) -> Void)?
    private var closed = false
    init?(accessory: EAAccessory) {
        guard let session = EASession(accessory:accessory,forProtocol:"com.hp.protocol.lifestyle"),
              let input = session.inputStream, let output = session.outputStream else { return nil }
        self.session = session; self.input = input; self.output = output
        super.init()
    }
    var hasBytes: Bool { !closed && input.hasBytesAvailable }
    var hasSpace: Bool { !closed && output.hasSpaceAvailable }
    func open(_ handler: @escaping (AccessoryIOEvent) -> Void) {
        precondition(Thread.isMainThread); self.handler = handler
        for stream: Stream in [input,output] {
            guard !closed else { return }
            stream.delegate = self; stream.schedule(in:.main,forMode:.common); stream.open()
        }
    }
    func read(maximum: Int) -> AccessoryRead {
        precondition(Thread.isMainThread)
        guard !closed, input.hasBytesAvailable else { return .wouldBlock }
        var bytes = [UInt8](repeating:0,count:maximum)
        let count = input.read(&bytes,maxLength:maximum)
        if count < 0 { return .failed }
        return count == 0 ? .ended : .bytes(Array(bytes.prefix(count)))
    }
    func write(_ bytes: [UInt8]) -> Int {
        precondition(Thread.isMainThread)
        guard !closed, output.hasSpaceAvailable else { return 0 }
        return bytes.withUnsafeBufferPointer { output.write($0.baseAddress!,maxLength:$0.count) }
    }
    func stream(_ stream: Stream, handle event: Stream.Event) {
        precondition(Thread.isMainThread)
        guard !closed, stream === input || stream === output else { return }
        if event.contains(.errorOccurred) { handler?(.failed); return }
        if event.contains(.endEncountered) { handler?(.ended); return }
        if event.contains(.openCompleted) { handler?(.opened(stream === input ? .input : .output)) }
        if event.contains(.hasBytesAvailable) { handler?(.readable) }
        if event.contains(.hasSpaceAvailable) { handler?(.writable) }
    }
    func close() {
        precondition(Thread.isMainThread)
        guard !closed else { return }; closed = true; handler = nil
        for stream: Stream in [input,output] {
            stream.delegate = nil; stream.close(); stream.remove(from:.main,forMode:.common)
        }
    }
    deinit { if !closed { close() } }
}

/// Diagnostics/recovery stay read-only. Submission requires an explicit immutable
/// saved binding and a freshly committed, single-use PrintPermit.
final class NativeAccessoryAdapter {
    private var driver: AccessoryStreamDriver?
    private var timer: Timer?
    private let clock = { ProcessInfo.processInfo.systemUptime }
    var active: Bool { driver.map { !$0.closed } ?? false }
    func preflight(_ accessory: EAAccessory, expectedDeviceID: String? = nil,
                   update: @escaping (AccessoryStreamPump) -> Void) throws {
        let pump = try AccessoryStreamPump(expectedDeviceID:expectedDeviceID,expectedFirmware:accessory.firmwareRevision,now:clock())
        try start(accessory,pump:pump,update:update)
    }
    func recover(_ accessory: EAAccessory, id: UUID, journal: JobJournal,
                 update: @escaping (AccessoryStreamPump) -> Void) throws {
        let coordinator = try SubmissionCoordinator(recover:id,journal:journal,now:clock())
        try start(accessory,pump:AccessoryStreamPump(coordinator:coordinator,now:clock()),update:update)
    }
    /// Called only by the saved-photo confirmation screen, never from lifecycle,
    /// reconnection, diagnostics, preparation or restoration of saved jobs.
    func submitOnce(_ accessory: EAAccessory, reviewed: JobBinding, journal: JobJournal,
                    update: @escaping (AccessoryStreamPump) -> Void) throws {
        precondition(Thread.isMainThread)
        guard !active, accessory.isConnected, accessory.modelNumber == "HPISPSLE",
              accessory.firmwareRevision == reviewed.firmware,
              accessory.protocolStrings.contains("com.hp.protocol.lifestyle") else { throw JobJournal.Failure.blocked }
        let permit = try journal.authorizePrintOnce(reviewed)
        do {
            let coordinator = try SubmissionCoordinator(boundJob:reviewed.id,journal:journal,now:clock(),authorization:permit)
            let pump = try AccessoryStreamPump(coordinator:coordinator,permit:permit,journal:journal,now:clock())
            try start(accessory,pump:pump,update:update)
        } catch {
            try? journal.finishPrintAttempt(reviewed.id)
            throw error
        }
    }
    private func start(_ accessory: EAAccessory, pump: AccessoryStreamPump,
                       update: @escaping (AccessoryStreamPump) -> Void) throws {
        precondition(Thread.isMainThread)
        guard !active, accessory.isConnected, accessory.modelNumber == "HPISPSLE",
              accessory.protocolStrings.contains("com.hp.protocol.lifestyle"), let io = EADuplex(accessory:accessory) else {
            throw ReadOnlyPreflight.Failure.invalid("Select session/streams unavailable; no retry")
        }
        let candidate = AccessoryStreamDriver(pump:pump,io:io,clock:clock) { [weak self] result in
            if result.terminal { self?.timer?.invalidate(); self?.timer = nil }
            update(result)
        }
        driver = candidate
        let tick = Timer(timeInterval:0.1,repeats:true) { [weak self] _ in self?.driver?.tick() }
        timer = tick; RunLoop.main.add(tick,forMode:.common)
        candidate.start()
    }
    func stop(_ reason: String) { timer?.invalidate(); timer = nil; driver?.cancel(reason) }
    deinit { timer?.invalidate(); driver?.cancel("Accessory owner released") }
}
