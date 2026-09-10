"""Generate a static Customer Health Check report from the Paul's Job API."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
import unicodedata
from urllib.parse import quote

import requests
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.paulsjob.ai/dev"
ENDPOINT = "/recruiting/jobs/search-jobs"
PIPELINE_TEMPLATE_ENDPOINT = "/recruiting/job-step-templates/pipelines"
APPLICATION_ENDPOINT = "/recruiting/applications/search-applications"
REPORT_PATH = Path("report.html")
BOTTLENECK_MIN_APPLICATIONS = 2
BOTTLENECK_MIN_SHARE = 0.50
BOTTLENECK_MIN_RATIO = 2.0
STUCK_WARNING_DAYS = 2
STUCK_CRITICAL_DAYS = 10
AGENT_REVIEW_WARNING_HOURS = 12
AGENT_REVIEW_CRITICAL_HOURS = 24
AGENT_REVIEW_GROUP_HIGH_COUNT = 2
SUSPICIOUS_APPLICATION_MIN_COUNT = 2
SUSPICIOUS_APPLICATION_HIGH_COUNT = 3


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


def detect_step_bottlenecks(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find job steps with unusually high application volume."""

    bottlenecks: list[dict[str, Any]] = []

    # Compare like-named steps across distinct pipeline templates. A pipeline
    # template is the useful comparison unit here: if it is used by several
    # jobs, aggregate those jobs before calculating the peer average.
    pipeline_step_counts: dict[str, dict[str, list[int]]] = {}
    for job in jobs:
        pipeline_id = job.get("PipelineTemplateID")
        if not pipeline_id:
            continue
        for step in job.get("PipelineSteps", []):
            if not isinstance(step, dict):
                continue
            step_name = step.get("Name")
            if not step_name:
                continue
            normalized_name = str(step_name).strip().casefold()
            count = step.get("ApplicationCount", 0)
            count = count if isinstance(count, int) else 0
            pipeline_step_counts.setdefault(normalized_name, {}).setdefault(
                str(pipeline_id), []
            ).append(max(0, count))

    for job in jobs:
        steps = [
            step
            for step in job.get("PipelineSteps", [])
            if isinstance(step, dict)
        ]
        if len(steps) < 2:
            continue

        counts = [
            max(0, step.get("ApplicationCount", 0))
            if isinstance(step.get("ApplicationCount", 0), int)
            else 0
            for step in steps
        ]
        total_applications = sum(counts)
        if total_applications == 0:
            continue

        job_id = job.get("PaulsjobJobID", job.get("JobPositionID", "unknown"))
        for step, count in zip(steps, counts):
            if count < BOTTLENECK_MIN_APPLICATIONS:
                continue

            other_count = total_applications - count
            comparison_average = other_count / (len(steps) - 1)
            share = count / total_applications
            ratio = count / max(comparison_average, 1)

            if share < BOTTLENECK_MIN_SHARE and ratio < BOTTLENECK_MIN_RATIO:
                continue

            step_name = step.get("Name", "Unnamed step")
            normalized_name = str(step_name).strip().casefold()
            pipeline_id = job.get("PipelineTemplateID")
            peer_counts = []
            if pipeline_id:
                for peer_pipeline_id, peer_job_counts in pipeline_step_counts.get(
                    normalized_name, {}
                ).items():
                    if peer_pipeline_id == str(pipeline_id):
                        continue
                    peer_counts.append(
                        {
                            "pipeline_id": peer_pipeline_id,
                            "application_count": sum(peer_job_counts),
                        }
                    )
            peer_average = (
                sum(item["application_count"] for item in peer_counts)
                / len(peer_counts)
                if peer_counts
                else None
            )

            bottlenecks.append(
                {
                    "type": "step_bottleneck",
                    "severity": "high" if share >= 0.75 or ratio >= 4 else "medium",
                    "job_id": job_id,
                    "job_title": job.get("JobPositionTitle"),
                    "step_id": step.get("ID"),
                    "step_name": step_name,
                    "application_count": count,
                    "total_applications": total_applications,
                    "share": share,
                    "comparison_average": comparison_average,
                    "ratio": ratio,
                    "peer_pipeline_count": len(peer_counts),
                    "peer_average": peer_average,
                    "peer_ratio": count / peer_average if peer_average else None,
                    "peer_pipeline_counts": peer_counts,
                    "guiding_questions": [
                        {
                            "question": "Is this step mostly manual?",
                            "action": "Speed up manual review through automation.",
                        },
                        {
                            "question": "Are next-step transition rules working?",
                            "action": "Review pipeline transition rules.",
                        },
                        {
                            "question": "Is the screening stage unnecessarily difficult?",
                            "action": "Simplify the screening process.",
                        },
                        {
                            "question": "Is this a temporary volume spike?",
                            "action": "Compare this period with other reporting periods.",
                        },
                    ],
                }
            )

    return bottlenecks


def _application_data(application: dict[str, Any]) -> dict[str, Any]:
    """Return the API's nested Application object when it is present."""

    nested = application.get("Application")
    return nested if isinstance(nested, dict) else application


