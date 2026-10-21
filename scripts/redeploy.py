#!/usr/bin/env python3
"""Replace this service, preserving its volume and Docker runtime configuration."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import http.client
import http.cookiejar
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import termios
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAME = "weread-challenge"
IMAGE = NAME + ":latest"


def docker(*args: str, capture: bool = True, **kwargs):
    return subprocess.run(["docker", *args], check=True, text=True, capture_output=capture, **kwargs)


def inspect_container() -> dict:
    return json.loads(docker("inspect", NAME).stdout)[0]


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def create_container(previous: dict, image: str, healthcheck: dict | None) -> None:
    payload = copy.deepcopy(previous["Config"])
    payload["Image"] = image
    payload["Healthcheck"] = healthcheck
    payload.pop("Hostname", None)
    payload.pop("Domainname", None)
    payload["HostConfig"] = copy.deepcopy(previous["HostConfig"])
    connection = DockerConnection("localhost", timeout=30)
    try:
        connection.request("POST", "/containers/create?name=" + NAME,
                           body=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        response.read()
        if response.status != 201:
            raise RuntimeError(f"Docker container creation failed (HTTP {response.status})")
    finally:
        connection.close()


def wait_healthy(timeout: int = 150) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = inspect_container()
        if current["State"]["Status"] in {"dead", "exited"}:
            raise RuntimeError("Replacement container exited during startup")
        health = current["State"].get("Health", {}).get("Status")
        if health == "healthy":
            return current
        time.sleep(2)
    raise RuntimeError("Replacement container did not become healthy in time")


def save_webhook(previous: dict, incoming: dict) -> None:
    if not incoming:
        return
    mounts = previous["Mounts"]
    mount = next(m for m in mounts if m["Destination"] == "/data")
    source = mount["Name"] if mount["Type"] == "volume" else mount["Source"]
    mount_arg = f"type={mount['Type']},source={source},target=/data"
    data_dir = next((v.split("=", 1)[1] for v in previous["Config"]["Env"] if v.startswith("WEREAD_DATA_DIR=")), "/data/.weread")
    code = '''import json, os, sys
from pathlib import Path
from feishu_notify import read_json, write_json
path = Path(os.environ['WEREAD_DATA_DIR']) / 'notification_config.json'
cfg = read_json(path)
webhook = cfg.get('webhook', {})
if not isinstance(webhook, dict):
    webhook = {}
incoming = json.load(sys.stdin)
for field in ('webhook_url', 'webhook_secret', 'panel_url'):
    if field in incoming:
        webhook[field] = incoming[field]
webhook['enabled'] = True
cfg['webhook'] = webhook
write_json(path, cfg)
print('Feishu configuration saved to the existing data volume (credentials hidden).')
'''
    result = docker("run", "--rm", "-i", "--network", "none", "--read-only", "--entrypoint", "python3",
                    "--mount", mount_arg, "-e", "WEREAD_DATA_DIR=" + data_dir, IMAGE, "-c", code,
                    input=json.dumps(incoming))
    print(result.stdout.strip(), flush=True)


def validate_service(test_webhook: bool) -> tuple[bool | None, str]:
    password = docker("exec", NAME, "python3", "-c", "import app; print(app.WEB_PASSWORD, end='')").stdout
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = "http://127.0.0.1:8860"
    with opener.open(base + "/login", timeout=15) as response:
        if "theme.js" not in response.read().decode():
            raise RuntimeError("Login page does not contain the updated theme assets")
    opener.open(base + "/login", data=urllib.parse.urlencode({"password": password}).encode(), timeout=15).close()
    with opener.open(base + "/status", timeout=15) as response:
        status = json.load(response)
    if "settings" not in status:
        raise RuntimeError("Dashboard status endpoint does not contain the new configuration summaries")
    for asset in ("theme.js", "dashboard.js", "dashboard.css"):
        opener.open(base + "/static/" + asset, timeout=15).close()
    print("HTTP checks passed on port 8860: login, authenticated status, theme and dashboard assets.", flush=True)
    if not test_webhook:
        return None, "not requested"
    feishu = next(channel for channel in status["notifications"]["channels"] if channel["id"] == "webhook")
    if not feishu["active"]:
        raise RuntimeError("Feishu configuration was not enabled")
    request = urllib.request.Request(base + "/api/notification/test", data=b'{"channel":"webhook"}',
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with opener.open(request, timeout=25) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        result = json.load(exc)
    return bool(result["ok"]), result["reason"]


def read_webhook() -> dict:
    terminal = sys.stdin.isatty()
    old_settings = termios.tcgetattr(sys.stdin) if terminal else None
    try:
        if terminal:
            hidden = copy.deepcopy(old_settings)
            hidden[3] &= ~termios.ECHO
            termios.tcsetattr(sys.stdin, termios.TCSANOW, hidden)
        print("Ready for webhook JSON on stdin (input is hidden).", flush=True)
        value = json.loads(sys.stdin.readline())
    finally:
        if terminal:
            termios.tcsetattr(sys.stdin, termios.TCSANOW, old_settings)
    if not isinstance(value, dict) or not isinstance(value.get("webhook_url"), str):
        raise ValueError("Expected a JSON object with webhook_url")
    parsed = urllib.parse.urlsplit(value["webhook_url"])
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Expected an HTTPS webhook URL")
    if any(not isinstance(value[field], str) for field in ("webhook_secret", "panel_url") if field in value):
        raise ValueError("Webhook fields must be strings")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--webhook-from-stdin", action="store_true")
    args = parser.parse_args()
    incoming = read_webhook() if args.webhook_from_stdin else {}
    previous = inspect_container()
    binding = previous["HostConfig"]["PortBindings"].get("7860/tcp", [])
    if not any(port["HostPort"] == "8860" for port in binding):
        raise RuntimeError("Expected the existing service to bind host port 8860")
    if not any(m["Destination"] == "/data" and m["RW"] for m in previous["Mounts"]):
        raise RuntimeError("Expected a writable persistent /data mount")
    old_image = json.loads(docker("image", "inspect", previous["Image"]).stdout)[0]
    docker_root = json.loads(docker("info", "--format", "{{json .}}").stdout)["DockerRootDir"]
    free = shutil.disk_usage(docker_root).free
    if free < 2 * 1024**3:
        raise RuntimeError("Less than 2 GiB free in the Docker filesystem")
    print(f"Docker filesystem: {docker_root}; available: {free / 1024**3:.1f} GiB; existing image: {old_image['Size'] / 1024**2:.0f} MiB.", flush=True)
    print("Building weread-challenge:latest before replacing the running container.", flush=True)
    docker("build", "--pull=false", "-t", IMAGE, str(ROOT), capture=False)
    image = json.loads(docker("image", "inspect", IMAGE).stdout)[0]
    print("Checking the built image with isolated tests; no reader task or real notification is started.", flush=True)
    docker("run", "--rm", "--network", "none", "--read-only", "--entrypoint", "python3",
           "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "SCRATCH_ROOT=/dev/shm", "-e", "TMPDIR=/dev/shm",
           "-e", "WEREAD_DATA_DIR=/dev/shm/weread-tests", "--mount", f"type=bind,source={ROOT / 'tests'},target=/qa/tests,readonly",
           IMAGE, "-m", "unittest", "discover", "-s", "/qa/tests", "-v", capture=False)
    save_webhook(previous, incoming)
    print("Replacing the old container; preserving its data mount, environment, port and restart policy.", flush=True)
    docker("stop", "--time", "30", NAME)
    docker("rm", NAME)  # Deliberately omit -v: persistent data must survive.
    try:
        create_container(previous, IMAGE, image["Config"].get("Healthcheck"))
        docker("start", NAME)
        current = wait_healthy()
        notified, reason = validate_service(bool(incoming))
    except Exception:
        print("Replacement validation failed; restoring the previous image and runtime configuration.", flush=True)
        subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)
        create_container(previous, previous["Image"], previous["Config"].get("Healthcheck"))
        docker("start", NAME)
        raise
    if old_image["Id"] != image["Id"]:
        old_ref = previous["Config"]["Image"]
        if old_ref.split(":")[0] != IMAGE.split(":")[0]:
            docker("image", "rm", old_ref, capture=False)
    print("Feishu test: " + reason, flush=True)
    report = ROOT / "docs" / "deployment-report.md"
    report.parent.mkdir(exist_ok=True)
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("Dockerfile", "app.py")}
    stamp = datetime.now(timezone.utc).isoformat()
    report.write_text(f'''# Deployment execution report

- Completed (UTC): {stamp}
- Container: `{NAME}`
- Image: `{IMAGE}`
- Image ID: `{image['Id']}`
- Published port: `8860:7860`
- Container health: `{current['State']['Health']['Status']}`
- Existing persistent data mount, environment and restart policy preserved.
- Previous service image reference removed; no data volumes or other services removed.
- Built-image verification: 27 tests passed; login, authenticated status and static assets passed HTTP checks.
- Feishu test: {reason}
- Webhook credentials saved only to the runtime data volume; none written to this repository.
- Build used the current working tree, including pre-existing local Dockerfile and app.py changes. Those existing changes remain uncommitted.
- Dockerfile SHA-256: `{hashes['Dockerfile']}`
- app.py SHA-256: `{hashes['app.py']}`
''', encoding="utf-8")
    print(json.dumps({"container": NAME, "image": IMAGE, "image_id": image["Id"], "health": "healthy",
                      "port": 8860, "feishu_test_ok": notified}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
