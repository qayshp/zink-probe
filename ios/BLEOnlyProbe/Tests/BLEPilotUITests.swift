import XCTest

final class BLEPilotUITests: XCTestCase {
    private let app = XCUIApplication()
    private let workspace = UUID().uuidString

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSavedPhotoSurvivesUnavailablePrinterThenClockSyncAndOneSheet() {
        launch("unavailable")
        savePhoto()
        checkPrinter()
        expectStatus("reach the printer", id: "ble-pilot-status")
        app.terminate()

        launch("clock")
        XCTAssertTrue(app.images["ble-pilot-draft-preview"].exists)
        checkPrinter()
        tap("ble-pilot-clock")
        let syncButton = app.buttons.matching(
            NSPredicate(format: "identifier == %@ OR label == %@", "ble-pilot-sync-confirm", "Sync clock only")
        ).firstMatch
        XCTAssertTrue(syncButton.waitForExistence(timeout: 5))
        syncButton.tap()
        tap("ble-pilot-recheck")
        tap("ble-pilot-review")
        tap("ble-pilot-confirm")
        tap("Cancel")
        tap("Close")
        XCTAssertFalse(app.staticTexts["Last print attempt"].exists)
        tap("ble-pilot-review")
        confirmPrint()
        expectStatus("Protocol completion observed", id: "ble-pilot-print-status")
        XCTAssertTrue(app.buttons["Share last print report"].waitForExistence(timeout: 5))
    }

    func testAProvenPreSubmissionStopOffersFreshReview() {
        launch("stoppedBeforeSend")
        savePhoto()
        checkPrinter()
        tap("ble-pilot-review")
        confirmPrint()
        expectStatus("Stopped before submission", id: "ble-pilot-print-status")
        tap("Close")
        tap("ble-pilot-prepare-retry")
        tap("ble-pilot-review")
        confirmPrint()
        expectStatus("Protocol completion observed", id: "ble-pilot-print-status")
    }

    func testLostAllocationReplyStaysBlockedAfterRelaunch() {
        launch("uncertain")
        savePhoto()
        checkPrinter()
        tap("ble-pilot-review")
        confirmPrint()
        expectStatus("Print outcome uncertain", id: "ble-pilot-print-status")
        app.terminate()

        launch("uncertain")
        XCTAssertTrue(app.staticTexts["Print outcome uncertain"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["ble-pilot-prepare-retry"].exists)
        XCTAssertFalse(app.buttons["ble-pilot-confirm"].exists)
        savePhoto()
        checkPrinter()
        expectStatus("Check the previous print outcome", id: "ble-pilot-status")
        XCTAssertFalse(app.buttons["ble-pilot-discard-earlier"].exists)
        XCTAssertFalse(app.buttons["ble-pilot-review"].exists)
    }

    func testNewPhotoWaitsForExplicitDiscardOfEarlierDraft() {
        launch("stoppedBeforeSend")
        savePhoto()
        checkPrinter()
        expectStatus("Review the saved photo", id: "ble-pilot-status")

        tap("ble-pilot-photo")
        tap("select-photo-rotate-right")
        tap("review-bound-draft")
        tap("ble-pilot-recheck")
        expectStatus("Discard the earlier draft", id: "ble-pilot-status")
        XCTAssertFalse(app.buttons["ble-pilot-review"].exists)
        XCTAssertFalse(app.buttons["Review saved photo"].exists)
        tap("ble-pilot-discard-earlier")
        tap("Keep draft")
        XCTAssertTrue(app.buttons["ble-pilot-discard-earlier"].exists)
        tap("ble-pilot-discard-earlier")
        tap("Discard draft")
        XCTAssertTrue(app.images["ble-pilot-draft-preview"].exists)
        tap("ble-pilot-recheck")
        tap("ble-pilot-review")
        XCTAssertTrue(app.buttons["ble-pilot-confirm"].exists)
        tap("Close")
        XCTAssertFalse(app.staticTexts["Last print attempt"].exists)
    }

    func testRotatedPhotoCanBeReviewedAfterRelaunch() {
        launch("stoppedBeforeSend")
        tap("ble-pilot-photo")
        tap("select-photo-jpeg-settings")
        let fileSizeLabel = "File size: "
        let fileSize = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", fileSizeLabel))
        XCTAssertTrue(fileSize.firstMatch.waitForExistence(timeout: 5))
        let originalSize = fileSize.firstMatch.label
        XCTAssertTrue(app.buttons["select-photo-rotate-left"].exists)
        tap("select-photo-rotate-right")
        let rotatedSize = fileSize.matching(NSPredicate(format: "label != %@", originalSize)).firstMatch
        XCTAssertTrue(rotatedSize.waitForExistence(timeout: 5))
        let reviewSize = String(rotatedSize.label.dropFirst(fileSizeLabel.count))
        tap("review-bound-draft")
        XCTAssertTrue(app.images["ble-pilot-draft-preview"].waitForExistence(timeout: 5))
        app.terminate()

        launch("stoppedBeforeSend")
        XCTAssertTrue(app.images["ble-pilot-draft-preview"].waitForExistence(timeout: 5))
        checkPrinter()
        tap("ble-pilot-review")
        tap("ble-pilot-technical-details")
        let review = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", reviewSize)).firstMatch
        XCTAssertTrue(review.waitForExistence(timeout: 5))
        tap("Close")
        XCTAssertFalse(app.staticTexts["Last print attempt"].exists)
    }

    private func launch(_ scenario: String) {
        app.launchEnvironment = [
            "ZINK_PILOT_FIXTURE_STORE": workspace,
            "ZINK_PILOT_FIXTURE_SCENARIO": scenario
        ]
        app.launch()
        tap("Prepare one BLE print")
    }

    private func savePhoto() {
        tap("ble-pilot-photo")
        tap("review-bound-draft")
        XCTAssertTrue(app.images["ble-pilot-draft-preview"].waitForExistence(timeout: 5))
    }

    private func checkPrinter() {
        tap("ble-pilot-scan")
        tap("ble-pilot-select-printer")
    }

    private func confirmPrint() {
        tap("ble-pilot-confirm")
        tap("Print one sheet")
    }

    private func expectStatus(_ text: String, id: String, file: StaticString = #filePath, line: UInt = #line) {
        let status = app.staticTexts.matching(identifier: id)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", text)).firstMatch
        XCTAssertTrue(status.waitForExistence(timeout: 8), "Expected \(text)", file: file, line: line)
    }

    private func tap(_ id: String, file: StaticString = #filePath, line: UInt = #line) {
        let button = app.buttons[id].firstMatch
        let screen = app.frame.insetBy(dx: 0, dy: 40)
        for direction in [true, false] {
            for _ in 0..<4 {
                if button.exists && button.isHittable && button.isEnabled &&
                    screen.contains(CGPoint(x: button.frame.midX, y: button.frame.midY)) {
                    button.tap()
                    return
                }
                if direction { app.swipeUp() } else { app.swipeDown() }
            }
        }
        XCTAssertTrue(button.waitForExistence(timeout: 5) && button.isHittable && button.isEnabled,
                      "Cannot tap \(id)", file: file, line: line)
        if button.exists && button.isHittable && button.isEnabled { button.tap() }
    }
}