def _application_field(
    application: dict[str, Any],
    field: str,
    default: Any = None,
) -> Any:
    """Read an application field from nested or flat API response shapes."""

    data = _application_data(application)
    return data.get(field, application.get(field, default))


def _application_identifier(application: dict[str, Any]) -> Any:
    """Return a non-empty application ID, if the API supplied one."""

    for field in ("ID", "ApplicationID", "ApplicationId", "id"):
        value = _application_field(application, field)
        if value is not None and str(value).strip():
            return value
    return None


def _parse_assigned_at(value: Any) -> datetime | None:
    """Parse an API timestamp into an aware UTC datetime."""

    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_true(value: Any) -> bool:
    return value is True or (
        isinstance(value, str) and value.strip().casefold() in {"true", "1", "yes"}
    )


def detect_stuck_applications(
    jobs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    warning_days: float = STUCK_WARNING_DAYS,
    critical_days: float = STUCK_CRITICAL_DAYS,
) -> list[dict[str, Any]]:
    """Find applications that have stayed in their current step too long.

    The API response tells us when an application was assigned to its current
    step, but does not provide complete transition history. Therefore each
    application returned under a step is treated as still being in that step.
    """

    if warning_days < 0 or critical_days < warning_days:
        raise ValueError("critical_days must be greater than or equal to warning_days.")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    anomalies: list[dict[str, Any]] = []
    for job in jobs:
        job_id = job.get("PaulsjobJobID", job.get("JobPositionID", "unknown"))
        for step in job.get("PipelineSteps", []):
            if not isinstance(step, dict):
                continue

            applications = step.get("Applications", [])
            if not isinstance(applications, list):
                continue

            for application in applications:
                if not isinstance(application, dict):
                    continue
                assigned_at_value = _application_field(application, "AssignedAt")
                assigned_at = _parse_assigned_at(assigned_at_value)
                if assigned_at is None:
                    continue

                days_in_step = (current_time - assigned_at).total_seconds() / 86400
                if days_in_step < warning_days:
                    continue

                human_review = _is_true(_application_field(application, "HumanReview"))
                agent_review = _is_true(_application_field(application, "AgentReview"))
                severity = (
                    "high"
                    if days_in_step >= critical_days
                    or human_review
                    or agent_review
                    else "medium"
                )
                anomalies.append(
                    {
                        "type": "stuck_application",
                        "severity": severity,
                        "job_id": job_id,
                        "job_title": job.get("JobPositionTitle"),
                        "step_id": step.get("ID"),
                        "step_name": step.get("Name", "Unnamed step"),
                        "application_id": _application_field(
                            application, "ID", application.get("id")
                        ),
                        "candidate_name": (
                            application.get("Person", {}).get("FullName")
                            if isinstance(application.get("Person"), dict)
                            else None
                        ),
                        "assigned_at": assigned_at_value,
                        "days_in_step": days_in_step,
                        "human_review": human_review,
                        "agent_review": agent_review,
                        "recommendation": (
                            "Review or reassign this candidate, confirm the next-step "
                            "rule, and decide whether to move, reject, or escalate."
                        ),
                    }
                )

    return anomalies


