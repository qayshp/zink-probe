import Foundation

enum AccessoryIOEvent { case opened(AccessoryStreamPump.Side), readable, writable, failed, ended }
enum AccessoryRead { case bytes([UInt8]), wouldBlock, ended, failed }
protocol AccessoryDuplex: AnyObject {
    var hasBytes: Bool { get }
    var hasSpace: Bool { get }
    func open(_ handler: @escaping (AccessoryIOEvent) -> Void)
    func read(maximum: Int) -> AccessoryRead
    func write(_ bytes: [UInt8]) -> Int
    func close()
}

/// Serial-use owner. Native IO dispatches all callbacks on the main run loop;
/// tests supply a deterministic duplex. Closing is idempotent, with no reconnect.
final class AccessoryStreamDriver {
    let pump: AccessoryStreamPump
    private let io: AccessoryDuplex
    private let clock: () -> TimeInterval
    private let update: (AccessoryStreamPump) -> Void
    private var started = false, driving = false
    private(set) var closed = false
    init(pump: AccessoryStreamPump, io: AccessoryDuplex, clock: @escaping () -> TimeInterval,
         update: @escaping (AccessoryStreamPump) -> Void) {
        self.pump = pump; self.io = io; self.clock = clock; self.update = update
    }
    deinit { if started && !closed { pump.stop("Accessory driver released; no retry"); io.close() } }
    func start() {
        guard !started, !closed else { return }; started = true
        io.open { [weak self] event in self?.handle(event) }
        finish()
    }
    func tick() { handle(nil) }
    func cancel(_ reason: String) {
        guard !closed else { return }; pump.stop(reason); finish()
    }
    private func handle(_ event: AccessoryIOEvent?) {
        guard started, !closed, !driving else { return }; driving = true
        defer { driving = false; finish() }
        let now = clock()
        switch event {
        case .opened(let side): pump.opened(side,now:now)
        case .failed: pump.stop("Accessory stream error; no retry")
        case .ended: pump.stop("Accessory stream ended; no retry")
        default: break
        }
        pump.tick(now:now)
        guard !pump.terminal else { return }
        for _ in 0..<16 {
            guard io.hasBytes, !pump.terminal else { break }
            switch io.read(maximum:512) {
            case .bytes(let bytes): pump.receive(bytes,now:clock())
            case .wouldBlock: return
            case .ended: pump.stop("Accessory input ended; no retry")
            case .failed: pump.stop("Accessory input read failed; no retry")
            }
        }
        if !pump.terminal, io.hasSpace { pump.writable(now:clock(),writer:io.write) }
    }
    private func finish() {
        guard !closed else { return }
        if pump.terminal { closed = true; io.close() }
        update(pump)
    }
}
