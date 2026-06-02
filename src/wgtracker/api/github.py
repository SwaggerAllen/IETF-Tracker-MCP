"""Trigger the pipeline GitHub Actions workflow (UI re-trigger buttons)."""

from __future__ import annotations

import httpx

from wgtracker.settings import Settings

_WORKFLOW = "pipeline.yml"
VALID_STAGES = {"ingest", "poll", "recategorize"}


def dispatch_pipeline(settings: Settings, stage: str, *, ref: str = "main") -> tuple[int, str]:
    """workflow_dispatch the pipeline workflow with the given stage input."""
    if stage not in VALID_STAGES:
        return 400, f"Unknown stage '{stage}'. Valid: {sorted(VALID_STAGES)}"
    if not settings.github_dispatch_token or not settings.github_repo:
        return 503, "GITHUB_DISPATCH_TOKEN/GITHUB_REPO not configured."
    url = (
        f"https://api.github.com/repos/{settings.github_repo}"
        f"/actions/workflows/{_WORKFLOW}/dispatches"
    )
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.github_dispatch_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": ref, "inputs": {"stage": stage}},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        return 502, f"Dispatch request failed: {exc}"
    if resp.status_code == 204:
        return 202, f"Dispatched pipeline stage '{stage}'."
    return resp.status_code, resp.text[:500]
