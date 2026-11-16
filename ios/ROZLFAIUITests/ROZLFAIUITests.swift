import XCTest

final class ROZLFAIUITests: XCTestCase {
    func testLaunchOpensAndBottomScanTabWorks() {
        let app = XCUIApplication()
        app.launchArguments += ["--uitest"]
        app.launch()
        let scan = app.buttons["nexus.tab.scan"]
        XCTAssertTrue(scan.waitForExistence(timeout: 8))
        scan.tap()
        let action = app.buttons["nexus.scan.now"]
        XCTAssertTrue(action.isHittable)
        action.tap()
        XCTAssertTrue(app.staticTexts["اضبط اتصال المحرك من الإعدادات أولاً."].exists)
    }

    func testSettingsAndServicesAreReachable() {
        let app = XCUIApplication()
        app.launchArguments += ["--uitest"]
        app.launch()
        let settings = app.buttons["nexus.tab.settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 8))
        settings.tap()
        XCTAssertTrue(app.buttons["nexus.connect"].exists)
        app.buttons["nexus.tab.services"].tap()
        XCTAssertTrue(app.staticTexts["تحليل الرسم البياني"].exists)
    }
}
