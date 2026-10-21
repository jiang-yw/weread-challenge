#!/usr/bin/env python3
"""Relay reader output and notify Feishu when a WeRead login is required."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from notification_settings import load_config, reader_environment

WEBHOOK_FIELDS = {
    "webhook_url": "WEBHOOK_URL",
    "webhook_secret": "WEBHOOK_SECRET",
    "panel_url": "WEREAD_PANEL_URL",
}


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    """Replace configuration/state atomically; keep credentials owner-readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def load_webhook_config(data_dir: Path) -> dict:
    settings = load_config(data_dir / "notification_config.json")["webhook"]
    cfg = {field: settings[field] for field in WEBHOOK_FIELDS}
    if not settings["enabled"]:
        cfg["webhook_url"] = ""
    return cfg


def send_feishu(cfg: dict, text: str) -> tuple[bool, str]:
    """Check Feishu's application response as well as the HTTP status."""
    url = cfg.get("webhook_url", "")
    if not url:
        return False, "未配置飞书 Webhook"
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False, "Webhook 地址须为 HTTP 或 HTTPS URL"
        payload = {"msg_type": "text", "content": {"text": text}}
        secret = cfg.get("webhook_secret", "")
        if secret:
            timestamp = str(int(time.time()))
            signature = hmac.new(f"{timestamp}\n{secret}".encode("utf-8"),
                                 digestmod=hashlib.sha256).digest()
            payload.update(timestamp=timestamp, sign=base64.b64encode(signature).decode("ascii"))
        req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read(65536))
        if not isinstance(result, dict):
            return False, "飞书返回了无效响应"
        code = result.get("code", result.get("StatusCode"))
        if type(code) is not int or code != 0:
            # Do not print response text, URLs or credentials into reader logs.
            label = str(code) if type(code) is int else "unknown"
            return False, f"飞书拒绝通知（code={label}）"
        return True, "飞书通知已发送"
    except HTTPError as exc:
        return False, f"Webhook HTTP 错误（{exc.code}）"
    except (OSError, URLError, ValueError, HTTPException):
        return False, "Webhook 请求失败：请检查网络、地址和机器人配置"


def login_message(cfg: dict) -> str:
    text = ("微信读书：需要重新登录\n"
            "阅读任务检测到登录失效或尚未登录，请打开管理面板，使用微信读书重新扫码。")
    if cfg.get("panel_url"):
        text += "\n管理面板：" + cfg["panel_url"]
    return text


class LoginNotifier:
    """One successful notification per login incident, persisted across runs."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.state_path = data_dir / "feishu_login_state.json"
        self.state = read_json(self.state_path)
        self.last_attempt = 0.0

    def observe(self, line: str) -> None:
        # These events come from the pinned weread-selenium-cli 0.18.0.
        if "Login completed." in line or "Successfully logged in." in line:
            if self.state.get("notified"):
                write_json(self.state_path, {})
                self.state = {}
            return
        if not any(event in line for event in (
            "Login link found. Clicking...", "QR code saved,", "Failed to login.",
        )):
            return
        if self.state.get("notified"):
            return
        cfg = load_webhook_config(self.data_dir)
        if not cfg["webhook_url"]:
            return
        # Failed requests may retry on a later login/QR event, without flooding.
        now = time.monotonic()
        if self.last_attempt and now - self.last_attempt < 60:
            return
        self.last_attempt = now
        ok, reason = send_feishu(cfg, login_message(cfg))
        print(f"[feishu] {reason}", flush=True)
        if ok:
            self.state = {"notified": True, "notified_at": int(time.time())}
            write_json(self.state_path, self.state)


def run_reader() -> int:
    """Preserve reader logs/exit status; notification errors cannot stop reading."""
    data_dir = Path(os.environ.get("WEREAD_DATA_DIR", "/data/.weread"))
    notifier = LoginNotifier(data_dir)
    with subprocess.Popen(["weread-selenium-cli", "run"], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                          errors="replace", bufsize=1, env=reader_environment(data_dir)) as proc:
        for line in proc.stdout:
            print(line, end="", flush=True)
            try:
                notifier.observe(line)
            except Exception:
                # Avoid leaking credentials through exception messages.
                print("[feishu] 通知处理失败，阅读任务继续运行", flush=True)
        return proc.wait()


if __name__ == "__main__":
    sys.exit(run_reader())
