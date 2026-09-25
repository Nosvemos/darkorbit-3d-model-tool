"""HTTP client for the standalone CLI render queue service."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


DEFAULT_SERVER = "http://127.0.0.1:8766"
DEFAULT_SERVER_URL = os.environ.get("DO3D_QUEUE_URL", DEFAULT_SERVER).rstrip("/")


class QueueClientError(RuntimeError):
    pass


class QueueClient:
    """Talk to the queue service used only by CLI commands."""

    def __init__(self, server: str = DEFAULT_SERVER_URL, timeout: float = 10):
        self.server = server.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, body: dict | None = None) -> dict:
        url = urljoin(self.server + "/", path.lstrip("/"))
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(url, data=data,
                          headers={"Content-Type": "application/json"} if data is not None else {},
                          method="POST" if data is not None else "GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("error")
            except (ValueError, UnicodeDecodeError, AttributeError):
                detail = None
            raise QueueClientError(detail or f"queue server returned HTTP {e.code}") from e
        except (URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", None) or e
            raise QueueClientError(
                f"cannot reach queue server at {self.server}: {reason}. "
                "Start it with `do3d queue serve` or pass --queue-server."
            ) from e
        try:
            return json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise QueueClientError(f"queue server returned invalid JSON for {path}") from e

    def get(self, path: str) -> dict:
        return self._request(path)

    def post(self, path: str, body: dict) -> dict:
        return self._request(path, body)

    def jobs(self) -> dict:
        return self.get("/api/jobs")

    def job(self, job_id: str) -> dict:
        return self.get("/api/job?" + urlencode({"id": job_id}))

    def submit(self, endpoint: str, body: dict) -> dict:
        return self.post(endpoint, body)

    def control(self, action: str) -> dict:
        return self.post("/api/queue/control", {"action": action})

    def cancel(self, job_id: str) -> dict:
        return self.post("/api/job/cancel", {"id": job_id})

    def clear_history(self) -> dict:
        return self.post("/api/jobs/clear", {})
