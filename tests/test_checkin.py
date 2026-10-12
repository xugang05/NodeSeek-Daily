"""Attendance regressions. No live account, requests, cookies or browser needed."""
import contextlib
import io
import os
import unittest
from unittest.mock import MagicMock, patch

import nodeseek_daily as daily


def browser():
    driver = MagicMock()
    driver.current_url = "https://www.nodeseek.com/board"
    driver.title = "NodeSeek"
    driver.find_elements.return_value = []
    return driver


class AttendanceResponseTests(unittest.TestCase):
    def test_explicit_success(self):
        self.assertEqual(daily.interpret_attendance({"status": 200, "data": {"success": True, "gain": 5}}), "success")

    def test_exact_already_done_response(self):
        for suffix in ("", "。", "！"):
            self.assertEqual(daily.interpret_attendance({"status": 200, "data": {
                "success": False, "message": daily.ALREADY_CHECKED_IN + suffix}}), "already_checked_in")

    def test_fail_closed_for_unconfirmed_results(self):
        cases = [None, [], {}, {"error": "timeout"}, {"status": 200, "data": None},
                 {"status": 200, "data": []}, {"status": 200, "data": {}},
                 {"status": 200, "data": {"success": "true"}},
                 {"status": 200, "data": {"success": 1}},
                 {"status": 200, "data": {"message": "签到失败，但页面显示已签到"}},
                 {"status": 200, "data": {"message": "获得鸡腿失败"}},
                 {"status": 200, "data": {"message": "尚未完成签到"}},
                 {"status": 200, "data": {"message": "昨天已完成签到，请勿重复操作"}},
                 {"status": 200, "data": {"success": False, "message": "unknown"}}]
        for response in cases:
            with self.subTest(response=response), self.assertRaises(daily.CheckinError):
                daily.interpret_attendance(response)

    def test_http_errors_override_success_payload(self):
        for status in (302, 401, 403, 429, 500, "200", True, None):
            with self.subTest(status=status), self.assertRaises(daily.CheckinError):
                daily.interpret_attendance({"status": status, "data": {"success": True}})

    def test_challenge_overrides_success_payload(self):
        with self.assertRaisesRegex(daily.CheckinError, "challenge"):
            daily.interpret_attendance({"status": 200, "challenge": True, "data": {"success": True}})

    def test_login_failure_is_actionable(self):
        with self.assertRaisesRegex(daily.CheckinError, "unauthenticated"):
            daily.interpret_attendance({"status": 200, "data": {"success": False, "message": "请先登录"}})


class AttendanceBrowserTests(unittest.TestCase):
    def test_submits_configured_mode_and_checks_result(self):
        for setting, expected in (("true", "true"), ("TRUE", "true"), ("false", "false"), ("", "false")):
            driver = browser()
            driver.execute_async_script.return_value = {"status": 200, "data": {"success": True, "gain": 5}}
            with self.subTest(setting=setting), patch.dict(os.environ, {"NS_RANDOM": setting}):
                self.assertTrue(daily.click_sign_icon(driver))
            driver.get.assert_called_once_with("https://www.nodeseek.com/board")
            driver.execute_async_script.assert_called_once_with(daily.ATTENDANCE_SCRIPT, expected)
            driver.find_element.assert_not_called()  # No brittle reward-button locator.

    def test_missing_confirmation_does_not_succeed(self):
        driver = browser()
        driver.execute_async_script.return_value = {"status": 200, "data": {"success": False}}
        self.assertFalse(daily.click_sign_icon(driver))

    def test_exception_does_not_succeed_or_leak(self):
        driver = browser()
        driver.execute_async_script.side_effect = RuntimeError("PRIVATE_COOKIE_VALUE")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(daily.click_sign_icon(driver))
        self.assertNotIn("PRIVATE_COOKIE_VALUE", output.getvalue())

    def test_raw_server_message_and_account_details_not_logged(self):
        driver = browser()
        driver.execute_async_script.return_value = {"status": 200, "data": {
            "success": False, "message": "PRIVATE_COOKIE_VALUE", "current": "PRIVATE_ACCOUNT_DATA"}}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(daily.click_sign_icon(driver))
        self.assertNotIn("PRIVATE_", output.getvalue())

    @patch.object(daily.time, "sleep")
    def test_no_post_when_page_is_login_challenge_or_wrong_origin(self, sleep):
        for url, title, elements in (
            ("https://www.nodeseek.com/login", "NodeSeek", []),
            ("https://www.nodeseek.com/signIn", "NodeSeek", []),
            ("https://www.nodeseek.com/board", "Just a moment...", []),
            ("https://www.nodeseek.com/board", "NodeSeek", [object()]),
            ("https://example.com/board", "NodeSeek", []),
            ("http://www.nodeseek.com/board", "NodeSeek", []),
        ):
            driver = browser()
            driver.current_url, driver.title, driver.find_elements.return_value = url, title, elements
            with self.subTest(url=url, title=title):
                self.assertFalse(daily.click_sign_icon(driver))
            driver.execute_async_script.assert_not_called()


