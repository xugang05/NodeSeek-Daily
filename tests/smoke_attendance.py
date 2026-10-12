"""Real Chrome + local fake API integration; never contacts NodeSeek or uses secrets."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

import nodeseek_daily as daily


class AttendanceTransportSmokeTest(unittest.TestCase):
    def test_browser_fetch_and_response_verification(self):
        requests = []
        reply = {"status": 200, "body": {"success": True, "gain": 5}}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<title>Local attendance test</title>")

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                requests.append((self.path, self.headers.get("Cookie"), json.loads(body)))
                self.send_response(reply["status"])
                if reply["status"] == 302:
                    self.send_header("Location", "/login")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                payload = reply["body"]
                self.wfile.write((payload if isinstance(payload, str) else json.dumps(payload)).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        driver = None
        try:
            driver = daily.create_browser()
            driver.set_script_timeout(25)
            driver.get(f"http://127.0.0.1:{server.server_port}/board")
            driver.add_cookie({"name": "fake_session", "value": "test-only", "httpOnly": True, "path": "/"})
            for random_reward in ("false", "true"):
                response = driver.execute_async_script(daily.ATTENDANCE_SCRIPT, random_reward)
                self.assertEqual(daily.interpret_attendance(response), "success")
                self.assertEqual(requests[-1], (
                    "/api/attendance?random=" + random_reward,
                    "fake_session=test-only", {"random": random_reward == "true"}))

            reply["body"] = {"success": False, "message": daily.ALREADY_CHECKED_IN}
            response = driver.execute_async_script(daily.ATTENDANCE_SCRIPT, "false")
            self.assertEqual(daily.interpret_attendance(response), "already_checked_in")

            for status, payload, expected in (
                (200, {"success": False, "message": "请先登录"}, "unauthenticated"),
                (401, {"success": True}, "unauthenticated"),
                (500, {"success": True}, "http_error"),
                (200, "<html>unexpected HTML</html>", "invalid_response"),
                (403, "<html><title>Just a moment...</title></html>", "challenge"),
                (302, {}, "request_failed"),
            ):
                reply.update(status=status, body=payload)
                response = driver.execute_async_script(daily.ATTENDANCE_SCRIPT, "false")
                with self.subTest(status=status, expected=expected), self.assertRaisesRegex(daily.CheckinError, expected):
                    daily.interpret_attendance(response)
        finally:
            if driver is not None:
                driver.quit()
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
