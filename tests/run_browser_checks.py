"""Run isolated browser checks inside the existing image, without a reader run."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

scratch = Path(os.environ["SCRATCH_ROOT"])
output = Path(os.environ["WEREAD_QA_DIR"])
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="weread-ui-", dir=scratch) as work:
    child_env = dict(os.environ, WEREAD_DATA_DIR=str(Path(work) / "data"),
                     XDG_CONFIG_HOME=str(Path(work) / "config"), XDG_CACHE_HOME=str(Path(work) / "cache"))
    with (output / "fixture.log").open("w") as log:
        server = subprocess.Popen(["python3", "tests/browser_fixture.py"], env=child_env,
                                  stdout=log, stderr=subprocess.STDOUT)
        try:
            for attempt in range(50):
                try:
                    urllib.request.urlopen("http://127.0.0.1:7860/healthz", timeout=1).close()
                    break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError("Browser fixture exited; see fixture.log")
                    time.sleep(0.1)
            else:
                raise RuntimeError("Browser fixture did not start")
            result = subprocess.run(["node", "tests/browser_smoke.js"], env=child_env)
            raise SystemExit(result.returncode)
        finally:
            server.terminate()
            server.wait(timeout=5)
