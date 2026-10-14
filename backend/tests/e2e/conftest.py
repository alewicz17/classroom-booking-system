"""The E2E stack (ADR 0008): Testcontainers Postgres, the API in-process, `vite preview`."""

import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import uvicorn

from booking.adapters.api import create_app
from booking.adapters.memory import FixedClock
from booking.adapters.postgres import PostgresUnitOfWork

FRONTEND_DIR = Path(__file__).parents[3] / "frontend"
# The same time as NOW in tests/conftest.py, which is not importable as a module.
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
HOST = "127.0.0.1"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def api_url(postgres_url: str) -> Iterator[str]:
    app = create_app(uow_factory=lambda: PostgresUnitOfWork(postgres_url), clock=FixedClock(NOW))
    # The socket listens before the thread starts, so no wait is needed: early
    # connections queue until uvicorn accepts them.
    sock = socket.socket()
    sock.bind((HOST, 0))
    sock.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    yield f"http://{HOST}:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join()
    sock.close()


@pytest.fixture(scope="session")
def base_url(api_url: str) -> Iterator[str]:
    """Overrides pytest-base-url, so `page.goto("/")` opens the frontend."""
    npm = shutil.which("npm")
    assert npm is not None, "npm is required for the e2e tests"
    subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, check=True)
    port = free_port()
    # Vite is started with node directly: on Windows npm is a .cmd wrapper, and
    # terminating it would leave the server running.
    preview = subprocess.Popen(
        [
            "node",
            "node_modules/vite/bin/vite.js",
            "preview",
            "--host",
            HOST,
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=FRONTEND_DIR,
        env={**os.environ, "API_URL": api_url, "NO_COLOR": "1"},
        stdout=subprocess.PIPE,
        text=True,
    )
    url = f"http://{HOST}:{port}"
    assert preview.stdout is not None
    # vite preview prints its URL once it is listening.
    for line in preview.stdout:
        if url in line:
            break
    else:
        raise RuntimeError("vite preview exited before it started listening")
    yield url
    preview.terminate()
    preview.wait()


@pytest.fixture(autouse=True)
def no_bookings(database_url: str) -> None:
    """Each test starts with the seeded rooms and users and no bookings."""
