"""Test delivery for the reader's Bark and email channels."""
import json
import smtplib
import ssl
from email.message import EmailMessage
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


def send_bark(cfg: dict, text: str) -> tuple[bool, str]:
    if not cfg.get("bark_key"):
        return False, "请先配置 Bark 设备密钥"
    try:
        url = cfg["bark_url"].rstrip("/") + "/" + cfg["bark_key"]
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            return False, "Bark 服务器须为 HTTP 或 HTTPS URL"
        req = Request(url, data=json.dumps({"title": "微信读书", "body": text, "group": "WeRead-Challenge"}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read(65536))
        return (True, "Bark 测试通知已发送") if isinstance(data, dict) and data.get("code") == 200 else (False, "Bark 拒绝通知，请检查设备密钥")
    except HTTPError as exc:
        return False, f"Bark 请求失败（HTTP {exc.code}）"
    except (OSError, URLError, ValueError, HTTPException):
        return False, "Bark 请求失败，请检查网络、地址和设备密钥"


def send_email(cfg: dict, text: str) -> tuple[bool, str]:
    if not all(cfg.get(key) for key in ("email_smtp", "email_user", "email_pass", "email_to")):
        return False, "请先补全邮件服务器、账号、授权码和收件人"
    try:
        port = int(cfg["email_port"])
        message = EmailMessage()
        message["Subject"] = "微信读书：通知测试"
        message["From"] = cfg.get("email_from") or cfg["email_user"]
        message["To"] = cfg["email_to"]
        message.set_content(text)
        context = ssl.create_default_context()
        client = smtplib.SMTP_SSL(cfg["email_smtp"], port, timeout=10, context=context) if port == 465 else smtplib.SMTP(cfg["email_smtp"], port, timeout=10)
        with client as smtp:
            if port != 465:
                smtp.starttls(context=context)
            smtp.login(cfg["email_user"], cfg["email_pass"])
            refused = smtp.send_message(message)
        return (False, "部分收件人未接受邮件，请检查地址") if refused else (True, "测试邮件已提交，请检查收件箱")
    except (OSError, ValueError, smtplib.SMTPException):
        return False, "邮件发送失败，请检查 SMTP 地址、端口、账号和授权码"
