"""Bounded log summaries and human-readable reading configuration."""
from __future__ import annotations

import os
from pathlib import Path
import re


def tail_lines(path: Path, limit: int, max_bytes: int = 256_000) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            offset = max(0, f.tell() - max_bytes)
            f.seek(offset)
            if offset:
                f.readline()  # Discard a potentially partial first record.
            return f.read(max_bytes).decode("utf-8", errors="replace").splitlines()[-limit:]
    except FileNotFoundError:
        return []


def log_entries(lines: list[str]) -> list[dict]:
    entries = []
    noise = re.compile(r"Pressed .* key\.|Screenshot size|Bark推送密钥未配置|pruned screenshots|Logging to WeRead server:", re.I)
    meaningful = re.compile(r"login|cookie|reading|error|fail|warn|success|complet|start_reading|"
                           r"\[feishu\]|登录|通知|失败|异常|二维码|阅读", re.I)
    translations = [(r"Reading minute:\s*(\d+)", lambda m: f"正在阅读 · 第 {m[1]} 分钟"),
                    (r"Reading completed\.", "本次阅读已完成"),
                    (r"Reading started\.\.\.", "开始阅读"),
                    (r"Cookies saved successfully\.", "登录信息已更新"),
                    (r"Cookies loaded successfully\.", "已加载保存的登录信息"),
                    (r"Login completed\.|Successfully logged in\.", "微信读书登录成功"),
                    (r"Login link found\. Clicking\.\.\.", "需要重新扫码登录"),
                    (r"Waiting for login\.\.\.", "等待扫码登录"),
                    (r"Failed to login\.", "扫码登录失败，请重新尝试")]
    for line in lines:
        line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if not line or noise.search(line) or not meaningful.search(line):
            continue
        lowered = line.lower()
        level = "error" if re.search(r"error|fail|失败|异常|拒绝|✗", lowered) else (
            "warning" if re.search(r"warn|login link found|qr code saved|需要重新|未登录", lowered) else (
                "success" if re.search(r"success|complet|完成|已发送|✓", lowered) else "info"))
        stamp = re.search(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?", line)
        text = re.sub(r"^(?:\[[^\]]*\]\s*)+:?\s*", "", line)
        for pattern, replacement in translations:
            text = re.sub(pattern, replacement, text)
        text = re.sub(r"https?://[^\s\"'<>]+", "[链接已隐藏]", text)
        for key in ("BARK_KEY", "EMAIL_PASS", "WEBHOOK_SECRET", "PUSHPLUS_TOKEN"):
            secret = os.environ.get(key)
            if secret:
                text = text.replace(secret, "***")
        entry = {"text": text, "level": level, "timestamp": stamp[0] if stamp else "", "count": 1}
        if entries and entries[-1]["text"] == text and entries[-1]["level"] == level:
            entries[-1]["count"] += 1
            entries[-1]["timestamp"] = entry["timestamp"]
        else:
            entries.append(entry)
    return entries


def reading_settings() -> dict:
    env = os.environ
    selection = env.get("WEREAD_SELECTION", "2")
    book = {"-1": "指定书籍链接", "0": "随机选择前四本"}.get(selection, f"书架第 {selection} 本")
    def item(key, label, value, description):
        return {"key": key, "label": label, "value": value, "description": description}
    return {"primary": [
        item("WEREAD_DURATION", "每次阅读时长", env.get("WEREAD_DURATION", "68") + " 分钟", "每次任务计划阅读的时间。"),
        item("READING_INTERVAL_HOURS", "自动运行间隔", env.get("READING_INTERVAL_HOURS", "12") + " 小时", "服务按这个间隔检查并启动阅读任务。"),
        item("WEREAD_SPEED", "翻页速度", {"slow": "慢速", "normal": "标准", "fast": "快速"}.get(env.get("WEREAD_SPEED", "slow"), env.get("WEREAD_SPEED")), "控制自动滚动和翻页的节奏。"),
        item("WEREAD_SELECTION", "书籍选择", book, "书架书籍不足或无法选择时，尝试默认书籍链接。"),
    ], "advanced": [
        item("DEFAULT_BOOK_URL", "默认书籍链接", env.get("DEFAULT_BOOK_URL") or "使用阅读程序内置书籍", "选择指定链接模式，或无法从书架选书时使用。"),
        item("WEREAD_SCREENSHOT", "阅读截图", "开启" if env.get("WEREAD_SCREENSHOT", "true").lower() == "true" else "关闭", "开启后，阅读程序按分钟保存截图。"),
        item("WEREAD_AGREE_TERMS", "上游运行统计", "开启" if env.get("WEREAD_AGREE_TERMS", "true").lower() == "true" else "关闭", "开启时向上游项目的统计服务提交运行与微信读书用户信息。"),
        item("WEREAD_BROWSER", "浏览器", env.get("WEREAD_BROWSER", "chrome"), "自动阅读使用的浏览器。"),
        item("WEREAD_DATA_DIR", "数据保存位置", env.get("WEREAD_DATA_DIR", "/data/.weread"), "容器内保存登录信息、截图和日志的位置。"),
    ]}
