"""Batch client abstraction over the Anthropic Message Batches API.

A thin ``BatchClient`` Protocol decouples the pipeline from the SDK, so stages
are testable offline with a fake client. ``AnthropicBatchClient`` is the real
adapter; it builds structured-output requests (``output_config.format``) with a
cached system prefix, and submits/polls/retrieves via the Batches API.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from wgtracker.llm.cost import Usage
from wgtracker.llm.prompts import SystemBlocks


@dataclass
class BatchRequest:
    custom_id: str
    model: str
    system: SystemBlocks
    user_content: str
    schema: dict[str, object]
    max_tokens: int = 2048
    effort: str | None = None
    thinking_disabled: bool = True


@dataclass
class BatchResultItem:
    custom_id: str
    status: str  # "succeeded" | "errored" | "canceled" | "expired"
    text: str | None = None
    usage: Usage = field(default_factory=Usage)
    error: str | None = None


class BatchClient(Protocol):
    def submit(self, requests: list[BatchRequest]) -> str: ...
    def status(self, batch_id: str) -> str: ...  # "ended" once complete
    def results(self, batch_id: str) -> Iterator[BatchResultItem]: ...


def _build_params(req: BatchRequest) -> dict[str, Any]:
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": req.schema}}
    if req.effort:
        output_config["effort"] = req.effort
    params: dict[str, Any] = {
        "model": req.model,
        "max_tokens": req.max_tokens,
        "system": req.system,
        "messages": [{"role": "user", "content": req.user_content}],
        "output_config": output_config,
    }
    if req.thinking_disabled:
        params["thinking"] = {"type": "disabled"}
    return params


class AnthropicBatchClient:
    """Real adapter over ``anthropic`` (imported lazily so tests need no SDK)."""

    def __init__(self, api_key: str | None = None) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def submit(self, requests: list[BatchRequest]) -> str:
        from anthropic.types.messages.batch_create_params import Request

        batch = self._client.messages.batches.create(
            requests=[
                Request(custom_id=r.custom_id, params=_build_params(r))  # type: ignore[typeddict-item]
                for r in requests
            ]
        )
        return str(batch.id)

    def status(self, batch_id: str) -> str:
        return str(self._client.messages.batches.retrieve(batch_id).processing_status)

    def results(self, batch_id: str) -> Iterator[BatchResultItem]:
        for r in self._client.messages.batches.results(batch_id):
            result = r.result
            if result.type == "succeeded":
                msg = result.message
                text = next((b.text for b in msg.content if b.type == "text"), None)
                u = msg.usage
                yield BatchResultItem(
                    custom_id=r.custom_id,
                    status="succeeded",
                    text=text,
                    usage=Usage(
                        input_tokens=getattr(u, "input_tokens", 0) or 0,
                        output_tokens=getattr(u, "output_tokens", 0) or 0,
                        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0)
                        or 0,
                        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                    ),
                )
            else:
                error = None
                if result.type == "errored":
                    error = str(getattr(result.error, "type", "error"))
                yield BatchResultItem(custom_id=r.custom_id, status=result.type, error=error)
