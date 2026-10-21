"""Shared notification settings for the dashboard and reader subprocess."""
from __future__ import annotations

import json
import os
from pathlib import Path

SCHEMA = {
    "bark": {"bark_key": "", "bark_url": "https://api.day.app", "enabled": False},
    "pushplus": {"pushplus_token": ""},
    "email": {"email_user": "", "email_pass": "", "email_to": "", "email_from": "",
              "email_smtp": "", "email_port": "465", "enabled": False},
    "webhook": {"webhook_url": "", "webhook_secret": "", "panel_url": "", "enabled": False},
}
ENV_MAP = {
    "bark_key": "BARK_KEY", "bark_url": "BARK_SERVER", "pushplus_token": "PUSHPLUS_TOKEN",
    "email_user": "EMAIL_USER", "email_pass": "EMAIL_PASS", "email_to": "EMAIL_TO",
    "email_from": "EMAIL_FROM", "email_smtp": "EMAIL_SMTP", "email_port": "EMAIL_PORT",
    "webhook_url": "WEBHOOK_URL", "webhook_secret": "WEBHOOK_SECRET", "panel_url": "WEREAD_PANEL_URL",
}
SECRET_FIELDS = {"bark_key", "pushplus_token", "email_pass", "webhook_url", "webhook_secret"}
REQUIRED = {"bark": ("bark_key",), "email": ("email_user", "email_pass", "email_to", "email_smtp"),
            "webhook": ("webhook_url",)}
CHANNEL_NAMES = {"bark": "Bark", "email": "邮件", "webhook": "飞书"}


def load_config(path: Path) -> dict:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    cfg = {channel: dict(fields) for channel, fields in SCHEMA.items()}
    for channel, fields in cfg.items():
        stored = saved.get(channel)
        stored = stored if isinstance(stored, dict) else {}
        for field in fields:
            if field == "enabled":
                continue
            val = os.environ.get(ENV_MAP[field]) or stored.get(field, fields[field])
            fields[field] = val.strip() if isinstance(val, str) and val != "***set***" else ""
        if channel in REQUIRED:
            default = all(fields.get(field) for field in REQUIRED[channel])
            if channel == "email" and os.environ.get("ENABLE_EMAIL"):
                default = os.environ["ENABLE_EMAIL"].lower() in {"true", "1", "yes"}
            fields["enabled"] = stored["enabled"] if isinstance(stored.get("enabled"), bool) else default
    return cfg


def channel_status(cfg: dict) -> list[dict]:
    result = []
    for channel, required in REQUIRED.items():
        fields = cfg[channel]
        configured = all(fields.get(field) for field in required)
        result.append({"id": channel, "name": "Webhook" if channel == "webhook" else CHANNEL_NAMES[channel],
                       "label": CHANNEL_NAMES[channel], "configured": configured,
                       "enabled": fields["enabled"], "active": fields["enabled"] and configured,
                       "has_settings": any(fields.get(field) for field in required),
                       "missing_fields": [field for field in required if not fields.get(field)]})
    return result


def reader_environment(data_dir: Path) -> dict:
    env = dict(os.environ)
    cfg = load_config(data_dir / "notification_config.json")
    for channel in ("bark", "email"):
        for field, value in cfg[channel].items():
            if field != "enabled":
                env[ENV_MAP[field]] = value
    if not cfg["bark"]["enabled"]:
        env["BARK_KEY"] = ""
    email_active = cfg["email"]["enabled"] and all(cfg["email"].get(field) for field in REQUIRED["email"])
    env["ENABLE_EMAIL"] = "true" if email_active else "false"
    return env
