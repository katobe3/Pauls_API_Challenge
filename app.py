"""Generate a static Customer Health Check report from the Paul's Job API."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.paulsjob.ai/dev"
ENDPOINT = "/recruiting/jobs/search-jobs"
PIPELINE_TEMPLATE_ENDPOINT = "/recruiting/job-step-templates/pipelines"
APPLICATION_ENDPOINT = "/recruiting/applications/search-applications"
REPORT_PATH = Path("report.html")
BOTTLENECK_MIN_APPLICATIONS = 1
BOTTLENECK_MIN_SHARE = 0.50
BOTTLENECK_MIN_RATIO = 2.0


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

            bottlenecks.append(
                {
                    "type": "step_bottleneck",
                    "severity": "high" if share >= 0.75 or ratio >= 4 else "medium",
                    "job_id": job_id,
                    "job_title": job.get("JobPositionTitle"),
                    "step_id": step.get("ID"),
                    "step_name": step.get("Name", "Unnamed step"),
                    "application_count": count,
                    "total_applications": total_applications,
                    "share": share,
                    "comparison_average": comparison_average,
                    "ratio": ratio,
                    "recommendation": (
                        "Review this step for manual-workload, automation, or "
                        "next-step transition issues."
                    ),
                }
            )

    return bottlenecks


def _text(value: Any, fallback: str = "—") -> str:
    """Return a safely escaped display value for the HTML report."""

    if value is None or value == "":
        return fallback
    return escape(str(value))


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
        rows.append(
            "<tr>"
            "<td>"
            f"<span class=\"step-number\">{_text(step.get('OrderIndex'), '?')}</span>"
            f"<strong>{_text(step.get('Name'), 'Unnamed step')}</strong>"
            f"<small>{_text(step.get('Category'), 'No category')}</small>"
            "</td>"
            f"<td><span class=\"status {'neutral' if hidden else 'positive'}\">"
            f"{'Hidden' if hidden else 'Active'}</span></td>"
            f"<td>{_render_agents(step.get('Agents', []))}</td>"
            "<td>"
            f"<span class=\"application-count\">{len(applications)}</span>"
            f"{_render_applications(applications)}"
            "</td>"
            "</tr>"
        )

    return (
        '<div class="table-wrap"><table>'
        "<thead><tr><th>Pipeline step</th><th>Status</th>"
        "<th>Agent configuration</th><th>Applications</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_bottlenecks(bottlenecks: list[dict[str, Any]]) -> str:
    if not bottlenecks:
        return ""

    alerts = []
    for anomaly in bottlenecks:
        severity = anomaly["severity"]
        alerts.append(
            '<div class="anomaly">'
            f"<span class=\"status {'negative' if severity == 'high' else 'warning'}\">"
            f"{_text(severity).upper()}</span>"
            "<div>"
            f"<strong>Step bottleneck · {_text(anomaly['step_name'])}</strong>"
            f"<p>{anomaly['application_count']} applications · "
            f"{anomaly['share']:.0%} of this job · "
            f"{anomaly['ratio']:.1f}× the average of other steps</p>"
            f"<small>{_text(anomaly['recommendation'])}</small>"
            "</div></div>"
        )

    return '<div class="anomaly-list"><h3>Attention needed</h3>' + "".join(alerts) + "</div>"


def render_html_report(jobs: list[dict[str, Any]]) -> str:
    """Render the current job, pipeline, agent, and application data as HTML."""

    bottlenecks = detect_step_bottlenecks(jobs)
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
            f"<div><dt>Location</dt><dd>{_text(job.get('Location'))}</dd></div>"
            f"<div><dt>Created</dt><dd>{_text(job.get('CreatedAt'))}</dd></div>"
            f"<div><dt>Pipeline ID</dt><dd>{_text(job.get('PipelineTemplateID'))}</dd></div>"
            "</dl>"
            f"{_render_steps(job.get('PipelineSteps', []))}"
            f"{_render_bottlenecks(job_bottlenecks)}"
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
    h1 {{ font-size: clamp(32px, 5vw, 48px); line-height: 1.05; margin: 0; letter-spacing: -.04em; }}
    h2 {{ margin: 0; font-size: 21px; letter-spacing: -.02em; }}
    .generated {{ color: var(--muted); font-size: 13px; white-space: nowrap; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 16px; margin-bottom: 28px; }}
    .metric, .job-card, .empty-state {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 10px 26px rgba(31, 41, 74, .05); }}
    .metric {{ padding: 20px; }}
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
    table {{ border-collapse: collapse; width: 100%; min-width: 760px; }} th, td {{ text-align: left; vertical-align: top; padding: 16px; border-bottom: 1px solid var(--line); }} tr:last-child td {{ border-bottom: 0; }} th {{ color: var(--muted); font-size: 12px; background: #fafbfe; }}
    td strong, td small {{ display: block; }} td small {{ color: var(--muted); margin-top: 2px; }} .step-number {{ display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: 8px; border-radius: 6px; background: var(--brand-soft); color: var(--brand); font-size: 12px; font-weight: 800; }}
    .agent + .agent {{ border-top: 1px solid var(--line); margin-top: 10px; padding-top: 10px; }} details {{ margin-top: 7px; }} summary {{ cursor: pointer; color: var(--brand); font-size: 13px; font-weight: 700; }} pre {{ margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; background: #111827; color: #e5e7eb; padding: 12px; border-radius: 8px; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .application-count {{ display: inline-grid; place-items: center; min-width: 28px; height: 28px; padding: 0 8px; border-radius: 99px; background: var(--brand); color: white; font-weight: 800; }} .application-details ul {{ padding-left: 18px; margin: 8px 0 0; }} .application-details li {{ margin: 6px 0; }} .application-details li span {{ display: block; color: var(--muted); font-size: 12px; }} .muted {{ color: var(--muted); font-size: 13px; }} .empty-state {{ padding: 32px; text-align: center; color: var(--muted); }}
    .anomaly-list {{ margin-top: 20px; border: 1px solid #f2d8a1; background: #fffaf0; border-radius: 12px; padding: 16px; }} .anomaly-list h3 {{ margin: 0 0 10px; font-size: 14px; color: var(--warn); }} .anomaly {{ display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid #f2e4c7; }} .anomaly:first-of-type {{ border-top: 0; }} .anomaly strong, .anomaly p, .anomaly small {{ display: block; }} .anomaly p {{ margin: 2px 0; color: var(--muted); font-size: 13px; }} .anomaly small {{ color: var(--warn); }} .status.warning {{ background: var(--warn-soft); color: var(--warn); }}
    @media (max-width: 720px) {{ .shell {{ padding: 28px 14px 48px; }} .hero {{ display: block; }} .generated {{ margin-top: 12px; }} .metrics, .job-meta {{ grid-template-columns: repeat(2, 1fr); }} .job-card {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">PJRI · CUSTOMER HEALTH CHECK</p><h1>Recruiting pipeline overview</h1></div>
      <p class="generated">Generated {generated_at}</p>
    </header>
    <section class="metrics" aria-label="Report summary">
      <article class="metric"><span>Jobs</span><strong>{len(jobs)}</strong></article>
      <article class="metric"><span>Pipelines</span><strong>{len(pipeline_ids)}</strong></article>
      <article class="metric"><span>Pipeline steps</span><strong>{len(steps)}</strong></article>
      <article class="metric"><span>Current applications</span><strong>{application_count}</strong></article>
      <article class="metric"><span>Step bottlenecks</span><strong>{len(bottlenecks)}</strong></article>
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
