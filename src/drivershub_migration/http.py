"""Conservative HTTP client with rate-limit-aware retries."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Callable


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    def json(self) -> object:
        return json.loads(self.body)


class RequestFailed(RuntimeError):
    def __init__(self, message: str, response: Response | None = None) -> None:
        super().__init__(message)
        self.response = response


def _headers(message: Message) -> dict[str, str]:
    return {key.lower(): value for key, value in message.items()}


class HttpClient:
    def __init__(
        self,
        authorization: str | None,
        *,
        timeout: float = 30,
        minimum_interval: float = 0.25,
        max_attempts: int = 5,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.authorization = authorization
        self.timeout = timeout
        self.minimum_interval = minimum_interval
        self.max_attempts = max_attempts
        self.sleeper = sleeper
        self._last_request = 0.0

    def get(self, url: str, *, expect_json: bool = True) -> Response:
        last_error: Exception | None = None
        last_response: Response | None = None
        for attempt in range(self.max_attempts):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.minimum_interval:
                self.sleeper(self.minimum_interval - elapsed)
            try:
                response = self._once(url)
                last_response = response
                if self._valid(response, expect_json):
                    return response
                last_error = RequestFailed(
                    f"Unexpected response from {url}: HTTP {response.status}, "
                    f"content type {response.content_type or 'missing'}",
                    response,
                )
                if response.status in {400, 401, 404, 405, 422}:
                    raise last_error
                delay = self._delay(response, attempt)
            except (TimeoutError, ConnectionError, urllib.error.URLError) as exc:
                last_error = exc
                delay = self._backoff(attempt)
            if attempt + 1 < self.max_attempts:
                self.sleeper(delay)
        raise RequestFailed(
            f"Request failed after {self.max_attempts} attempts: {url}",
            last_response,
        ) from last_error

    def _once(self, url: str) -> Response:
        headers = {"Accept": "application/json", "User-Agent": "DriversHubMigrationTools/0.1"}
        if self.authorization:
            headers["Authorization"] = self.authorization
        request = urllib.request.Request(url, headers=headers, method="GET")
        self._last_request = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as result:
                return Response(result.status, _headers(result.headers), result.read())
        except urllib.error.HTTPError as exc:
            return Response(exc.code, _headers(exc.headers), exc.read())

    @staticmethod
    def _valid(response: Response, expect_json: bool) -> bool:
        if response.status < 200 or response.status >= 300:
            return False
        if not expect_json:
            return True
        if response.content_type not in {"application/json", "text/json"}:
            return False
        try:
            response.json()
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return True

    def _delay(self, response: Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(float(retry_after), self.minimum_interval)
            except ValueError:
                pass
        return self._backoff(attempt)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(60.0, 2.0**attempt) + random.uniform(0.0, 0.5)
