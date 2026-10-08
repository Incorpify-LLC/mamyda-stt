"""Exercise a real loopback HTTP process without persistent credentials or media."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time

import httpx


def test_real_http_server_authentication_and_readiness(tmp_path):
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    key = secrets.token_urlsafe(32)
    environment = {
        **os.environ,
        "STT_API_KEYS": json.dumps({key: "smoke-test"}),
        "STT_DATA_DIR": str(tmp_path / "data"),
    }
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "mamyda_stt.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1
        ) as client:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                assert server.poll() is None, "HTTP server exited during startup"
                try:
                    if client.get("/health/live").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                raise AssertionError("HTTP server did not become live")
            assert client.get("/v1/models").status_code == 401
            headers = {"Authorization": f"Bearer {key}"}
            assert client.get("/v1/models", headers=headers).status_code == 200
            assert client.get("/health/ready", headers=headers).status_code == 503
            assert client.get("/openapi.json", headers=headers).status_code == 200
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