def detect_agent_reviews(
    jobs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    warning_hours: float = AGENT_REVIEW_WARNING_HOURS,
    critical_hours: float = AGENT_REVIEW_CRITICAL_HOURS,
    group_high_count: int = AGENT_REVIEW_GROUP_HIGH_COUNT,
) -> list[dict[str, Any]]:
    """Find applications waiting for an agent decision and group them by step."""

    if warning_hours < 0 or critical_hours < warning_hours:
        raise ValueError("critical_hours must be greater than or equal to warning_hours.")
    if group_high_count < 2:
        raise ValueError("group_high_count must be at least 2.")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for job in jobs:
        job_id = job.get("PaulsjobJobID", job.get("JobPositionID", "unknown"))
        pipeline_id = str(job.get("PipelineTemplateID", "unknown"))
        for step in job.get("PipelineSteps", []):
            if not isinstance(step, dict):
                continue
            agents = step.get("Agents", [])
            has_agent = bool(agents) or _is_true(step.get("HasAgent"))
            if not has_agent:
                continue
            agents = agents if isinstance(agents, list) else []

            waiting_applications = []
            for application in step.get("Applications", []):
                if not isinstance(application, dict):
                    continue
                agent_review_value = _application_field(
                    application, "AgentReview", None
                )
                if not _is_true(agent_review_value) and not (
                    isinstance(agent_review_value, bool) and not agent_review_value
                ):
                    continue
                if _application_field(application, "PaulDecision") is not None:
                    continue
                assigned_at_value = _application_field(application, "AssignedAt")
                assigned_at = _parse_assigned_at(assigned_at_value)
                if assigned_at is None:
                    continue
                waiting_hours = (current_time - assigned_at).total_seconds() / 3600
                if waiting_hours < warning_hours:
                    continue
                person = application.get("Person")
                waiting_applications.append(
                    {
                        "application_id": _application_field(
                            application, "ID", application.get("id")
                        ),
                        "candidate_name": (
                            person.get("FullName")
                            if isinstance(person, dict)
                            else None
                        ),
                        "assigned_at": assigned_at_value,
                        "waiting_hours": waiting_hours,
                        "review_mode": (
                            "confirmed"
                            if _is_true(agent_review_value)
                            else "handoff"
                        ),
                    }
                )

            if not waiting_applications:
                continue

            step_id = str(step.get("ID", step.get("Name", "unknown")))
            key = (str(job_id), pipeline_id, step_id)
            agent_names = [
                agent.get("Name")
                for agent in agents
                if isinstance(agent, dict) and agent.get("Name")
            ]
            has_system_prompt = any(
                isinstance(agent, dict)
                and isinstance(agent.get("Instructions"), dict)
                and bool(agent["Instructions"].get("SystemPrompt"))
                for agent in agents
            )
            existing = grouped.setdefault(
                key,
                {
                    "type": "agent_review",
                    "job_id": job_id,
                    "job_title": job.get("JobPositionTitle"),
                    "pipeline_id": job.get("PipelineTemplateID"),
                    "pipeline_name": job.get("PipelineTemplateName"),
                    "step_id": step.get("ID"),
                    "step_name": step.get("Name", "Unnamed step"),
                    "agent_names": agent_names,
                    "has_system_prompt": has_system_prompt,
                    "applications": [],
                },
            )
            existing["applications"].extend(waiting_applications)

    results = []
    for group in grouped.values():
        applications = group["applications"]
        oldest_waiting_hours = max(item["waiting_hours"] for item in applications)
        review_modes = {item["review_mode"] for item in applications}
        review_mode = (
            next(iter(review_modes)) if len(review_modes) == 1 else "mixed"
        )
        severity = (
            "high"
            if oldest_waiting_hours >= critical_hours
            or len(applications) >= group_high_count
            else "medium"
        )
        results.append(
            {
                **group,
                "severity": severity,
                "application_count": len(applications),
                "oldest_waiting_hours": oldest_waiting_hours,
                "review_mode": review_mode,
                "confirmed_application_count": sum(
                    item["review_mode"] == "confirmed" for item in applications
                ),
                "handoff_application_count": sum(
                    item["review_mode"] == "handoff" for item in applications
                ),
                "recommendation": (
                    "Review agent execution, system prompt completeness, candidate "
                    "data availability, and API, credit, or rate-limit failures."
                    if review_mode == "confirmed"
                    else "Verify that the application was handed off to the agent "
                    "and review the step configuration or integration."
                ),
                "guiding_question": (
                    "Is agent execution or processing delayed?"
                    if review_mode == "confirmed"
                    else "Agent handoff requires verification."
                ),
            }
        )

    return results


def _person_slug(application: dict[str, Any]) -> str | None:
    """Read PersonSlug from the common API response locations."""

    person = application.get("Person")
    sources = [application, _application_data(application)]
    if isinstance(person, dict):
        sources.append(person)
    for source in sources:
        for key in ("PersonSlug", "person_slug", "Slug"):
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _normalize_person_name(value: Any) -> str:
    """Normalize a name for cautious, case-insensitive comparison."""

    if value is None:
        return ""
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_accents.casefold()))


def _person_name_key(application: dict[str, Any]) -> str | None:
    """Build a normalized first-name/last-name identity for fallback matching."""

    person = application.get("Person")
    person = person if isinstance(person, dict) else {}
    first_name = _normalize_person_name(person.get("FirstName"))
    last_name = _normalize_person_name(person.get("LastName"))
    if not first_name or not last_name:
        full_name = _normalize_person_name(person.get("FullName"))
        parts = full_name.split()
        if len(parts) >= 2:
            first_name = first_name or parts[0]
            last_name = last_name or parts[-1]
    return f"{first_name}|{last_name}" if first_name and last_name else None


