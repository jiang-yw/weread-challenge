import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as web
from feishu_notify import read_json, write_json


class NotificationApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("SCRATCH_ROOT"))
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.config_path = self.data_dir / "notification_config.json"
        for key, value in [("DATA_DIR", self.data_dir), ("NOTIF_CONFIG", self.config_path)]:
            p = patch.object(web, key, value)
            p.start()
            self.addCleanup(p.stop)
        env = patch.dict(os.environ, {"WEBHOOK_URL": "", "WEBHOOK_SECRET": "", "WEREAD_PANEL_URL": ""})
        env.start()
        self.addCleanup(env.stop)
        self.client = web.app.test_client()
        with self.client.session_transaction() as session:
            session["authed"] = True

    def test_configuration_and_test_endpoint_require_login(self):
        unauthenticated = web.app.test_client()
        for method, path in [("get", "/api/notification"), ("post", "/api/notification"),
                             ("post", "/api/notification/test")]:
            with self.subTest(path=path):
                res = getattr(unauthenticated, method)(path, headers={"Accept": "application/json"})
                self.assertEqual(res.status_code, 401)

    def test_webhook_save_masks_credentials_and_preserves_other_channels(self):
        write_json(self.config_path, {"bark": {"bark_key": "existing-key"}})
        cfg = {"webhook_url": "https://example.test/secret-hook", "webhook_secret": "sign-secret",
               "panel_url": "https://panel.example"}
        self.assertTrue(self.client.post("/api/notification", json={"webhook": cfg}).json["ok"])
        saved = read_json(self.config_path)
        self.assertEqual(saved["bark"]["bark_key"], "existing-key")
        self.assertEqual(saved["webhook"], cfg)
        self.assertEqual(self.config_path.stat().st_mode & 0o777, 0o600)
        res = self.client.get("/api/notification")
        self.assertEqual(res.json["config"]["webhook"]["webhook_url"], "***set***")
        self.assertNotIn("sign-secret", res.get_data(as_text=True))
        masked = res.json["config"]["webhook"]
        self.client.post("/api/notification", json={"webhook": masked})
        self.assertEqual(read_json(self.config_path)["webhook"], cfg)
        self.assertTrue(next(c for c in web._notification_status()["channels"] if c["name"] == "Webhook")["configured"])

    def test_test_notification_uses_saved_config_and_reports_failure(self):
        cfg = {"webhook_url": "https://example.test/secret-hook", "webhook_secret": "", "panel_url": ""}
        write_json(self.config_path, {"webhook": cfg})
        with patch("app.send_feishu", return_value=(False, "飞书拒绝通知（code=19024）")) as send:
            res = self.client.post("/api/notification/test")
        self.assertEqual(res.status_code, 502)
        self.assertFalse(res.json["ok"])
        self.assertEqual(send.call_args.args[0], cfg)
        self.assertIn("微信读书", send.call_args.args[1])
        self.assertFalse((self.data_dir / "feishu_login_state.json").exists())

    def test_invalid_configuration_is_rejected_without_erasing_saved_values(self):
        write_json(self.config_path, {"bark": {"bark_key": "keep-me"}})
        for payload in [[1], {"webhook": "invalid"}]:
            self.assertEqual(self.client.post("/api/notification", json=payload).status_code, 400)
        self.assertEqual(read_json(self.config_path)["bark"]["bark_key"], "keep-me")

    def test_saved_webhook_can_be_disabled_with_empty_url(self):
        write_json(self.config_path, {"webhook": {"webhook_url": "https://example.test/hook"}})
        self.client.post("/api/notification", json={"webhook": {"webhook_url": ""}})
        self.assertFalse(next(c for c in web._notification_status()["channels"] if c["name"] == "Webhook")["configured"])


if __name__ == "__main__":
    unittest.main()
