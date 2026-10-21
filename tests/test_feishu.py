import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import feishu_notify


class FeishuTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("SCRATCH_ROOT"))
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {key: "" for key in feishu_notify.WEBHOOK_FIELDS.values()})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.requests = []
        self.reply = {"code": 0}
        self.status = 200
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                case.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(case.status)
                self.end_headers()
                body = case.reply if isinstance(case.reply, bytes) else json.dumps(case.reply).encode()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.close_server)
        self.cfg = {"webhook_url": f"http://127.0.0.1:{self.server.server_port}/secret-token",
                    "webhook_secret": "", "panel_url": "https://panel.example"}
        feishu_notify.write_json(self.data_dir / "notification_config.json", {"webhook": self.cfg})

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def test_signed_text_request_matches_feishu_signature(self):
        self.cfg["webhook_secret"] = "demo"
        with patch("feishu_notify.time.time", return_value=1700000000):
            ok, _ = feishu_notify.send_feishu(self.cfg, "微信读书：测试")
        self.assertTrue(ok)
        self.assertEqual(self.requests, [{
            "msg_type": "text", "content": {"text": "微信读书：测试"},
            "timestamp": "1700000000", "sign": "8oT2n3SMKFfEnDoiwer8BUM/SjKLwe9SqoEIHlhDTKo=",
        }])

    def test_application_errors_http_errors_and_bad_responses_fail_safely(self):
        for status, reply in [(200, {"code": 19024, "msg": self.cfg["webhook_url"]}),
                              (503, {}), (200, b"not-json"), (200, []), (200, {})]:
            with self.subTest(status=status, reply=reply):
                self.status, self.reply = status, reply
                ok, reason = feishu_notify.send_feishu(self.cfg, "微信读书")
                self.assertFalse(ok)
                self.assertNotIn("secret-token", reason)

    def test_legacy_success_response_is_accepted(self):
        self.reply = {"StatusCode": 0, "StatusMessage": "success"}
        self.assertTrue(feishu_notify.send_feishu(self.cfg, "微信读书")[0])

    def test_real_login_event_not_cookie_file_age_controls_alerts(self):
        (self.data_dir / "cookies.json").write_text("[]")
        notifier = feishu_notify.LoginNotifier(self.data_dir)
        notifier.observe("Cookies loaded successfully.\n")
        notifier.observe("Waiting for login...\n")
        self.assertEqual(self.requests, [])
        notifier.observe("Login link found. Clicking...\n")
        self.assertEqual(len(self.requests), 1)
        self.assertIn(self.cfg["panel_url"], self.requests[0]["content"]["text"])

    def test_dedup_survives_runs_and_resets_after_successful_login(self):
        feishu_notify.LoginNotifier(self.data_dir).observe("Login link found. Clicking...")
        second = feishu_notify.LoginNotifier(self.data_dir)
        for line in ["QR code saved, datetime: now", "Failed to login.", "Login link found. Clicking..."]:
            second.observe(line)
        self.assertEqual(len(self.requests), 1)
        second.observe("Login completed.")
        third = feishu_notify.LoginNotifier(self.data_dir)
        third.observe("Login link found. Clicking...")
        self.assertEqual(len(self.requests), 2)

    def test_failure_retries_later_without_marking_incident_delivered(self):
        notifier = feishu_notify.LoginNotifier(self.data_dir)
        with patch("feishu_notify.send_feishu", side_effect=[(False, "failed"), (True, "sent")]) as send:
            with patch("feishu_notify.time.monotonic", side_effect=[10, 11, 71]):
                notifier.observe("Login link found. Clicking...")
                self.assertFalse(feishu_notify.read_json(notifier.state_path).get("notified"))
                notifier.observe("QR code saved, datetime: now")
                notifier.observe("Failed to login.")
            self.assertEqual(send.call_count, 2)
        self.assertTrue(feishu_notify.read_json(notifier.state_path)["notified"])

    def test_no_configuration_makes_no_request(self):
        (self.data_dir / "notification_config.json").unlink()
        feishu_notify.LoginNotifier(self.data_dir).observe("Login link found. Clicking...")
        self.assertEqual(self.requests, [])

    def test_environment_overrides_saved_configuration(self):
        with patch.dict(os.environ, {"WEBHOOK_URL": "https://override.example/hook",
                                     "WEBHOOK_SECRET": "env-secret"}):
            cfg = feishu_notify.load_webhook_config(self.data_dir)
        self.assertEqual(cfg["webhook_url"], "https://override.example/hook")
        self.assertEqual(cfg["webhook_secret"], "env-secret")
        self.assertEqual(cfg["panel_url"], self.cfg["panel_url"])

    def test_reader_logs_and_exit_code_survive_notification_exception(self):
        original_popen = subprocess.Popen
        requested = []

        def fake_cli(command, **kwargs):
            requested.append(command)
            return original_popen([sys.executable, "-c",
                                   "import sys; print('Login link found. Clicking...'); print('reader continued'); sys.exit(7)"],
                                  **kwargs)

        output = io.StringIO()
        with patch.dict(os.environ, {"WEREAD_DATA_DIR": str(self.data_dir)}):
            with patch("feishu_notify.subprocess.Popen", side_effect=fake_cli):
                with patch.object(feishu_notify.LoginNotifier, "observe", side_effect=OSError("secret-token")):
                    with contextlib.redirect_stdout(output):
                        code = feishu_notify.run_reader()
        self.assertEqual(requested, [["weread-selenium-cli", "run"]])
        self.assertEqual(code, 7)
        self.assertIn("reader continued", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