def detect_suspicious_applications(
    jobs: list[dict[str, Any]],
    *,
    minimum_count: int = SUSPICIOUS_APPLICATION_MIN_COUNT,
    high_count: int = SUSPICIOUS_APPLICATION_HIGH_COUNT,
) -> list[dict[str, Any]]:
    """Find candidates with multiple distinct applications for one job.

    The same application can appear under more than one current step while it
    moves through a pipeline. It is counted once by application ID, so normal
    movement does not create a duplicate alert.
    """

    if minimum_count < 2 or high_count < minimum_count:
        raise ValueError("high_count must be greater than or equal to minimum_count.")

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    name_grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for job in jobs:
        job_id = job.get("PaulsjobJobID", job.get("JobPositionID", "unknown"))
        for step in job.get("PipelineSteps", []):
            if not isinstance(step, dict):
                continue
            applications = step.get("Applications", [])
            if not isinstance(applications, list):
                continue
            for application in applications:
                if not isinstance(application, dict):
                    continue
                slug = _person_slug(application)
                application_id = _application_identifier(application)
                if slug is None:
                    continue

                key = (str(job_id), slug)
                group = grouped.setdefault(
                    key,
                    {
                    "type": "suspicious_application",
                    "match_type": "person_slug",
                    "job_id": job_id,
                        "job_title": job.get("JobPositionTitle"),
                        "person_slug": slug,
                        "candidate_name": (
                            application.get("Person", {}).get("FullName")
                            if isinstance(application.get("Person"), dict)
                            else None
                        ),
                        "applications_by_id": {},
                    },
                )
                # Some API responses contain an empty Application.ID. Use the
                # person slug only as an internal key in that case, while
                # keeping the displayed application ID unknown.
                application_key = (
                    str(application_id)
                    if application_id is not None
                    else f"person-slug:{slug}"
                )
                detail = group["applications_by_id"].setdefault(
                    application_key,
                    {
                        "application_id": application_id,
                        "created_at": next(
                            (
                                _application_field(application, field)
                                for field in (
                                    "ApplicationDate",
                                    "CreatedAt",
                                    "ApplicationCreatedAt",
                                )
                                if _application_field(application, field) is not None
                            ),
                            None,
                        ),
                        "steps": set(),
                    },
                )
                step_name = step.get("Name", "Unnamed step")
                detail["steps"].add(str(step_name))

                name_key = _person_name_key(application)
                if name_key is not None:
                    name_group = name_grouped.setdefault(
                        (str(job_id), name_key),
                        {
                            "job_id": job_id,
                            "job_title": job.get("JobPositionTitle"),
                            "person_name_key": name_key,
                            "candidate_name": (
                                application.get("Person", {}).get("FullName")
                                if isinstance(application.get("Person"), dict)
                                else None
                            ),
                            "applications_by_id": {},
                        },
                    )
                    name_detail = name_group["applications_by_id"].setdefault(
                        application_key,
                        {
                            "application_id": application_id,
                            "created_at": detail["created_at"],
                            "person_slug": _person_slug(application),
                            "steps": set(),
                        },
                    )
                    name_detail["steps"].add(str(step_name))

    anomalies = []
    for group in grouped.values():
        applications = list(group["applications_by_id"].values())
        if len(applications) < minimum_count:
            continue
        for application in applications:
            application["steps"] = sorted(application["steps"])
        anomalies.append(
            {
                **group,
                "applications": applications,
                "application_count": len(applications),
                "severity": "high" if len(applications) >= high_count else "medium",
                "recommendation": (
                    "Compare application IDs and timestamps, check the source or "
                    "external ATS integration, and mark records for manual review "
                    "or consolidation rather than deleting them automatically."
                ),
                "guiding_questions": [
                    "Did the candidate intentionally apply more than once?",
                    "Is an external ATS resubmitting applications?",
                    "Should duplicate records be manually consolidated?",
                ],
            }
        )

    slug_alert_keys = {
        (str(anomaly["job_id"]), anomaly.get("person_slug"))
        for anomaly in anomalies
        if anomaly.get("match_type") == "person_slug"
    }
    for group in name_grouped.values():
        applications = list(group["applications_by_id"].values())
        if len(applications) < minimum_count:
            continue
        person_slugs = {
            application.get("person_slug")
            for application in applications
            if application.get("person_slug")
        }
        # A same-slug duplicate is already covered by the stronger identity
        # check. The name layer is for different or unavailable person slugs.
        if len(person_slugs) == 1 and (
            str(group["job_id"]), next(iter(person_slugs))
        ) in slug_alert_keys:
            continue
        for application in applications:
            application["steps"] = sorted(application["steps"])
        anomalies.append(
            {
                "type": "suspicious_application",
                "match_type": "normalized_name",
                "job_id": group["job_id"],
                "job_title": group["job_title"],
                "candidate_name": group["candidate_name"],
                "person_name_key": group["person_name_key"],
                "applications": applications,
                "application_count": len(applications),
                "severity": "high" if len(applications) >= high_count else "medium",
                "recommendation": (
                    "This name match can be a false positive. Check PersonSlug, "
                    "application IDs, and timestamps in detail before deciding "
                    "whether these records represent the same person. Do not "
                    "delete records automatically."
                ),
                "guiding_questions": [
                    "Could these be two different people with the same name?",
                    "Do PersonSlug and application timestamps confirm the same person?",
                    "Should the records be manually reviewed before consolidation?",
                ],
            }
        )

    return anomalies


def _text(value: Any, fallback: str = "—") -> str:
    """Return a safely escaped display value for the HTML report."""

    if value is None or value == "":
        return fallback
    return escape(str(value))


def _date_only(value: Any) -> str:
    """Display an API timestamp as a calendar date without its time."""

    if not isinstance(value, str) or not value:
        return "—"
    return _text(value[:10])


def _application_display_name(application: dict[str, Any]) -> str:
    person = application.get("Person")
    if isinstance(person, dict):
        return _text(person.get("FullName"), "Unnamed candidate")
    return "Unnamed candidate"


def _render_applications(applications: list[dict[str, Any]]) -> str:
    if not applications:
        return '<span class="muted">No current applications</span>'

    application_rows = []
    for application in applications:
        application_data = application.get("Application")
        application_data = application_data if isinstance(application_data, dict) else {}
        application_rows.append(
            "<li>"
            f"<strong>{_application_display_name(application)}</strong>"
            f"<span>{_text(application_data.get('Source'), 'Unknown source')} · "
            f"{_text(application_data.get('ApplicationDate'), 'Unknown date')}</span>"
            "</li>"
        )

    return (
        '<details class="application-details">'
        f"<summary>View {len(applications)} application(s)</summary>"
        f"<ul>{''.join(application_rows)}</ul>"
        "</details>"
    )


