"""Browser selection regressions; all browser and network calls are mocked."""

import os
import subprocess
import unittest
from unittest.mock import call, patch

import nodeseek_daily as daily


class BrowserSelectionTests(unittest.TestCase):
    @patch.object(daily.subprocess, "check_output")
    @patch.object(daily.shutil, "which")
    def test_probes_and_launches_same_binary_with_multiple_browsers(self, which, output):
        # Regression: google-chrome is 154 while UC would auto-select Chromium 153.
        which.side_effect = lambda name: {
            "google-chrome": "/usr/bin/google-chrome",
            "chromium-browser": "/usr/bin/chromium-browser",
        }.get(name)
        versions = {
            "/usr/bin/google-chrome": "Google Chrome 154.0.8037.57\n",
            "/usr/bin/chromium-browser": "Chromium 153.0.8010.47\n",
        }
        output.side_effect = lambda command, **kwargs: versions[command[0]]

        with patch.object(daily.uc, "Chrome") as chrome:
            driver = daily.create_browser()

        output.assert_called_once_with(
            ["/usr/bin/google-chrome", "--version"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertIs(driver, chrome.return_value)
        self.assertEqual(chrome.call_args.kwargs["browser_executable_path"], "/usr/bin/google-chrome")
        self.assertEqual(chrome.call_args.kwargs["version_main"], 154)

    def test_each_supported_browser_name(self):
        for name, version in (
            ("google-chrome", "Google Chrome 154.0.8037.57"),
            ("chromium-browser", "Chromium 153.0.8010.47"),
            ("google-chrome-stable", "Google Chrome for Testing 154.0.8037.57"),
            ("chromium", "Chromium 153.0.8010.47 built on Debian"),
        ):
            with self.subTest(name=name):
                path = f"/opt/browsers/{name}"
                with patch.object(daily.shutil, "which", side_effect=lambda n: path if n == name else None), \
                        patch.object(daily.subprocess, "check_output", return_value=version) as output:
                    executable, major = daily.resolve_chrome_binary()
                self.assertEqual(executable, path)
                self.assertEqual(major, 153 if name.startswith("chromium") else 154)
                self.assertEqual(output.call_args.args[0], [path, "--version"])

    def test_unusable_candidate_falls_back(self):
        failures = (
            FileNotFoundError("missing"),
            PermissionError("not executable"),
            subprocess.CalledProcessError(1, "chrome"),
            subprocess.TimeoutExpired("chrome", 10),
            "browser version unavailable",
        )
        for failure in failures:
            with self.subTest(failure=failure):
                with patch.object(daily.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"), \
                        patch.object(daily.subprocess, "check_output", side_effect=[failure, "Chromium 153.0.8010.47"]):
                    self.assertEqual(daily.resolve_chrome_binary(), ("/usr/bin/chromium-browser", 153))

    @patch.object(daily.shutil, "which", return_value="/usr/bin/google-chrome")
    @patch.object(daily.subprocess, "check_output", return_value="wrapper warning: library 2.3.4\nGoogle Chrome 154.0.8037.57\n")
    def test_ignores_unrelated_version_in_warning(self, output, which):
        self.assertEqual(daily.resolve_chrome_binary(), ("/usr/bin/google-chrome", 154))

    @patch.object(daily.shutil, "which", return_value="bin/chromium")
    @patch.object(daily.subprocess, "check_output", return_value="Chromium 153.0.8010.47")
    def test_resolves_relative_path_before_probing(self, output, which):
        executable, _ = daily.resolve_chrome_binary()
        self.assertEqual(executable, os.path.abspath("bin/chromium"))
        self.assertEqual(output.call_args.args[0][0], executable)

    @patch.object(daily.uc, "Chrome")
    @patch.object(daily.shutil, "which", return_value=None)
    @patch.object(daily.subprocess, "check_output")
    def test_missing_browser_fails_before_driver_creation(self, output, which, chrome):
        with self.assertRaisesRegex(RuntimeError, "Chrome/Chromium"):
            daily.create_browser()
        output.assert_not_called()
        chrome.assert_not_called()

    @patch.object(daily.uc, "Chrome")
    @patch.object(daily.shutil, "which", return_value="/usr/bin/google-chrome")
    @patch.object(daily.subprocess, "check_output")
    def test_unknown_version_does_not_use_automatic_driver(self, output, which, chrome):
        for version in ("unrecognized 1.2.3", "Google Chrome 0.0.0.0"):
            with self.subTest(version=version):
                output.return_value = version
                with self.assertRaisesRegex(RuntimeError, "版本号"):
                    daily.create_browser()
        chrome.assert_not_called()


class BrowserStartupTests(unittest.TestCase):
    @patch.object(daily, "resolve_chrome_binary", return_value=("/usr/bin/chromium", 153))
    @patch.object(daily.uc, "Chrome")
    def test_startup_options_and_no_site_or_cookie_activity(self, chrome, resolve):
        for headless in (True, False):
            with self.subTest(headless=headless):
                chrome.reset_mock()
                with patch.dict(os.environ, {"NS_COOKIE": "test=never-used"}):
                    driver = daily.create_browser(headless=headless)
                options = chrome.call_args.kwargs["options"]
                self.assertEqual("--headless" in options.arguments, headless)
                self.assertIn("--no-sandbox", options.arguments)
                self.assertIn("--disable-dev-shm-usage", options.arguments)
                self.assertEqual(options.binary_location, "")
                self.assertEqual(chrome.call_args.kwargs["browser_executable_path"], "/usr/bin/chromium")
                self.assertEqual(chrome.call_args.kwargs["version_main"], 153)
                driver.get.assert_not_called()
                driver.add_cookie.assert_not_called()
                driver.refresh.assert_not_called()
                if headless:
                    driver.set_window_size.assert_called_once_with(1920, 1080)
                else:
                    driver.execute_script.assert_not_called()
                    driver.set_window_size.assert_not_called()

    @patch.object(daily, "create_browser")
    def test_no_cookie_does_not_start_browser(self, create):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(daily.setup_driver_and_cookies())
        create.assert_not_called()

    @patch.object(daily.time, "sleep")
    @patch.object(daily, "create_browser")
    def test_cookie_setup_uses_startup_helper(self, create, sleep):
        create.return_value.current_url = "https://www.nodeseek.com/"
        create.return_value.title = "NodeSeek"
        create.return_value.find_elements.return_value = []
        with patch.dict(os.environ, {"NS_COOKIE": "test=fake", "HEADLESS": "false"}, clear=True):
            driver = daily.setup_driver_and_cookies()
        create.assert_called_once_with(headless=False)
        self.assertIs(driver, create.return_value)
        self.assertEqual(driver.get.call_args_list, [call("https://www.nodeseek.com"), call("https://www.nodeseek.com")])
        driver.add_cookie.assert_called_once_with({
            "name": "test", "value": "fake", "domain": ".nodeseek.com", "path": "/",
        })
        driver.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
