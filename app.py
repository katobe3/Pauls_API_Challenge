"""Call the Paul's Job person-list endpoint and print its response."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.paulsjob.ai/dev"
ENDPOINT = "/company/person/list"


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


def fetch_people(
    *,
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
    timeout: float = 20.0,
) -> Any:
    """POST to the person-list endpoint and return the decoded JSON response."""

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


def main() -> int:
    try:
        api_key, base_url = load_config()
        result = fetch_people(
            api_key=api_key,
            base_url=base_url,
            payload={},
        )
    except ApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Error: could not reach the Paul's Job API: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
