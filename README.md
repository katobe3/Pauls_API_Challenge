# PJRI Customer Health Check

An API-driven report that helps PJRI teams quickly assess the technical health of a customer account.

This project implements Option 1 of the PJRI API Challenge. It is designed to turn a customer’s jobs, pipelines, steps, agents, and applications into a concise report that makes configuration problems and candidate-flow anomalies easy to spot.

## Why this is useful

Customer health checks are often spread across several screens and require manual comparison. This tool brings the relevant operational signals into one report for technical project managers and customer-facing teams:

- Which jobs and pipelines are active?
- Are expected steps and agents configured?
- Where are applications accumulating?
- Are candidates stuck in a step beyond the configured threshold?
- Which jobs need investigation first?

## Planned report

The report will include:

- Customer and generation timestamp
- Jobs and their assigned pipelines
- Pipeline step configuration and agent status
- Application counts by step
- Stuck-candidate findings
- Missing or incomplete configuration warnings
- A summary health status: `healthy`, `needs_attention`, or `critical`

Example output:

```json
{
  "customer_id": "customer_123",
  "health": "needs_attention",
  "summary": {
    "jobs_checked": 4,
    "pipelines_checked": 4,
    "applications_checked": 186,
    "anomalies": 2
  },
  "anomalies": [
    {
      "type": "stuck_candidates",
      "job_id": "job_456",
      "step": "Phone screen",
      "count": 12,
      "threshold_days": 7
    }
  ]
}
```

## Status

The repository includes a small Python API client. It calls the jobs search endpoint, follows all result pages, enriches each job with its pipeline template name and step templates, and prints the combined job list. The customer health-check analysis can build on this client as the next step.

```text
.
├── README.md
├── .env.example
├── .gitignore
├── app.py
├── requirements.txt
└── tests/
    └── test_app.py
```

## Setup

1. Create a free account at [app.paulsjob.ai](https://app.paulsjob.ai/).
2. Generate a personal API key in the account settings.
3. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

4. Add the key to `.env`:

   ```dotenv
   PAULSJOB_API_KEY=your_api_key_here
   PAULSJOB_BASE_URL=https://api.paulsjob.ai/dev
   ```

5. Create and activate a virtual environment, then install the dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

6. Run the API smoke test:

   ```bash
   python app.py
   ```

   The combined job list is printed as formatted JSON. The client requests up to 100 jobs per page, follows `TotalPage` until every page has been collected, and looks up each unique pipeline using `GET /recruiting/job-step-templates/pipelines/{pipeline_template_id}` and `GET /recruiting/job-step-templates/pipelines/{pipeline_template_id}/steps`.

7. Run the tests without making a network request:

   ```bash
   python -m pytest
   ```

The API key must only be read from the environment. It must never be committed, printed in logs, or included in example output.

## API areas used

The implementation uses the Paul's Job API resources required to construct a customer health report:

| Resource | Purpose |
| --- | --- |
| Customers | Identify the account being checked and scope related data |
| Jobs | Fetch jobs belonging to the customer |
| Pipelines | Resolve the pipeline assigned to each job |
| Steps | Inspect ordering, names, and configuration |
| Agents | Check whether configured agents are present and active |
| Applications | Aggregate candidate counts by pipeline step and identify aging records |

The current client calls `POST /recruiting/jobs/search-jobs`. Authentication uses the `x-company-api-key` header with the company API key. The current smoke test sends an empty JSON object; add the request fields required by the jobs search schema in `app.py` once the filters are confirmed. The [Paul's Job API OpenAPI documentation](https://api.paulsjob.ai/dev/docs) is the source of truth for that schema.

## Health rules

The report should make its rules explicit and deterministic. The initial rules are:

- `critical`: a job has no pipeline, or a required pipeline step/agent is missing.
- `needs_attention`: candidates have remained in the same step longer than the configured threshold, or an API response is incomplete.
- `healthy`: no critical configuration issue or configured aging anomaly was found.

The stuck-candidate threshold should be configurable rather than hard-coded. A reasonable default is 7 days, with the report showing the threshold used for every finding.

## Error handling

The API client should:

- Fail fast when `PAULSJOB_API_KEY` is missing.
- Use request timeouts and bounded retries for transient `5xx` and rate-limit responses.
- Preserve the HTTP status and request context in actionable error messages.
- Handle pagination until all relevant records are fetched.
- Treat missing optional fields as unknown instead of silently converting them to healthy.
- Return a non-zero exit code when the report cannot be trusted.
- Redact authorization headers and API keys from logs.

Partial results should be clearly marked as partial; they should not be presented as a healthy account.

## Assumptions and limitations

- A customer is the reporting boundary; jobs and applications are evaluated only within that account.
- A candidate is considered stuck based on time since the latest step transition, not time since application creation.
- The initial version reports anomalies and does not modify jobs, pipelines, candidates, or agent configuration.
- Health thresholds may need to vary by customer, job type, or pipeline and should become configuration in a production version.
- The report depends on the API exposing enough timestamps and relationships to connect applications to pipeline steps.

## Example command

The intended CLI shape is:

```bash
python -m src.cli health-check --customer-id customer_123 --format json
```

Supported output formats should include JSON for automation and a human-readable table or HTML report for customer reviews.

## Testing approach

The client and health rules should be tested independently using mocked API responses. Important cases include:

- Multiple pages of jobs and applications
- Empty customers and jobs without pipelines
- Missing agents or steps
- Candidates over and under the stuck threshold
- Rate limits, timeouts, malformed responses, and server errors
- Redaction of API keys from errors and logs

## Next steps

1. Implement the typed API client from the OpenAPI schemas.
2. Add pagination and retry handling.
3. Implement the health rules as independently testable functions.
4. Add JSON and human-readable report renderers.
5. Add fixtures based on sanitized test data and document a real sample run.
6. Add structured logging and optional report persistence for recurring customer checks.

## Security

Never commit an API key. Keep `.env` in `.gitignore`, commit only `.env.example`, and check generated reports and screenshots for customer or credential data before sharing them.
