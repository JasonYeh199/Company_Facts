import httpx
import pytest

from company_facts.config import Settings
from company_facts.sec_client import SecClient, SecConfigurationError


def settings() -> Settings:
    return Settings(
        sec_user_agent="Fundamental Test data-team@valid.test",
        sec_requests_per_second=8,
    )


def test_sec_client_retries_429_and_5xx(monkeypatch) -> None:
    statuses = iter((429, 503, 200))
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == "Fundamental Test data-team@valid.test"
        status = next(statuses)
        return httpx.Response(status, json={"ok": status == 200}, request=request)

    monkeypatch.setattr("company_facts.sec_client.time.sleep", sleeps.append)
    with SecClient(settings(), transport=httpx.MockTransport(handler)) as client:
        assert client.get_json("https://data.sec.gov/test.json") == {"ok": True}

    assert len(sleeps) >= 2


def test_download_resumes_partial_file_and_retries(monkeypatch, tmp_path) -> None:
    destination = tmp_path / "companyfacts.zip"
    partial = tmp_path / "companyfacts.zip.partial"
    partial.write_bytes(b"first-")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Range"] == "bytes=6-"
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            206,
            content=b"second",
            headers={"Content-Length": "6", "ETag": '"fixture"'},
            request=request,
        )

    monkeypatch.setattr("company_facts.sec_client.time.sleep", lambda _: None)
    with SecClient(settings(), transport=httpx.MockTransport(handler)) as client:
        metadata = client.download("https://www.sec.gov/companyfacts.zip", destination)

    assert destination.read_bytes() == b"first-second"
    assert not partial.exists()
    assert metadata.etag == '"fixture"'
    assert metadata.content_length == 12


def test_sec_client_rejects_placeholder_contact() -> None:
    invalid = Settings(sec_user_agent="Research contact@example.com")
    with pytest.raises(SecConfigurationError):
        SecClient(invalid)
