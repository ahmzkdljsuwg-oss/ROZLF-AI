import XCTest

final class ROZLFAIUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSetupRejectsNonHTTPSAddress() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-rozlf.baseURL", ""]
        app.launch()

        let field = app.textFields["serverField"]
        XCTAssertTrue(field.waitForExistence(timeout: 8))
        field.tap()
        field.typeText("http://example.com")
        app.buttons["connectButton"].tap()

        XCTAssertTrue(app.staticTexts["Enter a valid HTTPS address. HTTP is accepted only for localhost."].waitForExistence(timeout: 3))
    }

    func testConfiguredServerShowsConnectionState() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-rozlf.baseURL", "https://invalid.example.invalid"]
        app.launch()

        XCTAssertTrue(app.otherElements["connectionBadge"].waitForExistence(timeout: 10)
                      || app.staticTexts["OFFLINE"].waitForExistence(timeout: 10))
    }
}
