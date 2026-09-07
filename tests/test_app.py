import pytest

from app import ApiError, fetch_all_jobs, search_jobs


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self.payload = payload
        self.text = text
        self.ok = status_code < 400

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_search_jobs_posts_to_expected_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResponse(payload={"data": [{"id": 1}]})

    monkeypatch.setattr("app.requests.post", fake_post)

    result = search_jobs(
        api_key="secret",
        base_url="https://api.example.test/dev",
        payload={"company_id": 123},
    )

    assert result == {"data": [{"id": 1}]}
    assert captured["url"] == "https://api.example.test/dev/recruiting/jobs/search-jobs"
    assert captured["json"] == {"company_id": 123}
    assert captured["headers"]["x-company-api-key"] == "secret"
    assert captured["timeout"] == 20.0


def test_search_jobs_raises_without_leaking_key(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(status_code=401, text="invalid credentials")

    monkeypatch.setattr("app.requests.post", fake_post)

    with pytest.raises(ApiError, match="HTTP 401") as error:
        search_jobs(
            api_key="do-not-print-this",
            base_url="https://api.example.test/dev",
            payload={},
        )

    assert "do-not-print-this" not in str(error.value)


def test_fetch_all_jobs_combines_all_pages(monkeypatch):
    requests_seen = []
    pages = {
        1: {"data": {"Jobs": [{"id": 1}], "TotalPage": 2}},
        2: {"data": {"Jobs": [{"id": 2}], "TotalPage": 2}},
    }

    def fake_post(url, *, headers, json, timeout):
        requests_seen.append(json)
        return FakeResponse(payload=pages[json["Page"]])

    monkeypatch.setattr("app.requests.post", fake_post)

    result = fetch_all_jobs(
        api_key="secret",
        base_url="https://api.example.test/dev",
        payload={"Published": True},
    )

    assert result == [{"id": 1}, {"id": 2}]
    assert requests_seen == [
        {"Published": True, "Page": 1, "PerPage": 100},
        {"Published": True, "Page": 2, "PerPage": 100},
    ]


def test_fetch_all_jobs_returns_empty_list_without_results(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(payload={"data": {"Jobs": [], "TotalPage": 0}})

    monkeypatch.setattr("app.requests.post", fake_post)

    result = fetch_all_jobs(
        api_key="secret",
        base_url="https://api.example.test/dev",
    )

    assert result == []
