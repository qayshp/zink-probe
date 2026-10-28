import Foundation

/// Event-driven single-job coordinator. No native transport is linked here.
/// Drive write/receive/tick serially with monotonic time. Each returned write is
/// consumed once; errors terminate the instance and never cause a reconnect/retry.
final class SubmissionCoordinator {
    enum State: String { case preflight, uploading, observing, completed, uncertain, notSubmitted }
    private(set) var state: State = .preflight
    private(set) var error: String?
    let localID: UUID
    var terminal: Bool { [.completed,.uncertain,.notSubmitted].contains(state) }
    let physicalEjectionConfirmed = false
    private let journal: JobJournal
    private let expectedID: String
    private let image: PreparedJobImage?
    private let name: String
    private let recovery: Bool
    private let pollInterval: TimeInterval
    private let deadline: TimeInterval
    private var lastTime: TimeInterval
    private var nextPoll: TimeInterval = 0
    private var reader: ReadOnlyPreflight
    private var exchange: AccessoryExchange?
    private var upload: TrackedUpload?
    private var claimed = false
    private var idleSamples = 0

    /// Loads the exact saved bytes and identity; never invents a new job ID.
    /// Native submission additionally requires an explicit single-use PrintPermit.
    convenience init(boundJob id: UUID, journal: JobJournal, now: TimeInterval, pollInterval: TimeInterval = 2, authorization: PrintPermit? = nil) throws {
        guard let binding = try journal.binding(id) else { throw JobJournal.Failure.invalidRecord }
        if try journal.attemptState(id) != nil {
            guard authorization?.binding == binding, try journal.attemptState(id) == "reserved" else { throw JobJournal.Failure.blocked }
        }
        try self.init(image:journal.boundImage(id),id:id,expectedDeviceID:binding.device,journal:journal,now:now,pollInterval:pollInterval)
    }

    init(image: PreparedJobImage, name: String = "Select photo", id: UUID, expectedDeviceID: String,
         journal: JobJournal, now: TimeInterval, timeout: TimeInterval = 300, pollInterval: TimeInterval = 2) throws {
        guard now.isFinite, timeout.isFinite, timeout > 0, (now+timeout).isFinite,
              pollInterval.isFinite, pollInterval >= 0 else { throw ReadOnlyPreflight.Failure.invalid("Invalid coordinator timing") }
        reader = try ReadOnlyPreflight(expectedDeviceID: expectedDeviceID)
        try journal.assertAvailable(id:id,device:expectedDeviceID)
        self.image = image; self.name = name; localID = id; expectedID = expectedDeviceID
        self.journal = journal; lastTime = now; deadline = now + timeout; self.pollInterval = pollInterval; recovery = false
    }
    /// Read-only recovery: no UploadPlan can be reconstructed from this initializer.
    init(recover id: UUID, journal: JobJournal, now: TimeInterval, timeout: TimeInterval = 180, pollInterval: TimeInterval = 2) throws {
        guard now.isFinite, timeout.isFinite, timeout > 0, (now+timeout).isFinite,
              pollInterval.isFinite, pollInterval >= 0,
              let record = try journal.record(id), record.printerJobID != nil,
              record.baselinePages != nil, record.baselineCalibrations != nil,
              record.attributionBlocked != true else { throw JobJournal.Failure.blocked }
        reader = try ReadOnlyPreflight(expectedDeviceID: record.device,requireReady:false)
        image = nil; name = ""; localID = id; expectedID = record.device; self.journal = journal
        lastTime = now; deadline = now + timeout; self.pollInterval = pollInterval; recovery = true; claimed = true
        if record.state == "completed" { state = .completed }
    }
    func cancel() { fail("Cancelled; any accepted printer job may still run") }
    func disconnected() { fail("Stream interrupted; no retry") }
    private func fail(_ reason: String) {
        guard !terminal else { return }
        exchange?.stop(); upload?.stop(); error = reason
        state = claimed ? .uncertain : .notSubmitted
        if claimed { journal.markUncertain(localID,reason:reason) }
    }
    func tick(now: TimeInterval) {
        guard !terminal else { return }
        guard now.isFinite, now >= lastTime, now < deadline else { fail("Coordinator deadline or clock violation"); return }
        lastTime = now
        do { try exchange?.check(now:now) } catch { fail("Exchange timeout") }
    }
    func write(now: TimeInterval, _ writer: ([UInt8]) -> Int) {
        tick(now:now)
        guard !terminal, now >= nextPoll else { return }
        do {
            if exchange == nil {
                let message: [UInt8]
                if state == .uploading { message = try upload!.nextMessage() }
                else { message = try reader.next() }
                exchange = try AccessoryExchange(payload:message,now:now)
            }
            try exchange?.write(now:now,writer)
        } catch { fail("Write/preparation failed: \(error)") }
    }
    func receive(_ bytes: [UInt8], now: TimeInterval) {
        tick(now:now)
        guard !terminal else { return }
        do {
            guard exchange != nil else { throw ReadOnlyPreflight.Failure.invalid("Unsolicited reply") }
            guard let reply = try exchange?.receive(bytes,now:now) else { return }
            exchange = nil
            if state == .uploading {
                try upload!.accept(reply)
                if upload!.uploaded { state = .observing; reader = try .observation() }
                return
            }
            try reader.accept(reply)
            guard reader.complete else { return }
            if state == .preflight && !recovery {
                guard let image else { throw JobJournal.Failure.invalidRecord }
                if let binding = try journal.binding(localID) {
                    guard binding.firmware == reader.firmware else { throw ReadOnlyPreflight.Failure.invalid("Bound firmware changed; saved draft requires review") }
                }
                upload = try TrackedUpload(journal:journal,id:localID,device:expectedID,jpeg:image.jpeg,
                                           maximum:reader.maximum,name:name,nameLimit:reader.nameLimit)
                claimed = true
                try journal.saveBaseline(localID,pages:reader.pages,calibrations:reader.calibrations,firmware:reader.firmware)
                state = .uploading
            } else {
                if recovery && state == .preflight {
                    guard reader.firmware == (try journal.record(localID))?.baselineFirmware else { throw ReadOnlyPreflight.Failure.invalid("Firmware changed during recovery") }
                    state = .observing
                }
                try observe()
                if !terminal { reader = try .observation(); nextPoll = now + pollInterval }
            }
        } catch { fail("Reply/journal validation failed: \(error)") }
    }
    private func observe() throws {
        if try journal.observe(localID,snapshot:reader,idleSamples:&idleSamples) { state = .completed }
    }
}
