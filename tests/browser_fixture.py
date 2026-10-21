"""An isolated UI fixture: no scheduler, reader, real credentials or delivery."""
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as web
from feishu_notify import write_json

web.WEB_PASSWORD = "browser-test"
web.app.config["SESSION_COOKIE_SECURE"] = False  # Fixture is served over loopback HTTP.
now = datetime.now(timezone.utc)
write_json(web.STATE_FILE, {"status": "completed", "started_at": (now - timedelta(hours=2)).isoformat(),
                          "ended_at": (now - timedelta(hours=1)).isoformat(), "exit_code": 0})
web.COOKIES_JSON.write_text("[]")
web.LOGIN_PNG.write_bytes(b"expired fixture QR")
os.utime(web.LOGIN_PNG, (time.time() - 86400, time.time() - 86400))
web.APP_LOG.write_text("\n".join([
    "[INFO][2026-10-21 12:00:00.000]: Reading started...",
    *[f"[INFO][2026-10-21 12:{n:02}:00.000]: Reading minute: {n}" for n in range(1, 40)],
    "Pressed down arrow key.", "Pressed down arrow key.",
    "[feishu] 通知请求失败：请检查机器人配置",
    "[INFO][2026-10-21 13:08:00.000]: Reading completed.",
    "[INFO][2026-10-21 13:08:00.001]: Cookies saved successfully.",
]), encoding="utf-8")
web.send_feishu = lambda *args: (True, "飞书测试通知已发送")
web.send_bark = lambda *args: (True, "Bark 测试通知已发送")
web.send_email = lambda *args: (True, "测试邮件已提交")
web._spawn_reader = lambda *args: 12345
web.app.run(host="127.0.0.1", port=7860, use_reloader=False)
