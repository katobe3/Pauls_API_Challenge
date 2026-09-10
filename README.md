# PJRI Customer Health Check

A Python reporting tool for assessing the operational health of a Paul's Job recruiting account. It retrieves jobs and their recruiting pipelines from the Paul's Job API, identifies candidate-flow and agent-review risks, and writes a self-contained HTML report.

 The dashboard summarises jobs, pipelines, applications, and four anomaly categories:

- **Step bottlenecks** — steps holding an unusually large share of a job's applications.
- **Stuck applications** — applications assigned to their current step for too long.
- **Agent-review backlog** — applications awaiting an agent decision at an agent-configured step.
- **Suspicious applications** — multiple distinct applications for the same candidate and job.

Alerts include severity, supporting evidence, and a suggested investigation or action. The generated report is branded **Customer Health Check** and is written to `report.html` in the repository root.

For every job returned by the API, the report shows its assigned pipeline, steps, configured agents and system prompts, and current applications at each step.

## Requirements

- Python 3.10 or later
- A Paul's Job company API key

## Setup

1. Create a virtual environment and install the dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

2. Create a local environment file:

   ```bash
   cp .env.example .env
   ```

3. Set the API key in `.env`:

   ```dotenv
   PAULSJOB_API_KEY=your_api_key_here
   PAULSJOB_BASE_URL=https://api.paulsjob.ai/dev
   ```

`PAULSJOB_BASE_URL` is optional and defaults to `https://api.paulsjob.ai/dev/v1`.

## Generate a report

```bash
python app.py
```

On success, the command prints the report location and creates `report.html`. Open that file in a browser to review the dashboard and job-level details.

## Detection rules

| Finding | Rule | Severity |
| --- | --- | --- |
| Step bottleneck | At least 2 applications in a step, and either at least 50% of the job's applications or at least 2× the average of the other steps. | High at 75% of applications or 4× the other-step average; otherwise medium. |
| Stuck application | An application has been assigned to its current step for at least 2 days. | High at 10 days, or when human or agent review is active; otherwise medium. |
| Agent-review backlog | A step has an agent, an application has no `PaulDecision`, is marked for agent review or handoff, and has waited at least 12 hours. | High at 24 hours or when at least 2 applications wait at the same step; otherwise medium. |
| Suspicious application | Two or more distinct application IDs belong to the same `PersonSlug` and job. A normalized first-name/last-name match is also reported as a possible duplicate. | High for 3 or more applications; otherwise medium. |

## API resources used

| Resource | Purpose |
| --- | --- |
| `POST /recruiting/jobs/search-jobs` | Retrieve every job. |
| `GET /recruiting/job-step-templates/pipelines/{pipeline_template_id}` | Resolve a pipeline name. |
| `GET /recruiting/job-step-templates/pipelines/{pipeline_template_id}/steps` | Retrieve pipeline steps. |
| `GET /recruiting/job-step-templates/pipelines/{pipeline_template_id}/steps/{step_template_id}/agents` | Retrieve configured agents and their system prompts. |
| `POST /recruiting/applications/search-applications` | Retrieve applications currently assigned to each job step. |

## Security and limitations

- Keep `PAULSJOB_API_KEY` only in your local `.env`; do not commit it or share generated reports containing customer data.
- Error messages deliberately omit authorization headers and API keys.
- “Stuck” time is calculated from `AssignedAt`. The API does not provide full transition history, so an application returned under a step is treated as currently in that step.
- Name-based duplicate matches can be false positives and are explicitly labelled as possible duplicates. No data is deleted or consolidated automatically.