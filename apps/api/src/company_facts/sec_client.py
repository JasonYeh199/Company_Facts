from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import Settings

SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"


@dataclass(frozen=True)
class DownloadMetadata:
    path: Path
    etag: str | None
    last_modified: str | None
    content_length: int | None


class SecConfigurationError(RuntimeError):
    pass


class SecClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        if not settings.sec_is_configured:
            raise SecConfigurationError(
                "SEC_USER_AGENT 必須包含產品名稱與有效聯絡信箱，且不可使用 example.com。"
            )
        self.settings = settings
        self._interval = 1 / settings.sec_requests_per_second
        self._last_request = 0.0
        self._client = httpx.Client(
            headers={
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, application/zip;q=0.9, */*;q=0.8",
            },
            timeout=httpx.Timeout(60, read=300),
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> SecClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(6):
            self._throttle()
            try:
                response = self._client.request(method, url, **kwargs)
                self._last_request = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 5:
                        response.raise_for_status()
                    retry_after = response.headers.get("Retry-After")
                    delay = (
                        float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                    )
                    time.sleep(min(delay, 30))
                    continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == 5:
                    raise
                time.sleep(min(2**attempt, 30))
        raise RuntimeError("SEC request failed") from last_error

    def get_json(self, url: str) -> dict[str, Any]:
        response = self._request("GET", url)
        return json.loads(response.content)

    def head(self, url: str) -> httpx.Headers:
        return self._request("HEAD", url).headers

    def download(self, url: str, destination: Path) -> DownloadMetadata:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".partial")
        last_error: Exception | None = None
        for attempt in range(6):
            existing = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            self._throttle()
            try:
                with self._client.stream("GET", url, headers=headers) as response:
                    self._last_request = time.monotonic()
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 5:
                            response.raise_for_status()
                        retry_after = response.headers.get("Retry-After")
                        delay = (
                            float(retry_after)
                            if retry_after and retry_after.isdigit()
                            else 2**attempt
                        )
                        time.sleep(min(delay, 30))
                        continue
                    response.raise_for_status()
                    if existing and response.status_code == 200:
                        existing = 0
                    mode = "ab" if existing and response.status_code == 206 else "wb"
                    with partial.open(mode) as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    etag = response.headers.get("ETag")
                    last_modified = response.headers.get("Last-Modified")
                    length_header = response.headers.get("Content-Length")
                partial.replace(destination)
                return DownloadMetadata(
                    path=destination,
                    etag=etag,
                    last_modified=last_modified,
                    content_length=int(length_header) + existing if length_header else None,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == 5:
                    raise
                time.sleep(min(2**attempt, 30))
        raise RuntimeError("SEC download failed") from last_error

    def company_facts(self, cik: str) -> dict[str, Any]:
        return self.get_json(f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json")

    def submissions(self, cik: str) -> dict[str, Any]:
        return self.get_json(f"{SEC_DATA_BASE}/submissions/CIK{cik}.json")


URLS = {
    "tickers": f"{SEC_WWW_BASE}/files/company_tickers_exchange.json",
    "funds": f"{SEC_WWW_BASE}/files/company_tickers_mf.json",
    "companyfacts": f"{SEC_WWW_BASE}/Archives/edgar/daily-index/xbrl/companyfacts.zip",
    "submissions": f"{SEC_WWW_BASE}/Archives/edgar/daily-index/bulkdata/submissions.zip",
}
