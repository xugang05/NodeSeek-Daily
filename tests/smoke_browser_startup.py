"""Opt-in real-browser smoke test. Never logs in or visits NodeSeek."""

import unittest

from nodeseek_daily import create_browser, resolve_chrome_binary


class BrowserStartupSmokeTest(unittest.TestCase):
    def test_browser_and_driver_majors_match(self):
        executable, expected_major = resolve_chrome_binary()
        driver = create_browser(headless=True)
        try:
            browser_version = driver.capabilities["browserVersion"]
            driver_version = driver.capabilities["chrome"]["chromedriverVersion"].split()[0]
            self.assertEqual(int(browser_version.split(".")[0]), expected_major)
            self.assertEqual(int(driver_version.split(".")[0]), expected_major)
            driver.get("data:text/html,<title>Browser startup smoke test</title>")
            self.assertEqual(driver.title, "Browser startup smoke test")
            self.assertTrue(driver.current_url.startswith("data:text/html,"))
            print(f"Smoke test passed: {executable}; browser={browser_version}; driver={driver_version}")
        finally:
            driver.quit()


if __name__ == "__main__":
    unittest.main()