def _render_agents(agents: list[dict[str, Any]]) -> str:
    if not agents:
        return '<span class="status neutral">No agent</span>'

    agent_items = []
    for agent in agents:
        instructions = agent.get("Instructions")
        instructions = instructions if isinstance(instructions, dict) else {}
        prompt = _text(instructions.get("SystemPrompt"), "No system prompt configured")
        agent_items.append(
            '<div class="agent">'
            f"<strong>{_text(agent.get('Name'), 'Unnamed agent')}</strong>"
            "<details>"
            "<summary>System prompt</summary>"
            f"<pre>{prompt}</pre>"
            "</details>"
            "</div>"
        )

    return '<span class="status positive">Agent configured</span>' + "".join(agent_items)


def _render_steps(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return '<p class="empty-state">No pipeline steps are configured for this job.</p>'

    rows = []
    for step in sorted(steps, key=lambda item: item.get("OrderIndex", 0)):
        hidden = bool(step.get("IsHidden"))
        applications = step.get("Applications", [])
        applications = applications if isinstance(applications, list) else []
        application_count = len(applications)
        count_class = "empty" if application_count == 0 else ""
        step_details = (
            '<details class="step-details">'
            "<summary>Step details</summary>"
            f"<p><strong>Status</strong> "
            f"<span class=\"status {'neutral' if hidden else 'positive'}\">"
            f"{'Hidden' if hidden else 'Active'}</span></p>"
            f"<p><strong>Agent configuration</strong> "
            f"{_render_agents(step.get('Agents', []))}</p>"
            "</details>"
        )
        rows.append(
            "<tr>"
            "<td>"
            f"<span class=\"step-number\">{_text(step.get('OrderIndex'), '?')}</span>"
            f"<strong>{_text(step.get('Name'), 'Unnamed step')}</strong>"
            f"{step_details}"
            "</td>"
            "<td>"
            f"<span class=\"application-count {count_class}\">{application_count}</span>"
            f"{_render_applications(applications)}"
            "</td>"
            "</tr>"
        )

    return (
        '<div class="table-wrap"><table>'
        "<thead><tr><th>Pipeline step</th><th>Applications</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_bottlenecks(bottlenecks: list[dict[str, Any]]) -> str:
    if not bottlenecks:
        return ""

    alerts = []
    for anomaly in bottlenecks:
        severity = anomaly["severity"]
        peer_pipeline_count = anomaly.get("peer_pipeline_count", 0)
        peer_average = anomaly.get("peer_average")
        if peer_average is None:
            peer_comparison = "No comparable step found in another pipeline."
        else:
            peer_comparison = (
                f"Compared with {peer_pipeline_count} other pipelines: "
                f"{peer_average:.1f} average applications"
            )
            peer_comparison += "."
        questions = "".join(
            "<li>"
            f"<strong>{_text(item.get('question'))}</strong> → "
            f"{_text(item.get('action'))}</li>"
            for item in anomaly.get("guiding_questions", [])
        )
        alerts.append(
            '<div class="anomaly">'
            f"<span class=\"status {'negative' if severity == 'high' else 'warning'}\">"
            f"{_text(severity).upper()}</span>"
            "<div>"
            '<strong class="anomaly-name">Step bottleneck</strong>'
            f"<strong class=\"anomaly-detail\">{_text(anomaly['step_name'])}</strong>"
            f"<p class=\"anomaly-evidence\">{anomaly['application_count']} applications</p>"
            f"<p class=\"anomaly-evidence\">{_text(peer_comparison)}</p>"
            f"<details class=\"guiding-question\"><summary>Guiding question:</summary><ul>{questions}</ul></details>"
            "</div></div>"
        )

    return '<div class="anomaly-list">' + "".join(alerts) + "</div>"


def _render_stuck_applications(anomalies: list[dict[str, Any]]) -> str:
    if not anomalies:
        return ""

    alerts = []
    for anomaly in anomalies:
        severity = anomaly["severity"]
        review_flags = []
        if anomaly.get("human_review"):
            review_flags.append("human review")
        if anomaly.get("agent_review"):
            review_flags.append("agent review")
        review_context = (
            f" · {', '.join(review_flags)} active" if review_flags else ""
        )
        alerts.append(
            '<div class="anomaly">'
            f"<span class=\"status {'negative' if severity == 'high' else 'warning'}\">"
            f"{_text(severity).upper()}</span>"
            "<div>"
            '<strong class="anomaly-name">Stuck applications</strong>'
            f"<strong class=\"anomaly-detail\">{_text(anomaly.get('candidate_name'), 'Unnamed candidate')} · "
            f"{_text(anomaly.get('step_name'), 'Unnamed step')}</strong>"
            f"<p class=\"anomaly-evidence\">"
            f"{anomaly['days_in_step']:.1f} days in current step{review_context}</p>"
            f"<small class=\"anomaly-evidence\">Assigned at {_text(anomaly.get('assigned_at'))}. "
            f"{_text(anomaly.get('recommendation'))}</small>"
            '<details class="guiding-question"><summary>Guiding question:</summary>'
            '<ul><li>Is someone expected to review this application manually?</li>'
            '<li>Is a decision missing or should the application be moved, rejected, or escalated?</li></ul></details>'
            "</div></div>"
        )

    return (
        '<div class="anomaly-list">'
        + "".join(alerts)
        + "</div>"
    )


def _render_agent_reviews(anomalies: list[dict[str, Any]]) -> str:
    if not anomalies:
        return ""

    alerts = []
    for anomaly in anomalies:
        severity = anomaly["severity"]
        agent_names = ", ".join(anomaly.get("agent_names", [])) or "Unnamed agent"
        prompt_status = "System prompt configured" if anomaly.get("has_system_prompt") else "System prompt missing"
        review_mode_labels = {
            "confirmed": "Confirmed agent backlog",
            "handoff": "Possible agent delay",
            "mixed": "Agent review / handoff",
        }
        review_mode_label = review_mode_labels.get(
            anomaly.get("review_mode"), "Agent review"
        )
        alerts.append(
            '<div class="anomaly">'
            f"<span class=\"status {'negative' if severity == 'high' else 'warning'}\">"
            f"{_text(severity).upper()}</span>"
            "<div>"
            '<strong class="anomaly-name">Agent review</strong>'
            f"<strong class=\"anomaly-detail\">{_text(review_mode_label)} · "
            f"{_text(anomaly.get('step_name'))}</strong>"
            f"<p class=\"anomaly-evidence\">{anomaly['application_count']} application(s) waiting · "
            f"Agent: {_text(agent_names)} · {_text(prompt_status)}</p>"
            f"<p class=\"anomaly-evidence\">Oldest waiting: {anomaly['oldest_waiting_hours']:.1f} hours</p>"
            f"<small class=\"anomaly-evidence\">{_text(anomaly.get('recommendation'))}</small>"
            f"<details class=\"guiding-question\"><summary>Guiding question:</summary>"
            f"<p>{_text(anomaly.get('guiding_question'))}</p></details>"
            "</div></div>"
        )

    return '<div class="anomaly-list">' + "".join(alerts) + "</div>"


def _render_suspicious_applications(anomalies: list[dict[str, Any]]) -> str:
    if not anomalies:
        return ""

    alerts = []
    for anomaly in anomalies:
        severity = anomaly["severity"]
        application_rows = "".join(
            "<li>"
            f"<strong>Application ID: "
            f"{_text(application.get('application_id'), 'unavailable')}</strong> · "
            f"PersonSlug: {_text(application.get('person_slug'), 'unavailable')} · "
            f"{_text(', '.join(application.get('steps', [])))}"
            f" · created {_text(application.get('created_at'))}"
            "</li>"
            for application in anomaly.get("applications", [])
        )
        guiding_questions = "".join(
            f"<li>{_text(question)}</li>"
            for question in anomaly.get("guiding_questions", [])
        )
        name_match_note = (
            "<p>Matched by normalized first name and last name; this can produce "
            "false positives for different people with the same name.</p>"
            if anomaly.get("match_type") == "normalized_name"
            else ""
        )
        alerts.append(
            '<div class="anomaly">'
            f"<span class=\"status {'negative' if severity == 'high' else 'warning'}\">"
            f"{_text(severity).upper()}</span>"
            "<div>"
            '<strong class="anomaly-name">Suspicious applications</strong>'
            f"<strong class=\"anomaly-detail\">"
            f"{_text(anomaly.get('candidate_name'), 'Unknown candidate')}</strong>"
            f"<p class=\"anomaly-evidence\">{anomaly['application_count']} distinct applications for this job</p>"
            f"{name_match_note}"
            f"<details><summary>Application evidence</summary><ul>{application_rows}</ul></details>"
            f"<details class=\"guiding-question\"><summary>Guiding question:</summary><ul>{guiding_questions}</ul></details>"
            f"<small class=\"anomaly-evidence\">{_text(anomaly.get('recommendation'))}</small>"
            "</div></div>"
        )

    return (
        '<div class="anomaly-list">'
        + "".join(alerts)
        + "</div>"
    )


def render_html_report(jobs: list[dict[str, Any]]) -> str:
    """Render the current job, pipeline, agent, and application data as HTML."""

    bottlenecks = detect_step_bottlenecks(jobs)
    stuck_applications = detect_stuck_applications(jobs)
    agent_reviews = detect_agent_reviews(jobs)
    suspicious_applications = detect_suspicious_applications(jobs)
    pipeline_ids = {
        job.get("PipelineTemplateID")
        for job in jobs
        if isinstance(job.get("PipelineTemplateID"), str)
    }
    steps = [
        step
        for job in jobs
        for step in job.get("PipelineSteps", [])
        if isinstance(step, dict)
    ]
    application_count = sum(
        step.get("ApplicationCount", 0)
        for step in steps
        if isinstance(step.get("ApplicationCount"), int)
    )
    bottleneck_application_count = sum(
        anomaly["application_count"] for anomaly in bottlenecks
    )
    stuck_application_count = len(stuck_applications)
    agent_review_application_count = sum(
        anomaly["application_count"] for anomaly in agent_reviews
    )
    suspicious_application_count = sum(
        anomaly["application_count"] for anomaly in suspicious_applications
    )

    def anomaly_metric_class(anomalies: list[dict[str, Any]]) -> str:
        if any(anomaly.get("severity") == "high" for anomaly in anomalies):
            return "metric negative"
        if anomalies:
            return "metric warning"
        return "metric"

    job_sections = []
    for job in jobs:
        pipeline_name = _text(job.get("PipelineTemplateName"), "No pipeline assigned")
        title = _text(job.get("JobPositionTitle"), "Untitled job")
        job_id = _text(job.get("PaulsjobJobID"), "Unknown ID")
        published = bool(job.get("Published"))
        expired = bool(job.get("Expired"))
        job_state = "Expired" if expired else "Published" if published else "Draft"
        state_class = "negative" if expired else "positive" if published else "neutral"
        job_id_value = job.get("PaulsjobJobID", job.get("JobPositionID", "unknown"))
        job_bottlenecks = [
            anomaly
            for anomaly in bottlenecks
            if str(anomaly["job_id"]) == str(job_id_value)
        ]
        job_stuck_applications = [
            anomaly
            for anomaly in stuck_applications
            if str(anomaly["job_id"]) == str(job_id_value)
        ]
        job_agent_reviews = [
            anomaly
            for anomaly in agent_reviews
            if str(anomaly["job_id"]) == str(job_id_value)
        ]
        job_suspicious_applications = [
            anomaly
            for anomaly in suspicious_applications
            if str(anomaly["job_id"]) == str(job_id_value)
        ]
        job_sections.append(
            '<section class="job-card">'
            '<div class="job-heading">'
            "<div>"
            f"<p class=\"eyebrow\">JOB {job_id}</p><h2>{title}</h2>"
            f"<p class=\"pipeline-name\">{pipeline_name}</p>"
            "</div>"
            f"<span class=\"status {state_class}\">{job_state}</span>"
            "</div>"
            '<dl class="job-meta">'
            f"<div><dt>Created</dt><dd>{_date_only(job.get('CreatedAt'))}</dd></div>"
            "</dl>"
            f"{_render_steps(job.get('PipelineSteps', []))}"
            f"{_render_bottlenecks(job_bottlenecks)}"
            f"{_render_stuck_applications(job_stuck_applications)}"
            f"{_render_agent_reviews(job_agent_reviews)}"
            f"{_render_suspicious_applications(job_suspicious_applications)}"
            "</section>"
        )

    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    empty_message = (
        '<section class="empty-state"><h2>No jobs found</h2>'
        "<p>The API returned no jobs for this company.</p></section>"
        if not job_sections
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PJRI Customer Health Check</title>
  <style>
    :root {{
      --ink: #17203a; --muted: #68718b; --line: #e6e9f2; --canvas: #f5f7fb;
      --card: #fff; --brand: #6254e7; --brand-soft: #eeecff; --good: #10705b;
      --good-soft: #e5f6ef; --warn: #8a5b11; --warn-soft: #fff4df; --bad: #b53a50;
      --bad-soft: #ffe9ee;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--canvas); color: var(--ink); font: 15px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .shell {{ max-width: 1280px; margin: 0 auto; padding: 48px 24px 72px; }}
    .hero {{ display: flex; justify-content: space-between; gap: 32px; align-items: end; margin-bottom: 28px; }}
    .eyebrow {{ margin: 0 0 8px; color: var(--brand); font-weight: 800; font-size: 12px; letter-spacing: .12em; }}
    h1 {{ color: var(--ink); font-size: clamp(32px, 5vw, 48px); line-height: 1.05; margin: 0; letter-spacing: -.04em; }}
    h2 {{ margin: 0; font-size: 21px; letter-spacing: -.02em; }}
    .generated {{ color: var(--muted); font-size: 13px; white-space: nowrap; }}
    .dashboard-group {{ margin-bottom: 28px; }} .dashboard-group > h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 28px; }}
    .metric, .job-card, .empty-state {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 10px 26px rgba(31, 41, 74, .05); }}
    .metric {{ padding: 20px; }} .metric.warning {{ background: var(--warn-soft); border-color: #f2d8a1; }} .metric.warning span, .metric.warning strong {{ color: var(--warn); }} .metric.negative {{ background: var(--bad-soft); border-color: #f0bdc8; }} .metric.negative span, .metric.negative strong {{ color: var(--bad); }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; font-size: 30px; margin-top: 4px; letter-spacing: -.04em; }}
    .job-card {{ padding: 28px; margin-top: 20px; }}
    .job-heading {{ display: flex; justify-content: space-between; align-items: start; gap: 16px; }}
    .pipeline-name {{ color: var(--brand); font-weight: 700; margin: 6px 0 0; }}
    .job-meta {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 22px 0; }}
    .job-meta div {{ background: #f8f9fd; padding: 12px; border-radius: 10px; min-width: 0; }}
    dt {{ color: var(--muted); font-size: 12px; }} dd {{ margin: 2px 0 0; overflow-wrap: anywhere; }}
    .status {{ display: inline-block; padding: 4px 9px; border-radius: 99px; font-size: 12px; font-weight: 800; white-space: nowrap; }}
    .status.positive {{ background: var(--good-soft); color: var(--good); }} .status.neutral {{ background: var(--brand-soft); color: #5044bc; }} .status.negative {{ background: var(--bad-soft); color: var(--bad); }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 500px; }} th, td {{ text-align: left; vertical-align: top; padding: 16px; border-bottom: 1px solid var(--line); }} tr:last-child td {{ border-bottom: 0; }} th {{ color: var(--muted); font-size: 12px; background: #fafbfe; }}
    td strong, td small {{ display: block; }} td small {{ color: var(--muted); margin-top: 2px; }} .step-number {{ display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: 8px; border-radius: 6px; background: var(--brand-soft); color: var(--brand); font-size: 12px; font-weight: 800; }}
    .agent + .agent {{ border-top: 1px solid var(--line); margin-top: 10px; padding-top: 10px; }} details {{ margin-top: 7px; }} summary {{ cursor: pointer; color: var(--brand); font-size: 13px; font-weight: 700; }} pre {{ margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; background: #111827; color: #e5e7eb; padding: 12px; border-radius: 8px; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .application-count {{ display: inline-grid; place-items: center; min-width: 28px; height: 28px; padding: 0 8px; border-radius: 99px; background: var(--brand); color: white; font-weight: 800; }} .application-count.empty {{ background: transparent; color: var(--muted); padding-left: 0; }} .application-details ul {{ padding-left: 18px; margin: 8px 0 0; }} .application-details li {{ margin: 6px 0; }} .application-details li span {{ display: block; color: var(--muted); font-size: 12px; }} .step-details {{ margin-top: 10px; }} .step-details p {{ margin: 8px 0; color: var(--muted); font-size: 13px; }} .step-details p strong {{ color: var(--ink); margin-right: 5px; }} .muted {{ color: var(--muted); font-size: 13px; }} .empty-state {{ padding: 32px; text-align: center; color: var(--muted); }}
    .anomaly-list {{ margin-top: 20px; border: 1px solid #f2d8a1; background: #fffaf0; border-radius: 12px; padding: 16px; }} .anomaly-list h3 {{ margin: 0 0 10px; font-size: 14px; color: var(--warn); }} .anomaly-note {{ color: var(--muted); font-size: 12px; margin: -4px 0 8px; }} .anomaly {{ display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid #f2e4c7; }} .anomaly:first-of-type {{ border-top: 0; }} .anomaly strong, .anomaly p, .anomaly small {{ display: block; }} .anomaly-name {{ color: var(--warn); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }} .anomaly-detail {{ color: var(--ink); font-size: 15px; margin-top: 2px; }} .anomaly p {{ margin: 4px 0; color: var(--muted); font-size: 13px; }} .anomaly small.anomaly-evidence {{ color: var(--muted); font-size: 12px; }} .guiding-question {{ margin-top: 10px; }} .guiding-question summary {{ display: inline-block; padding: 5px 9px; border-radius: 7px; background: var(--brand-soft); color: #5044bc; }} .guiding-question ul, .guiding-question p {{ margin: 8px 0 0; color: var(--muted); font-size: 13px; }} .status.warning {{ background: var(--warn-soft); color: var(--warn); }}
    @media (max-width: 720px) {{ .shell {{ padding: 28px 14px 48px; }} .hero {{ display: block; }} .generated {{ margin-top: 12px; }} .metrics, .job-meta {{ grid-template-columns: repeat(2, 1fr); }} .job-card {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">API Challenge · Technical Project Manager PJRI · KTB</p><h1>CUSTOMER HEALTH CHECK</h1></div>
      <p class="generated">Generated {generated_at}</p>
    </header>
    <section class="dashboard-group" aria-labelledby="pipeline-summary">
      <h2 id="pipeline-summary">Active pipelines</h2>
      <div class="metrics">
        <article class="metric"><span>Jobs</span><strong>{len(jobs)}</strong></article>
        <article class="metric"><span>Pipelines</span><strong>{len(pipeline_ids)}</strong></article>
        <article class="metric"><span>Applications</span><strong>{application_count}</strong></article>
      </div>
    </section>
    <section class="dashboard-group" aria-labelledby="anomaly-summary">
      <h2 id="anomaly-summary">Anomalies</h2>
      <div class="metrics">
        <article class="{anomaly_metric_class(bottlenecks)}"><span>Step bottlenecks</span><strong>{bottleneck_application_count}</strong></article>
        <article class="{anomaly_metric_class(stuck_applications)}"><span>Stuck applications</span><strong>{stuck_application_count}</strong></article>
        <article class="{anomaly_metric_class(agent_reviews)}"><span>Agent review backlog</span><strong>{agent_review_application_count}</strong></article>
        <article class="{anomaly_metric_class(suspicious_applications)}"><span>Suspicious applications</span><strong>{suspicious_application_count}</strong></article>
      </div>
    </section>
    {empty_message}
    {''.join(job_sections)}
  </main>
</body>
</html>"""


def write_html_report(jobs: list[dict[str, Any]], path: Path = REPORT_PATH) -> Path:
    """Write the static report to disk and return its location."""

    path.write_text(render_html_report(jobs), encoding="utf-8")
    return path


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

    report_path = write_html_report(jobs)
    print(f"Report created: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
