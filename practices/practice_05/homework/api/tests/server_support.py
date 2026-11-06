"""Actual Uvicorn child processes, not an in-process fake API."""
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx

from app.config import API_ROOT


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def server(settings, log, *, offline=False):
    from urllib.parse import urlsplit
    env = dict(os.environ, HOMEWORK_API_ORIGIN=settings.origin, HOMEWORK_STORAGE_ROOT=str(settings.storage_root),
               HOMEWORK_UI_ROOT=str(settings.ui_root), PYTHONUNBUFFERED="1")
    if offline:
        env.update(HTTPS_PROXY="http://127.0.0.1:1", HTTP_PROXY="http://127.0.0.1:1", NO_PROXY="127.0.0.1")
    with log.open("ab") as output:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                    "--port", str(urlsplit(settings.origin).port), "--workers", "1"],
                                   cwd=API_ROOT, env=env, stdout=output, stderr=output)
        try:
            # Network readiness only. Not a source or export check.
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"Server stopped: {log}")
                try:
                    with httpx.Client(timeout=0.3, trust_env=False) as client:
                        if client.request("GET", settings.origin + "/api/v1/works/not-a-uuid").status_code == 422:
                            break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError("Server startup timed out")
            yield process
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
