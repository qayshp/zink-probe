import Foundation

/// One notification is one complete BLE protocol packet. `written` is the native
/// write-with-response callback, never a printer protocol acknowledgement.
enum BLEPacketIOEvent {
    case ready(writeLimit: Int), notification([UInt8]), written, failed, ended
}

/// Serial-use native seam. A successful write accepts one whole ATT packet and
/// must eventually produce one `written` callback (or a terminal failure).
/// Implementations may call back inline; the bridge serializes those callbacks.
protocol BLEPacketIO: AnyObject {
    func open(_ handler: @escaping (BLEPacketIOEvent) -> Void)
    func write(_ packet: [UInt8]) -> Bool
    func close()
}

/// Adapts the existing gated stream coordinator to the BLE packet envelope.
/// HP+ frames exist only at the in-memory AccessoryDuplex seam: their payloads,
/// not their stream headers, are fragmented for GATT. No native submission
/// factory currently enables single-job submission. Native submission is blocked
/// before composition; read-only native sessions use the independent read policy.
final class BLESubmissionDuplex: AccessoryDuplex {
    /// This is a coarse opcode policy, not print authorization. A single-job
    /// composition still requires the upstream durable permit/frame gate.
    enum Policy { case readOnly, singleJobSubmission }
    /// Describes the failed operation, not a framework error or physical cause.
    /// Connection includes native Bluetooth/service/subscription readiness;
    /// setup is the printer's IF_CONFIG exchange; exchange follows negotiation.
    enum FailureStage: Equatable { case connection, setup, exchange }
    private enum State { case unopened, waitingReady, configuring, idle, exchanging, replyReady, closed }
    private enum WriteKind { case request, acknowledgement }
    private struct PendingWrite { let kind: WriteKind; let count: Int }

    private let io: BLEPacketIO
    private let clock: () -> TimeInterval
    private let policy: Policy
    private let setupTimeout: TimeInterval
    private var state: State = .unopened
    private var handler: ((AccessoryIOEvent) -> Void)?
    private var events: [BLEPacketIOEvent] = []
    private var processing = false
    private var virtualWriteInProgress = false
    private var platformWriteLimit = 20
    private var output: [[UInt8]] = []
    private var outputIndex = 0
    private var inFlight: PendingWrite?
    private var ackQueue = 0
    private var receiver = BLEPacketCodec()
    private var response: [UInt8]?
    private var input: [UInt8] = []
    private var lastTime = 0.0
    private var overallDeadline = 0.0
    private var setupDeadline = 0.0
    private var exchangeDeadline: TimeInterval?
    private(set) var protocolMTU = 20
    private(set) var acknowledgementPeriod = 0
    private(set) var txQueuedBytes = 0
    private(set) var txAcknowledgedBytes = 0
    private(set) var rxBytes = 0
    private(set) var writeCallbacks = 0
    private(set) var failureReason: String?
    private(set) var failureStage: FailureStage?
    /// Sequence space is a transport bound separate from the peer's SETUP
    /// message maximum. The coordinator samples this after IF_CONFIG and before
    /// claiming a job, so large JPEG chunks can be sized safely at small ATT MTUs.
    var maximumMessagePayload: Int { min(4096, 127 * (min(protocolMTU, platformWriteLimit) - 1)) }
    var closed: Bool { state == .closed }
    var hasBytes: Bool { state == .replyReady && !input.isEmpty }
    var hasSpace: Bool { state == .idle }

    init(io: BLEPacketIO, clock: @escaping () -> TimeInterval, policy: Policy = .readOnly,
         setupTimeout: TimeInterval = 10) {
        self.io = io; self.clock = clock; self.policy = policy; self.setupTimeout = setupTimeout
    }

    func open(_ handler: @escaping (AccessoryIOEvent) -> Void) {
        guard state == .unopened else { return }
        self.handler = handler
        let now = clock()
        guard now.isFinite, (now + 300).isFinite,
              setupTimeout.isFinite, setupTimeout > 0, setupTimeout <= 90 else {
            fail("Invalid BLE monotonic clock or setup deadline"); return
        }
        lastTime = now; overallDeadline = now + 300; setupDeadline = now + setupTimeout
        exchangeDeadline = setupDeadline
        state = .waitingReady
        io.open { [weak self] event in self?.enqueue(event) }
    }

