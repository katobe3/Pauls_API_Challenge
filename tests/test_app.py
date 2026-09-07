import pytest

from app import ApiError, fetch_people


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


def test_fetch_people_posts_to_expected_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResponse(payload={"data": [{"id": 1}]})

    monkeypatch.setattr("app.requests.post", fake_post)

    result = fetch_people(
        api_key="secret",
        base_url="https://api.example.test/dev",
        payload={"company_id": 123},
    )

    assert result == {"data": [{"id": 1}]}
    assert captured["url"] == "https://api.example.test/dev/company/person/list"
    assert captured["json"] == {"company_id": 123}
    assert captured["headers"]["x-company-api-key"] == "secret"
    assert captured["timeout"] == 20.0


def test_fetch_people_raises_without_leaking_key(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(status_code=401, text="invalid credentials")

    monkeypatch.setattr("app.requests.post", fake_post)

    with pytest.raises(ApiError, match="HTTP 401") as error:
        fetch_people(
            api_key="do-not-print-this",
            base_url="https://api.example.test/dev",
            payload={},
        )

    assert "do-not-print-this" not in str(error.value)
