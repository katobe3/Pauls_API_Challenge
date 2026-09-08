import pytest

from app import (
    ApiError,
    add_application_details_to_steps,
    add_pipeline_template_names,
    fetch_all_jobs,
    fetch_applications_for_step,
    get_pipeline_template_name,
    get_pipeline_steps,
    get_step_agents,
    search_jobs,
)


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


def test_get_pipeline_template_name_uses_template_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, *, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return FakeResponse(payload={"data": {"Name": "Hiring pipeline"}})

    monkeypatch.setattr("app.requests.get", fake_get)

    result = get_pipeline_template_name(
        api_key="secret",
        base_url="https://api.example.test/dev",
        pipeline_template_id="pipeline-123",
    )

    assert result == "Hiring pipeline"
    assert captured["url"] == (
        "https://api.example.test/dev/recruiting/job-step-templates/pipelines/pipeline-123"
    )
    assert captured["headers"]["x-company-api-key"] == "secret"


def test_add_pipeline_template_names_deduplicates_lookups(monkeypatch):
    name_calls = []
    steps_calls = []

    def fake_get_pipeline_template_name(**kwargs):
        name_calls.append(kwargs["pipeline_template_id"])
        return "Standard pipeline"

    def fake_get_pipeline_steps(**kwargs):
        steps_calls.append(kwargs["pipeline_template_id"])
        return [{"ID": "step-1", "Name": "Application review"}]

    def fake_add_agent_details_to_steps(steps, **kwargs):
        return [
            {
                **steps[0],
                "HasAgent": True,
                "Agents": [
                    {
                        "Name": "Screening agent",
                        "Instructions": {"SystemPrompt": "Screen candidates."},
                    }
                ],
            }
        ]

    monkeypatch.setattr("app.get_pipeline_template_name", fake_get_pipeline_template_name)
    monkeypatch.setattr("app.get_pipeline_steps", fake_get_pipeline_steps)
    monkeypatch.setattr("app.add_agent_details_to_steps", fake_add_agent_details_to_steps)
    monkeypatch.setattr(
        "app.add_application_details_to_steps",
        lambda steps, **kwargs: steps,
    )

    jobs = add_pipeline_template_names(
        [
            {"id": 1, "PipelineTemplateID": "pipeline-123"},
            {"id": 2, "PipelineTemplateID": "pipeline-123"},
            {"id": 3},
        ],
        api_key="secret",
        base_url="https://api.example.test/dev",
    )

    assert name_calls == ["pipeline-123"]
    assert steps_calls == ["pipeline-123"]
    assert jobs == [
        {
            "id": 1,
            "PipelineTemplateID": "pipeline-123",
            "PipelineTemplateName": "Standard pipeline",
            "PipelineSteps": [
                {
                    "ID": "step-1",
                    "Name": "Application review",
                    "HasAgent": True,
                    "Agents": [
                        {
                            "Name": "Screening agent",
                            "Instructions": {"SystemPrompt": "Screen candidates."},
                        }
                    ],
                }
            ],
        },
        {
            "id": 2,
            "PipelineTemplateID": "pipeline-123",
            "PipelineTemplateName": "Standard pipeline",
            "PipelineSteps": [
                {
                    "ID": "step-1",
                    "Name": "Application review",
                    "HasAgent": True,
                    "Agents": [
                        {
                            "Name": "Screening agent",
                            "Instructions": {"SystemPrompt": "Screen candidates."},
                        }
                    ],
                }
            ],
        },
        {"id": 3, "PipelineTemplateName": None, "PipelineSteps": []},
    ]


def test_get_pipeline_steps_uses_steps_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, *, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return FakeResponse(
            payload={
                "data": {
                    "JobStepTemplates": [
                        {"ID": "step-1", "Name": "Application review"}
                    ]
                }
            }
        )

    monkeypatch.setattr("app.requests.get", fake_get)

    result = get_pipeline_steps(
        api_key="secret",
        base_url="https://api.example.test/dev",
        pipeline_template_id="pipeline-123",
    )

    assert result == [{"ID": "step-1", "Name": "Application review"}]
    assert captured["url"] == (
        "https://api.example.test/dev/recruiting/job-step-templates/"
        "pipelines/pipeline-123/steps"
    )
    assert captured["headers"]["x-company-api-key"] == "secret"


def test_get_step_agents_returns_configured_agents(monkeypatch):
    captured = {}

    def fake_get(url, *, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return FakeResponse(
            payload={
                "data": {
                    "JobStepAgentTemplates": [
                        {
                            "Name": "Screening agent",
                            "Instructions": {"SystemPrompt": "Screen candidates."},
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("app.requests.get", fake_get)

    result = get_step_agents(
        api_key="secret",
        base_url="https://api.example.test/dev",
        pipeline_template_id="pipeline-123",
        step_template_id="step-1",
    )

    assert result[0]["Instructions"]["SystemPrompt"] == "Screen candidates."
    assert captured["url"] == (
        "https://api.example.test/dev/recruiting/job-step-templates/"
        "pipelines/pipeline-123/steps/step-1/agents"
    )


def test_add_agent_details_to_steps_marks_steps_without_agents(monkeypatch):
    monkeypatch.setattr("app.get_step_agents", lambda **kwargs: [])

    from app import add_agent_details_to_steps

    result = add_agent_details_to_steps(
        [{"ID": "step-1", "Name": "Application review"}],
        api_key="secret",
        base_url="https://api.example.test/dev",
        pipeline_template_id="pipeline-123",
    )

    assert result == [
        {
            "ID": "step-1",
            "Name": "Application review",
            "HasAgent": False,
            "Agents": [],
        }
    ]


def test_fetch_applications_for_step_paginates_and_filters_job_and_step(monkeypatch):
    requests_seen = []
    pages = {
        1: {"data": {"JobApplications": [{"id": 1}], "TotalPage": 2}},
        2: {"data": {"JobApplications": [{"id": 2}], "TotalPage": 2}},
    }

    def fake_post(url, *, headers, json, timeout):
        requests_seen.append(json)
        return FakeResponse(payload=pages[json["Page"]])

    monkeypatch.setattr("app.requests.post", fake_post)

    result = fetch_applications_for_step(
        api_key="secret",
        base_url="https://api.example.test/dev",
        job_id=99,
        step_name="Application review",
    )

    assert result == [{"id": 1}, {"id": 2}]
    assert requests_seen[0] == {
        "Must": [
            {"Key": "paulsjob_job_id", "Operator": "is", "Value": 99},
            {
                "Key": "app_status_name",
                "Operator": "is",
                "Value": "Application review",
            },
        ],
        "Page": 1,
        "PerPage": 100,
    }


def test_add_application_details_to_steps_adds_count(monkeypatch):
    monkeypatch.setattr(
        "app.fetch_applications_for_step",
        lambda **kwargs: [{"id": 1}, {"id": 2}],
    )

    result = add_application_details_to_steps(
        [{"ID": "step-1", "Name": "Application review"}],
        api_key="secret",
        base_url="https://api.example.test/dev",
        job_id=99,
    )

    assert result[0]["Applications"] == [{"id": 1}, {"id": 2}]
    assert result[0]["ApplicationCount"] == 2