    /// Call beside AccessoryStreamDriver.tick(), including while connecting or
    /// waiting for a write callback. No callback or deadline causes a retry.
    func tick() {
        guard state != .unopened, !closed else { return }
        guard checkTime() else { return }
        process()
    }

    func read(maximum: Int) -> AccessoryRead {
        guard !closed else { return failureReason == nil ? .ended : .failed }
        guard maximum > 0 else { fail("Invalid virtual BLE read bound"); return .failed }
        guard hasBytes else { return .wouldBlock }
        let count = min(maximum, input.count), bytes = Array(input.prefix(count))
        input.removeFirst(count)
        if input.isEmpty { state = .idle }
        return .bytes(bytes)
    }

    func write(_ bytes: [UInt8]) -> Int {
        guard !closed, checkTime() else { return -1 }
        guard state == .idle else { return 0 }
        // The upstream frame gate commits/authorizes the complete virtual frame
        // before invoking us. Reject a malformed/oversized message before the
        // first BLE fragment; never truncate or silently re-chunk its payload.
        do {
            let payload = try Self.payload(bytes)
            guard ReadOnlyFrameGate.allows(payload) ||
                    (policy == .singleJobSubmission && [12,14,48].contains(payload.first ?? 0)) else {
                throw BLEPacketCodec.Failure.invalid("BLE output policy refused a mutating or unknown request")
            }
            try prepare(payload, configuring: false)
            virtualWriteInProgress = true
            defer { virtualWriteInProgress = false }
            sendNext()
            return closed ? -1 : bytes.count
        } catch {
            fail("BLE virtual frame rejected: \(error)"); return -1
        }
    }

    func close() {
        guard !closed else { return }
        state = .closed; handler = nil; events.removeAll(); input.removeAll()
        output.removeAll(); response = nil; inFlight = nil; ackQueue = 0
        io.close()
    }

    deinit { close() }

    private static func payload(_ frame: [UInt8]) throws -> [UInt8] {
        guard frame.count >= 5, frame.prefix(3) == [72,80,43], [1,2].contains(frame[3]) else {
            throw BLEPacketCodec.Failure.invalid("Malformed virtual HP+ frame")
        }
        let width = Int(frame[3]), header = 4 + width
        guard frame.count >= header else { throw BLEPacketCodec.Failure.invalid("Truncated virtual HP+ header") }
        let size = Int(frame[4]) + (width == 2 ? Int(frame[5]) << 8 : 0)
        guard size > 0, size <= 4096, frame.count == header + size else {
            throw BLEPacketCodec.Failure.invalid("Virtual HP+ message bound or length mismatch")
        }
        return Array(frame.dropFirst(header))
    }

    private static func frame(_ message: [UInt8]) -> [UInt8] {
        [72,80,43] + (message.count < 256 ? [1,UInt8(message.count)] :
            [2,UInt8(message.count & 255),UInt8(message.count >> 8)]) + message
    }

    private func prepare(_ message: [UInt8], configuring: Bool) throws {
        output = try BLEPacketCodec.fragments(message, packetLimit: min(platformWriteLimit, protocolMTU))
        outputIndex = 0; inFlight = nil; ackQueue = 0
        response = nil; receiver = BLEPacketCodec()
        exchangeDeadline = configuring ? min(clock() + 10, setupDeadline) : clock() + 10
        state = configuring ? .configuring : .exchanging
    }

    private func enqueue(_ event: BLEPacketIOEvent) {
        guard !closed else { return }
        guard events.count < 256 else { fail("BLE callback queue bound exceeded"); return }
        events.append(event)
        // If native callbacks are inline, do not deliver a virtual response until
        // the caller has recorded our complete-frame write return value.
        if !virtualWriteInProgress { process() }
    }

    private func process() {
        guard !processing, !virtualWriteInProgress, !closed else { return }
        processing = true
        defer { processing = false }
        var iterations = 0
        while !closed {
            guard checkTime() else { return }
            iterations += 1
            // An entirely inline simulated peer can complete many exchanges in
            // this stack. Yield bounded work to tick(), retaining queued events;
            // ordinary large transfers must not fail merely for being inline.
            guard iterations <= 1024 else { return }
            if !events.isEmpty {
                let event = events.removeFirst()
                handle(event)
                if closed { return }
            }
            sendNext()
            if closed { return }
            finishResponseIfReady()
            if events.isEmpty { return }
        }
    }

