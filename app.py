#!/usr/bin/env python3
"""Flask Web UI for weread-selenium-cli on HuggingFace Spaces.

Features:
  - Password-protected Web UI (default: linuxdo123)
  - Light/dark dashboard with auto-refresh
  - QR code display + manual restart button
  - Manual trigger reading / restart reading
  - Background scheduler (every N hours)

Endpoints:
  GET  /          dashboard (requires login)
  GET  /status    JSON status (requires login)
  GET  /login.png QR code image (requires login)
  POST /start     trigger reading (requires login)
  POST /restart   kill + restart reading (requires login)
  GET  /logs      tail app.log (requires login)
  GET  /healthz   health check (no auth, for external ping)
  GET  /login     login page
  POST /login     authenticate
  GET  /logout    clear session
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Flask, Response, abort, jsonify, redirect,
    render_template, request, send_file, session,
)
from feishu_notify import WEBHOOK_FIELDS, send_feishu, write_json
from dashboard_helpers import log_entries, reading_settings, tail_lines
from notification_delivery import send_bark, send_email
from notification_settings import ENV_MAP, SCHEMA, SECRET_FIELDS, channel_status, load_config

# ─── Configuration ─────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("WEREAD_DATA_DIR", "/data/.weread"))
PORT = int(os.environ.get("PORT", "7860"))
READING_INTERVAL_HOURS = float(os.environ.get("READING_INTERVAL_HOURS", "12"))
START_SCRIPT = Path(os.environ.get("START_SCRIPT", "/app/start_reading.sh"))
COOKIE_TTL_DAYS = 30
LOGIN_QR_FRESH_MINUTES = 5
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "linuxdo123")

DATA_DIR.mkdir(parents=True, exist_ok=True)

LOGIN_PNG = DATA_DIR / "login.png"
COOKIES_JSON = DATA_DIR / "cookies.json"
PID_FILE = DATA_DIR / "run.pid"
STATE_FILE = DATA_DIR / "last_run.json"
APP_LOG = DATA_DIR / "app.log"
NOTIF_CONFIG = DATA_DIR / "notification_config.json"

PUBLIC_ENV_KEYS = (
    "WEREAD_BROWSER", "WEREAD_DATA_DIR", "WEREAD_DURATION", "WEREAD_SPEED",
    "WEREAD_SELECTION", "WEREAD_SCREENSHOT", "WEREAD_AGREE_TERMS",
    "DEFAULT_BOOK_URL", "READING_INTERVAL_HOURS",
)
SECRET_ENV_KEYS = (
    "BARK_KEY", "EMAIL_PASS", "EMAIL_USER", "EMAIL_TO", "EMAIL_FROM", "EMAIL_SMTP",
    "WEBHOOK_URL", "WEBHOOK_SECRET",
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "weread-challenge-secret-key-2024")
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True


# ─── Auth ──────────────────────────────────────────────────────────────────────
_NO_AUTH_PATHS = {"/healthz", "/login"}


@app.before_request
def _check_auth():
    if request.path in _NO_AUTH_PATHS or request.endpoint == "static":
        return None
    if session.get("authed"):
        return None
    if request.accept_mimetypes.accept_html and not request.is_json:
        return redirect("/login")
    return jsonify({"ok": False, "reason": "unauthorized"}), 401


@app.route("/login", methods=["GET", "POST"])
def route_login():
    if request.method == "GET":
        return render_template("login.html")
    pwd = (request.form.get("password") or "").strip()
    if pwd == WEB_PASSWORD:
        session["authed"] = True
        return redirect("/")
    return render_template("login.html", error=True)


@app.route("/logout")
def route_logout():
    session.clear()
    return redirect("/login")


# ─── Status helpers ────────────────────────────────────────────────────────────
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _file_age_seconds(p: Path) -> float | None:
    try:
        return (_utcnow().timestamp() - p.stat().st_mtime)
    except FileNotFoundError:
        return None


def _pid_alive() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, PermissionError):
        return None


def _last_run() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _cookies_status() -> tuple[str, float | None]:
    age = _file_age_seconds(COOKIES_JSON)
    if age is None:
        return ("missing", None)
    age_days = age / 86400.0
    if age_days > COOKIE_TTL_DAYS:
        return ("expired", age_days)
    return ("valid", age_days)


def _qr_status() -> tuple[bool, float | None]:
    age = _file_age_seconds(LOGIN_PNG)
    if age is None:
        return (False, None)
    return (age <= LOGIN_QR_FRESH_MINUTES * 60, age)


def _is_paused(pid: int | None) -> bool:
    """Check if a process is in stopped (paused) state."""
    if pid is None:
        return False
    try:
        with open(f"/proc/{pid}/status", "r") as f:
            for line in f:
                if line.startswith("State:"):
                    return "stopped" in line.lower()
    except (FileNotFoundError, PermissionError):
        return False
    return False


def _reading_state() -> dict:
    last = _last_run()
    pid = _pid_alive()
    cookies, cookies_age_days = _cookies_status()
    qr_fresh, qr_age = _qr_status()
    qr_active = pid is not None and qr_fresh and (cookies_age_days is None or qr_age < cookies_age_days * 86400)

    if pid is not None:
        if qr_active:
            phase = "waiting_login"
        else:
            phase = "running"
    else:
        if qr_active:
            phase = "waiting_login"
        elif last.get("status") == "failed":
            phase = "failed"
        else:
            phase = "idle"

    started_at = last.get("started_at")
    duration_min = float(last.get("duration_minutes", 68))
    eta_seconds: float | None = None
    if phase == "running" and started_at:
        try:
            t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            elapsed = (_utcnow() - t0).total_seconds()
            eta_seconds = max(0.0, duration_min * 60 - elapsed)
        except ValueError:
            pass

    return {
        "phase": phase,
        "pid": pid,
        "cookies": {"status": cookies, "age_days": cookies_age_days},
        "login_qr": {"present": LOGIN_PNG.exists(), "fresh": qr_fresh, "active": qr_active, "age_seconds": qr_age},
        "last_run": last,
        "eta_seconds": eta_seconds,
        "is_paused": _is_paused(pid),
        "now": _utcnow().isoformat(),
    }


def _public_env() -> dict:
    out = {k: os.environ.get(k, "") for k in PUBLIC_ENV_KEYS}
    for k in SECRET_ENV_KEYS:
        v = os.environ.get(k, "")
        out[k] = "***set***" if v else ""
    return out


def _notification_status() -> dict:
    channels = channel_status(_load_notif_config())
    return {"channels": channels, "any_configured": any(c["configured"] for c in channels)}


# ─── Background workers ───────────────────────────────────────────────────────
def _spawn_reader(trigger: str) -> int:
    proc = subprocess.Popen(
        [str(START_SCRIPT), trigger],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def _scheduler_loop() -> None:
    interval = max(60.0, READING_INTERVAL_HOURS * 3600)
    time.sleep(interval)
    while True:
        try:
            if _pid_alive() is None:
                _spawn_reader("scheduler")
        except Exception as exc:
            print(f"[scheduler] error: {exc}", flush=True)
        time.sleep(interval)


def _start_background_threads() -> None:
    threading.Thread(target=_scheduler_loop, name="reader-scheduler", daemon=True).start()


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/status")
def route_status() -> Response:
    return jsonify({"reading": _reading_state(), "env": _public_env(), "settings": reading_settings(),
                    "notifications": _notification_status()})


@app.route("/login.png")
def route_login_png() -> Response:
    if not LOGIN_PNG.exists():
        abort(404)
    resp = send_file(LOGIN_PNG, mimetype="image/png", max_age=0)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/start", methods=["POST"])
def route_start() -> Response:
    if _pid_alive() is not None:
        return jsonify({"ok": False, "reason": "already running"}), 409
    pid = _spawn_reader("manual")
    return jsonify({"ok": True, "spawned_pid": pid})


@app.route("/restart", methods=["POST"])
def route_restart() -> Response:
    try:
        pid = _pid_alive()
        _kill_reader(pid)
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        # Delete cookies + old QR so the new run generates a fresh login QR
        for f in [COOKIES_JSON, LOGIN_PNG]:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        # Give the killed process time to fully exit
        for _ in range(20):
            time.sleep(0.1)
            if _pid_alive() != pid:
                break
        new_pid = _spawn_reader("manual")
        return jsonify({"ok": True, "killed_pid": pid, "spawned_pid": new_pid})
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)}), 500


@app.route("/stop", methods=["POST"])
def route_stop() -> Response:
    """Pause: terminate the running reader without spawning a new one."""
    pid = _pid_alive()
    if pid is None:
        return jsonify({"ok": False, "reason": "not running"}), 409
    _kill_reader(pid)
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        last = _last_run() or {}
        last["status"] = "stopped"
        last["ended_at"] = _utcnow().isoformat()
        STATE_FILE.write_text(json.dumps(last, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return jsonify({"ok": True, "killed_pid": pid})


def _kill_reader(pid: int | None) -> None:
    """Terminate the reading process. Also cleans up lock file."""
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    # Delete the flock lockfile so next spawn isn't blocked
    LOCK_FILE = DATA_DIR / "run.lock"
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    # Wait in background thread so we don't block the Flask request
    def _wait_and_force():
        for _ in range(30):
            time.sleep(0.1)
            if _pid_alive() != pid:
                return
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    threading.Thread(target=_wait_and_force, daemon=True).start()


def _log_limit(default: int, maximum: int) -> int:
    try:
        return max(1, min(int(request.args.get("n", default)), maximum))
    except ValueError:
        abort(400)


@app.route("/logs")
def route_logs() -> Response:
    return Response("\n".join(tail_lines(APP_LOG, _log_limit(200, 5000))), mimetype="text/plain")


@app.route("/logs/clean")
def route_logs_clean() -> Response:
    n = _log_limit(80, 500)
    entries = log_entries(tail_lines(APP_LOG, 10000))
    level = request.args.get("level", "all")
    query = request.args.get("q", "").strip().lower()
    if level != "all":
        entries = [entry for entry in entries if entry["level"] == level]
    if query:
        entries = [entry for entry in entries if query in entry["text"].lower()]
    return jsonify({"entries": entries[-n:], "total": len(entries)})


# ─── Notification config ──────────────────────────────────────────────────────
NOTIF_SCHEMA = SCHEMA
_NOTIF_SECRET_FIELDS = SECRET_FIELDS


def _load_notif_config() -> dict:
    return load_config(NOTIF_CONFIG)


@app.route("/api/notification", methods=["GET"])
def route_notif_get() -> Response:
    """Return current notification config with secret fields masked."""
    cfg = _load_notif_config()
    masked: dict = {}
    for ch, fields in cfg.items():
        masked[ch] = {}
        for k, v in fields.items():
            if k in _NOTIF_SECRET_FIELDS:
                masked[ch][k] = "***set***" if v else ""
            else:
                masked[ch][k] = v
    locked = [field for field, key in ENV_MAP.items() if os.environ.get(key)]
    return jsonify({"ok": True, "config": masked, "schema": NOTIF_SCHEMA,
                    "locked_fields": locked, "channels": channel_status(cfg)})


@app.route("/api/notification", methods=["POST"])
def route_notif_save() -> Response:
    """Persist notification config; ``***set***`` keeps the existing secret value."""
    incoming = request.get_json(silent=True)
    if not isinstance(incoming, dict):
        return jsonify({"ok": False, "reason": "配置必须是 JSON 对象"}), 400
    existing: dict = {}
    if NOTIF_CONFIG.exists():
        try:
            existing = json.loads(NOTIF_CONFIG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    if not isinstance(existing, dict):
        existing = {}

    cleaned: dict = {}
    for ch, fields in NOTIF_SCHEMA.items():
        cleaned[ch] = {}
        sub_in = incoming.get(ch, {})
        if not isinstance(sub_in, dict):
            return jsonify({"ok": False, "reason": "渠道配置必须是 JSON 对象"}), 400
        sub_old = (existing.get(ch) or {}) if isinstance(existing.get(ch), dict) else {}
        for field in fields:
            if field == "enabled":
                if field in sub_in:
                    if not isinstance(sub_in[field], bool):
                        return jsonify({"ok": False, "reason": "启用开关必须为布尔值"}), 400
                    cleaned[ch][field] = sub_in[field]
                elif isinstance(sub_old.get(field), bool):
                    cleaned[ch][field] = sub_old[field]
                continue
            val = sub_in.get(field, sub_old.get(field, fields[field]))
            if not isinstance(val, str):
                val = str(val)
            val = val.strip()
            if val == "***set***" and field in _NOTIF_SECRET_FIELDS:
                val = sub_old.get(field, "") if isinstance(sub_old.get(field, ""), str) else ""
            if val and field in {"bark_url", "webhook_url", "panel_url"}:
                try:
                    parsed = urlsplit(val)
                    valid_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                    parsed.port
                except ValueError:
                    valid_url = False
                if not valid_url:
                    return jsonify({"ok": False, "reason": "服务器、Webhook 和面板地址须为有效的 HTTP 或 HTTPS URL"}), 400
            if field == "email_port" and val:
                if not val.isdecimal() or not 1 <= int(val) <= 65535:
                    return jsonify({"ok": False, "reason": "SMTP 端口须为 1 到 65535 的整数"}), 400
            cleaned[ch][field] = val

    try:
        write_json(NOTIF_CONFIG, cleaned)
    except OSError as exc:
        return jsonify({"ok": False, "reason": str(exc)}), 500

    return jsonify({"ok": True})


@app.route("/api/notification/test", methods=["POST"])
def route_notif_test() -> Response:
    incoming = request.get_json(silent=True)
    channel = incoming.get("channel", "webhook") if isinstance(incoming, dict) else "webhook"
    cfg = _load_notif_config()
    if channel == "webhook":
        fields = {field: cfg[channel][field] for field in WEBHOOK_FIELDS}
        ok, reason = send_feishu(fields, "微信读书：飞书通知测试\nWebhook 配置正常，可以接收重新登录提醒。")
    elif channel == "bark":
        ok, reason = send_bark(cfg[channel], "微信读书：Bark 通知测试")
    elif channel == "email":
        ok, reason = send_email(cfg[channel], "微信读书：邮件通知测试，配置正常。")
    else:
        return jsonify({"ok": False, "reason": "不支持的通知渠道"}), 400
    return jsonify({"ok": ok, "reason": reason}), (200 if ok else 502)



@app.route("/healthz")
def route_health() -> Response:
    return jsonify({"ok": True, "now": _utcnow().isoformat()})


@app.route("/")
def route_index() -> str:
    return render_template("index.html")


# ─── Main ─────────────────────────────────────────────────────────────────────
def _install_signal_handlers() -> None:
    def _shutdown(signum, _frame):
        print(f"[app] received signal {signum}, exiting", flush=True)
        os._exit(0)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):
            pass


if __name__ == "__main__":
    _install_signal_handlers()
    _start_background_threads()
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
