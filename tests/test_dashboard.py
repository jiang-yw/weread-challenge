import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as web
from dashboard_helpers import log_entries, reading_settings, tail_lines
from feishu_notify import load_webhook_config, write_json
from notification_delivery import send_email
from notification_settings import ENV_MAP, reader_environment


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("SCRATCH_ROOT"))
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        env = patch.dict(os.environ, {key: "" for key in [*ENV_MAP.values(), "ENABLE_EMAIL"]})
        env.start()
        self.addCleanup(env.stop)

    def test_saved_bark_email_settings_reach_the_actual_reader_environment(self):
        write_json(self.path / "notification_config.json", {
            "bark": {"bark_key": "device-secret", "bark_url": "https://bark.example", "enabled": True},
            "email": {"email_user": "sender@example.test", "email_pass": "smtp-secret", "email_to": "to@example.test",
                      "email_smtp": "smtp.example.test", "email_port": "587", "enabled": True}})
        env = reader_environment(self.path)
        self.assertEqual(env["BARK_KEY"], "device-secret")
        self.assertEqual(env["BARK_SERVER"], "https://bark.example")
        self.assertEqual(env["ENABLE_EMAIL"], "true")
        self.assertEqual(env["EMAIL_PASS"], "smtp-secret")
        self.assertEqual(env["EMAIL_PORT"], "587")

    def test_dashboard_switches_disable_environment_configured_channels(self):
        write_json(self.path / "notification_config.json", {"bark": {"enabled": False},
                   "email": {"enabled": False}, "webhook": {"enabled": False}})
        with patch.dict(os.environ, {"BARK_KEY": "env-key", "ENABLE_EMAIL": "true", "WEBHOOK_URL": "https://example.test/hook"}):
            env = reader_environment(self.path)
            self.assertEqual(env["BARK_KEY"], "")
            self.assertEqual(env["ENABLE_EMAIL"], "false")
            self.assertEqual(load_webhook_config(self.path)["webhook_url"], "")

    def test_partial_email_configuration_does_not_enable_the_reader(self):
        write_json(self.path / "notification_config.json", {"email": {"enabled": True, "email_user": "incomplete"}})
        self.assertEqual(reader_environment(self.path)["ENABLE_EMAIL"], "false")

    def test_log_summary_filters_noise_merges_repeats_and_hides_links(self):
        lines = ["Pressed down arrow key."] * 4 + [
            "[INFO][2026-10-21 12:00:00.000]: Reading minute: 67",
            "[INFO][2026-10-21 12:00:01.000]: Reading minute: 67",
            "[INFO][2026-10-21 12:00:02.000]: Reading completed.",
            "[INFO][2026-10-21 12:00:03.000]: Bark推送密钥未配置",
            "[feishu] Webhook 请求失败：请检查网络",
            "登录链接: https://example.test/secret-token",
            'Logging to WeRead server: {"error":"", "wr_rt":"private-cookie-token"}',
        ]
        entries = log_entries(lines)
        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0]["count"], 2)
        self.assertIn("第 67 分钟", entries[0]["text"])
        self.assertEqual(entries[1]["level"], "success")
        self.assertEqual(entries[2]["level"], "error")
        self.assertNotIn("secret-token", str(entries))
        self.assertNotIn("private-cookie-token", str(entries))

    def test_large_logs_only_read_the_tail_and_keep_last_events(self):
        log = self.path / "app.log"
        log.write_text("old entry\n" * 10000 + "Reading completed.\n")
        lines = tail_lines(log, 10, max_bytes=256)
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[-1], "Reading completed.")

    def test_log_api_supports_search_and_level_without_reading_other_logs(self):
        log = self.path / "app.log"
        log.write_text("[feishu] 通知发送失败\nReading completed.\n")
        client = web.app.test_client()
        with client.session_transaction() as session:
            session["authed"] = True
        with patch.object(web, "APP_LOG", log):
            res = client.get("/logs/clean?level=error&q=通知")
            self.assertEqual(len(res.json["entries"]), 1)
            self.assertEqual(client.get("/logs?n=invalid").status_code, 400)
            self.assertIn("Reading completed.", client.get("/logs").get_data(as_text=True))

    def test_stale_qr_is_not_active_and_fresh_login_ignores_cookie_age_estimate(self):
        cookie = self.path / "cookies.json"
        cookie.write_text("[]")
        qr = self.path / "login.png"
        qr.write_bytes(b"fake-qr")
        os.utime(cookie, (100, 100))
        os.utime(qr, (200, 200))
        with patch.object(web, "COOKIES_JSON", cookie), patch.object(web, "LOGIN_PNG", qr):
            with patch.object(web, "_pid_alive", return_value=123), patch.object(web, "_last_run", return_value={}):
                self.assertFalse(web._reading_state()["login_qr"]["active"])
                os.utime(cookie, None)
                os.utime(qr, None)
                # Make the QR newer than a recently saved (but invalid) cookie.
                recent = cookie.stat().st_mtime - 1
                os.utime(cookie, (recent, recent))
                self.assertEqual(web._reading_state()["phase"], "waiting_login")
            with patch.object(web, "_pid_alive", return_value=None):
                self.assertFalse(web._reading_state()["login_qr"]["active"])

    def test_reading_settings_explain_selection_and_units(self):
        with patch.dict(os.environ, {"WEREAD_DURATION": "68", "WEREAD_SELECTION": "2"}):
            primary = {row["key"]: row for row in reading_settings()["primary"]}
        self.assertEqual(primary["WEREAD_DURATION"]["value"], "68 分钟")
        self.assertEqual(primary["WEREAD_SELECTION"]["value"], "书架第 2 本")

    def test_test_email_uses_ssl_or_starttls_and_reports_rejection(self):
        cfg = {"email_smtp": "smtp.example.test", "email_user": "sender@example.test", "email_pass": "secret",
               "email_to": "receiver@example.test", "email_from": "", "email_port": "465"}
        for port, target in [("465", "notification_delivery.smtplib.SMTP_SSL"), ("587", "notification_delivery.smtplib.SMTP")]:
            cfg["email_port"] = port
            with patch(target) as constructor:
                smtp = constructor.return_value.__enter__.return_value
                smtp.send_message.return_value = {}
                self.assertTrue(send_email(cfg, "test")[0])
                smtp.login.assert_called_once_with("sender@example.test", "secret")
                self.assertEqual(smtp.starttls.called, port != "465")
                smtp.send_message.return_value = {"receiver@example.test": (550, b"rejected")}
                self.assertFalse(send_email(cfg, "test")[0])


if __name__ == "__main__":
    unittest.main()