    private func handle(_ event: BLEPacketIOEvent) {
        switch event {
        case .ready(let limit):
            guard state == .waitingReady, (20...65536).contains(limit) else {
                fail("Unexpected BLE readiness or invalid platform write limit"); return
            }
            platformWriteLimit = limit
            do { try prepare([10,1,0], configuring: true) }
            catch { fail("BLE configure preparation failed: \(error)") }
        case .written:
            guard let pending = inFlight, state == .configuring || state == .exchanging else {
                fail("Unexpected BLE write callback"); return
            }
            inFlight = nil; writeCallbacks += 1; txAcknowledgedBytes += pending.count
        case .notification(let packet):
            guard state == .configuring || state == .exchanging,
                  response == nil, outputIndex == output.count else {
                fail("Unsolicited or premature BLE response"); return
            }
            rxBytes += packet.count
            guard rxBytes <= 32 * 1024 * 1024 else { fail("BLE receive byte bound exceeded"); return }
            do {
                let event = try receiver.receive(packet, ackPeriod: acknowledgementPeriod, packetLimit: protocolMTU)
                if event.acknowledge {
                    ackQueue += 1
                    guard ackQueue <= 127 else { fail("BLE acknowledgement queue bound exceeded"); return }
                }
                if let message = event.message { response = message }
            } catch { fail("BLE notification rejected: \(error)") }
        case .failed: fail("BLE native IO failed; no retry")
        case .ended: fail("BLE connection ended; no retry", ended: true)
        }
    }

    private func sendNext() {
        guard !closed, inFlight == nil, state == .configuring || state == .exchanging else { return }
        let packet: [UInt8], kind: WriteKind
        if ackQueue > 0 {
            ackQueue -= 1; packet = [0]; kind = .acknowledgement
        } else if outputIndex < output.count {
            packet = output[outputIndex]; outputIndex += 1; kind = .request
        } else { return }
        guard !packet.isEmpty, packet.count <= min(platformWriteLimit, protocolMTU),
              txQueuedBytes + packet.count <= 32 * 1024 * 1024 else {
            fail("BLE packet/transmit byte bound exceeded"); return
        }
        inFlight = PendingWrite(kind:kind,count:packet.count)
        txQueuedBytes += packet.count
        if !io.write(packet) { fail("BLE native packet write refused; no retry") }
    }

    private func finishResponseIfReady() {
        guard !closed, inFlight == nil, ackQueue == 0, outputIndex == output.count,
              let message = response else { return }
        response = nil; output.removeAll(); outputIndex = 0; exchangeDeadline = nil
        if state == .configuring {
            guard message.count == 5, message[0] == 11, message[1] == 1 else {
                fail("Malformed BLE IF_CONFIG response"); return
            }
            let mtu = Int(message[2]) | (Int(message[3]) << 8), ack = Int(message[4])
            guard (20...4097).contains(mtu), (0...127).contains(ack) else {
                fail("Unsupported BLE protocol MTU/acknowledgement period"); return
            }
            protocolMTU = mtu; acknowledgementPeriod = ack; state = .idle
            handler?(.opened(.input))
            if !closed { handler?(.opened(.output)) }
        } else if state == .exchanging {
            input = Self.frame(message); state = .replyReady
            handler?(.readable)
        } else { fail("Unexpected completed BLE response") }
    }

    @discardableResult private func checkTime() -> Bool {
        let now = clock()
        guard now.isFinite, now >= lastTime, now < overallDeadline,
              exchangeDeadline.map({ now < $0 }) ?? true else {
            fail("BLE setup/exchange/overall deadline or monotonic clock violation; no retry"); return false
        }
        lastTime = now; return true
    }

    private func fail(_ reason: String, ended: Bool = false) {
        guard !closed else { return }
        switch state {
        case .unopened, .waitingReady: failureStage = .connection
        case .configuring: failureStage = .setup
        default: failureStage = .exchange
        }
        failureReason = reason
        let callback = handler
        close()
        callback?(ended ? .ended : .failed)
    }
}