class ChallengeSettleTests(unittest.TestCase):
    @patch.object(daily.time, "sleep")
    def test_transient_challenge_gets_one_passive_settle(self, sleep):
        driver = browser()
        driver.title = "Just a moment..."
        sleep.side_effect = lambda seconds: setattr(driver, "title", "NodeSeek")
        daily.check_page(driver)
        sleep.assert_called_once_with(8)
        driver.get.assert_not_called()
        driver.execute_script.assert_not_called()
        driver.execute_async_script.assert_not_called()

    @patch.object(daily.time, "sleep")
    def test_persistent_challenge_fails_and_cannot_wait_again(self, sleep):
        driver = browser()
        driver.title = "Just a moment..."
        for _ in range(2):
            with self.assertRaisesRegex(daily.CheckinError, "challenge"):
                daily.check_page(driver)
        sleep.assert_called_once_with(8)

    @patch.object(daily.time, "sleep")
    def test_login_failure_does_not_wait(self, sleep):
        driver = browser()
        driver.current_url = "https://www.nodeseek.com/signIn"
        with self.assertRaisesRegex(daily.CheckinError, "unauthenticated"):
            daily.check_page(driver)
        sleep.assert_not_called()


class CookieAndExitTests(unittest.TestCase):
    @patch.object(daily, "create_browser")
    def test_invalid_cookie_fails_before_browser(self, create):
        for value in (" ", ";", "bad", "=value", "good=value;bad"):
            with self.subTest(value=value), patch.dict(os.environ, {"NS_COOKIE": value}, clear=True):
                self.assertIsNone(daily.setup_driver_and_cookies())
        create.assert_not_called()

    @patch.object(daily, "create_browser")
    def test_cookie_values_with_equals_and_trailing_semicolon(self, create):
        create.return_value = browser()
        with patch.dict(os.environ, {"NS_COOKIE": "a=fake==; b=;"}, clear=True):
            self.assertIs(daily.setup_driver_and_cookies(), create.return_value)
        self.assertEqual(create.return_value.add_cookie.call_args_list[0].args[0]["value"], "fake==")
        self.assertEqual(create.return_value.add_cookie.call_count, 2)
        self.assertEqual(create.return_value.add_cookie.call_args_list[1].args[0]["value"], "")

    @patch.object(daily, "create_browser")
    def test_initial_login_page_can_receive_cookie_then_navigate_home(self, create):
        driver = create.return_value = browser()
        def navigate(url):
            driver.current_url = ("https://www.nodeseek.com/signIn" if driver.get.call_count == 1
                                  else "https://www.nodeseek.com/")
        driver.get.side_effect = navigate
        with patch.dict(os.environ, {"NS_COOKIE": "test=fake"}, clear=True):
            self.assertIs(daily.setup_driver_and_cookies(), driver)
        self.assertEqual(driver.get.call_count, 2)
        driver.add_cookie.assert_called_once()
        driver.quit.assert_not_called()

    @patch.object(daily, "create_browser")
    def test_cookie_failure_closes_browser_without_leaking(self, create):
        create.return_value = browser()
        create.return_value.add_cookie.side_effect = RuntimeError("PRIVATE_COOKIE_VALUE")
        output = io.StringIO()
        with patch.dict(os.environ, {"NS_COOKIE": "test=fake"}, clear=True), contextlib.redirect_stdout(output):
            self.assertIsNone(daily.setup_driver_and_cookies())
        create.return_value.quit.assert_called_once()
        self.assertNotIn("PRIVATE_COOKIE_VALUE", output.getvalue())

    @patch.object(daily, "setup_driver_and_cookies", return_value=None)
    def test_initialization_failure_exit_status(self, setup):
        self.assertEqual(daily.main(), 1)

    @patch.object(daily, "click_sign_icon")
    @patch.object(daily, "setup_driver_and_cookies")
    def test_exit_status_and_cleanup(self, setup, checkin):
        for success in (True, False):
            setup.return_value = browser()
            checkin.return_value = success
            self.assertEqual(daily.main(), 0 if success else 1)
            setup.return_value.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
