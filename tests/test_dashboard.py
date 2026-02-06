# import pytest (Removed to allow direct execution)
from playwright.sync_api import Page, expect

# Usage: py -m pytest tests/test_dashboard.py
# Or: py tests/test_dashboard.py (if using direct run block)


def test_dashboard_load(page: Page):
    # Adjust URL if needed
    response = page.goto("http://localhost:8000/dashboard.html")
    assert response.status == 200, "Dashboard page load failed"

    # Verify Title
    expect(page).to_have_title("分析工具")

    # Verify External CSS and JS loaded
    # We check if the elements exist in DOM and if they load successfully
    # Check CSS Response
    with page.expect_response("**/static/css/styles.css") as response_info:
        page.reload()  # Reload to trigger network requests
        response = response_info.value
        assert response.status == 200, f"CSS load failed with {response.status}"

    # Check JS Response
    with page.expect_response("**/static/js/dashboard.js") as response_info:
        page.reload()
        response = response_info.value
        assert response.status == 200, f"JS load failed with {response.status}"

    css = page.locator('link[href="/static/css/styles.css"]')
    expect(css).to_be_attached()

    js = page.locator('script[src="/static/js/dashboard.js"]')
    expect(js).to_be_attached()

    # Verify Sidebar
    expect(page.locator("#sidebar")).to_be_visible()

    # Verify Content Areas available (hidden or visible)
    # By default, 'view-files' might be visible
    # Start: switch to dashboard view
    page.evaluate("switchView('dashboard')")
    expect(page.locator("#view-dashboard")).to_be_visible()

    # Verify Status Text Initializing
    # expect(page.locator('#status-text')).to_contain_text("Initializing")


def test_files_tab(page: Page):
    page.goto("http://localhost:8000/dashboard.html")

    # Switch to Files
    page.click("#nav-files")
    expect(page.locator("#view-files")).to_be_visible()

    # Check Upload Button
    expect(page.locator("text=上傳新檔案")).to_be_visible()


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            test_dashboard_load(page)
            print("✅ test_dashboard_load passed")
            test_files_tab(page)
            print("✅ test_files_tab passed")
        except Exception as e:
            print(f"❌ Test Failed: {e}")
        finally:
            browser.close()
