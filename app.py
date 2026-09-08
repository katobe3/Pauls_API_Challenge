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


def add_pipeline_template_names(
    jobs: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Add the pipeline template name to every job that has a template ID."""

    names_by_id: dict[str, str] = {}
    enriched_jobs: list[dict[str, Any]] = []

    for job in jobs:
        enriched_job = dict(job)
        pipeline_template_id = job.get("PipelineTemplateID")

        if isinstance(pipeline_template_id, str) and pipeline_template_id:
            if pipeline_template_id not in names_by_id:
                names_by_id[pipeline_template_id] = get_pipeline_template_name(
                    api_key=api_key,
                    base_url=base_url,
                    pipeline_template_id=pipeline_template_id,
                    timeout=timeout,
                )
            enriched_job["PipelineTemplateName"] = names_by_id[pipeline_template_id]
        else:
            enriched_job["PipelineTemplateName"] = None

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
