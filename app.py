"""Call the Paul's Job jobs search endpoint and print its response."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.paulsjob.ai/dev"
ENDPOINT = "/recruiting/jobs/search-jobs"
PIPELINE_TEMPLATE_ENDPOINT = "/recruiting/job-step-templates/pipelines"
APPLICATION_ENDPOINT = "/recruiting/applications/search-applications"


class ApiError(RuntimeError):
    """Raised when the Paul's Job API request cannot be completed."""


def load_config() -> tuple[str, str]:
    """Load the API key and base URL from the local environment."""

    load_dotenv()
    api_key = os.getenv("PAULSJOB_API_KEY")
    base_url = os.getenv("PAULSJOB_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

    if not api_key or api_key == "your_api_key_here":
        raise ApiError(
            "PAULSJOB_API_KEY is missing. Add your key to a local .env file."
        )

    return api_key, base_url


def search_jobs(
    *,
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
    timeout: float = 20.0,
) -> Any:
    """POST to the jobs search endpoint and return the decoded JSON response."""

    response = requests.post(
        f"{base_url}{ENDPOINT}",
        headers={
            "Accept": "application/json",
            "x-company-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )

    if not response.ok:
        # Do not include request headers in the error. This keeps the API key out
        # of terminal output and test failure messages.
        detail = response.text.strip()
        raise ApiError(
            f"API request failed with HTTP {response.status_code}"
            + (f": {detail[:500]}" if detail else ".")
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ApiError("The API returned a successful response that was not JSON.") from exc


def fetch_all_jobs(
    *,
    api_key: str,
    base_url: str,
    payload: dict[str, Any] | None = None,
    per_page: int = 100,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Fetch every job page allowed by the API and return one combined list."""

    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100.")

    base_payload = dict(payload or {})
    all_jobs: list[dict[str, Any]] = []
    page = 1

    while True:
        page_payload = {
            **base_payload,
            "Page": page,
            "PerPage": per_page,
        }
        result = search_jobs(
            api_key=api_key,
            base_url=base_url,
            payload=page_payload,
            timeout=timeout,
        )

        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise ApiError("The API response did not contain a valid data object.")

        jobs = data.get("Jobs", [])
        if not isinstance(jobs, list):
            raise ApiError("The API response did not contain a valid Jobs list.")

        all_jobs.extend(job for job in jobs if isinstance(job, dict))

        total_pages = data.get("TotalPage", 0) or 0
        if page >= total_pages or not jobs:
            return all_jobs

        page += 1


def get_pipeline_template_name(
    *,
    api_key: str,
    base_url: str,
    pipeline_template_id: str,
    timeout: float = 20.0,
) -> str:
    """Retrieve a pipeline template name by its ID."""

    encoded_id = quote(pipeline_template_id, safe="")
    response = requests.get(
        f"{base_url}{PIPELINE_TEMPLATE_ENDPOINT}/{encoded_id}",
        headers={
            "Accept": "application/json",
            "x-company-api-key": api_key,
        },
        timeout=timeout,
    )

    if not response.ok:
        detail = response.text.strip()
        raise ApiError(
            f"Pipeline template request failed with HTTP {response.status_code}"
            + (f": {detail[:500]}" if detail else ".")
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise ApiError("The pipeline template response was not JSON.") from exc

    data = result.get("data") if isinstance(result, dict) else None
    name = data.get("Name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name:
        raise ApiError("The pipeline template response did not contain a Name.")

    return name


def get_pipeline_steps(
    *,
    api_key: str,
    base_url: str,
    pipeline_template_id: str,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Retrieve all step templates belonging to a pipeline template."""

    encoded_id = quote(pipeline_template_id, safe="")
    response = requests.get(
        f"{base_url}{PIPELINE_TEMPLATE_ENDPOINT}/{encoded_id}/steps",
        headers={
            "Accept": "application/json",
            "x-company-api-key": api_key,
        },
        timeout=timeout,
    )

    if not response.ok:
        detail = response.text.strip()
        raise ApiError(
            f"Pipeline steps request failed with HTTP {response.status_code}"
            + (f": {detail[:500]}" if detail else ".")
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise ApiError("The pipeline steps response was not JSON.") from exc

    data = result.get("data") if isinstance(result, dict) else None
    steps = data.get("JobStepTemplates") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        raise ApiError("The pipeline steps response did not contain JobStepTemplates.")

    return [step for step in steps if isinstance(step, dict)]


def get_step_agents(
    *,
    api_key: str,
    base_url: str,
    pipeline_template_id: str,
    step_template_id: str,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Retrieve the agent templates configured for one pipeline step."""

    encoded_pipeline_id = quote(pipeline_template_id, safe="")
    encoded_step_id = quote(step_template_id, safe="")
    response = requests.get(
        f"{base_url}{PIPELINE_TEMPLATE_ENDPOINT}/{encoded_pipeline_id}"
        f"/steps/{encoded_step_id}/agents",
        headers={
            "Accept": "application/json",
            "x-company-api-key": api_key,
        },
        timeout=timeout,
    )

    if not response.ok:
        detail = response.text.strip()
        raise ApiError(
            f"Step agents request failed with HTTP {response.status_code}"
            + (f": {detail[:500]}" if detail else ".")
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise ApiError("The step agents response was not JSON.") from exc

    data = result.get("data") if isinstance(result, dict) else None
    agents = data.get("JobStepAgentTemplates") if isinstance(data, dict) else None
    if not isinstance(agents, list):
        raise ApiError("The step agents response did not contain JobStepAgentTemplates.")

    return [agent for agent in agents if isinstance(agent, dict)]


def add_agent_details_to_steps(
    steps: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str,
    pipeline_template_id: str,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Add agent presence and system prompts to each pipeline step."""

    agents_by_step_id: dict[str, list[dict[str, Any]]] = {}
    enriched_steps: list[dict[str, Any]] = []

    for step in steps:
        enriched_step = dict(step)
        step_template_id = step.get("ID")

        if isinstance(step_template_id, str) and step_template_id:
            if step_template_id not in agents_by_step_id:
                agents_by_step_id[step_template_id] = get_step_agents(
                    api_key=api_key,
                    base_url=base_url,
                    pipeline_template_id=pipeline_template_id,
                    step_template_id=step_template_id,
                    timeout=timeout,
                )
            agents = agents_by_step_id[step_template_id]
        else:
            agents = []

        enriched_step["HasAgent"] = bool(agents)
        enriched_step["Agents"] = [
            {
                "Name": agent.get("Name"),
                "Instructions": {
                    "SystemPrompt": (
                        agent.get("Instructions", {}).get("SystemPrompt")
                        if isinstance(agent.get("Instructions"), dict)
                        else None
                    )
                },
            }
            for agent in agents
        ]
        enriched_steps.append(enriched_step)

    return enriched_steps


def search_applications(
    *,
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
    timeout: float = 20.0,
) -> Any:
    """POST to the application search endpoint and return decoded JSON."""

    response = requests.post(
        f"{base_url}{APPLICATION_ENDPOINT}",
        headers={
            "Accept": "application/json",
            "x-company-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )

    if not response.ok:
        detail = response.text.strip()
        raise ApiError(
            f"Application search failed with HTTP {response.status_code}"
            + (f": {detail[:500]}" if detail else ".")
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ApiError("The application search response was not JSON.") from exc


def fetch_applications_for_step(
    *,
    api_key: str,
    base_url: str,
    job_id: int | str,
    step_name: str,
    per_page: int = 100,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Fetch applications currently assigned to one job step."""

    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100.")

    applications: list[dict[str, Any]] = []
    page = 1

    while True:
        result = search_applications(
            api_key=api_key,
            base_url=base_url,
            payload={
                "Must": [
                    {
                        "Key": "paulsjob_job_id",
                        "Operator": "is",
                        "Value": job_id,
                    },
                    {
                        "Key": "app_status_name",
                        "Operator": "is",
                        "Value": step_name,
                    },
                ],
                "Page": page,
                "PerPage": per_page,
            },
            timeout=timeout,
        )

        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise ApiError("The application search response did not contain a valid data object.")

        page_applications = data.get("JobApplications", [])
        if not isinstance(page_applications, list):
            raise ApiError("The application search response did not contain JobApplications.")

        applications.extend(
            application
            for application in page_applications
            if isinstance(application, dict)
        )

        total_pages = data.get("TotalPage", 0) or 0
        if page >= total_pages or not page_applications:
            return applications

        page += 1


def add_application_details_to_steps(
    steps: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str,
    job_id: int | str,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Add current applications and their count to each job step."""

    enriched_steps: list[dict[str, Any]] = []
    applications_by_step_name: dict[str, list[dict[str, Any]]] = {}

    for step in steps:
        enriched_step = dict(step)
        step_name = step.get("Name")

        if isinstance(step_name, str) and step_name:
            if step_name not in applications_by_step_name:
                applications_by_step_name[step_name] = fetch_applications_for_step(
                    api_key=api_key,
                    base_url=base_url,
                    job_id=job_id,
                    step_name=step_name,
                    timeout=timeout,
                )
            applications = applications_by_step_name[step_name]
        else:
            applications = []

        enriched_step["Applications"] = applications
        enriched_step["ApplicationCount"] = len(applications)
        enriched_steps.append(enriched_step)

    return enriched_steps


def add_pipeline_template_names(
    jobs: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Add pipeline template names and steps to every job with a template ID."""

    details_by_id: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    enriched_jobs: list[dict[str, Any]] = []

    for job in jobs:
        enriched_job = dict(job)
        pipeline_template_id = job.get("PipelineTemplateID")

        if isinstance(pipeline_template_id, str) and pipeline_template_id:
            if pipeline_template_id not in details_by_id:
                details_by_id[pipeline_template_id] = (
                    get_pipeline_template_name(
                        api_key=api_key,
                        base_url=base_url,
                        pipeline_template_id=pipeline_template_id,
                        timeout=timeout,
                    ),
                    add_agent_details_to_steps(
                        get_pipeline_steps(
                            api_key=api_key,
                            base_url=base_url,
                            pipeline_template_id=pipeline_template_id,
                            timeout=timeout,
                        ),
                        api_key=api_key,
                        base_url=base_url,
                        pipeline_template_id=pipeline_template_id,
                        timeout=timeout,
                    ),
                )
            pipeline_name, pipeline_steps = details_by_id[pipeline_template_id]
            enriched_job["PipelineTemplateName"] = pipeline_name
            job_id = job.get("PaulsjobJobID")
            enriched_job["PipelineSteps"] = (
                add_application_details_to_steps(
                    pipeline_steps,
                    api_key=api_key,
                    base_url=base_url,
                    job_id=job_id,
                    timeout=timeout,
                )
                if job_id is not None
                else pipeline_steps
            )
        else:
            enriched_job["PipelineTemplateName"] = None
            enriched_job["PipelineSteps"] = []

        enriched_jobs.append(enriched_job)

    return enriched_jobs


def main() -> int:
    try:
        api_key, base_url = load_config()
        jobs = fetch_all_jobs(
            api_key=api_key,
            base_url=base_url,
            payload={},
        )
        jobs = add_pipeline_template_names(
            jobs,
            api_key=api_key,
            base_url=base_url,
        )
    except ApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Error: could not reach the Paul's Job API: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(jobs, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
