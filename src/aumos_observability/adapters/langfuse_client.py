"""Langfuse LLM observability tracing adapter.

Wraps the Langfuse REST API using httpx.AsyncClient.
Provides trace, span, generation, and score creation for LLM call observability.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class LangfuseClient:
    """Async HTTP client for the Langfuse observability API.

    Creates traces, spans, and generation records for LLM calls.
    All methods use the Langfuse v1 REST ingestion API.
    Authentication uses Basic auth (public_key:secret_key).
    """

    def __init__(
        self,
        host: str,
        public_key: str,
        secret_key: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialise the Langfuse client.

        Args:
            host: Langfuse server base URL (e.g. http://langfuse:3000).
            public_key: Langfuse project public key.
            secret_key: Langfuse project secret key.
            timeout_seconds: Request timeout in seconds.
        """
        self._host = host.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._host,
            auth=(public_key, secret_key),
            headers={"Content-Type": "application/json"},
            timeout=timeout_seconds,
        )

    async def create_trace(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Create a new trace in Langfuse.

        A trace represents a single end-to-end LLM interaction or pipeline run.

        Args:
            name: Human-readable trace name.
            metadata: Arbitrary key-value metadata attached to the trace.
            user_id: End-user identifier for user-level filtering.
            session_id: Session identifier for grouping related traces.
            tags: List of string tags for filtering.

        Returns:
            The newly created trace ID (UUID string).
        """
        trace_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "batch": [
                {
                    "id": str(uuid.uuid4()),
                    "type": "trace-create",
                    "body": {
                        "id": trace_id,
                        "name": name,
                        "metadata": metadata or {},
                        "userId": user_id,
                        "sessionId": session_id,
                        "tags": tags or [],
                    },
                }
            ]
        }

        response = await self._client.post("/api/public/ingestion", json=payload)
        response.raise_for_status()
        logger.debug("Langfuse trace created", trace_id=trace_id, name=name)
        return trace_id

    async def create_span(
        self,
        trace_id: str,
        name: str,
        input: Any | None = None,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        parent_observation_id: str | None = None,
    ) -> str:
        """Create a span observation within a trace.

        A span represents a step within a larger pipeline (e.g. a retrieval call).

        Args:
            trace_id: Parent trace ID.
            name: Human-readable span name.
            input: Input data passed into this span.
            output: Output data produced by this span.
            metadata: Arbitrary key-value metadata.
            parent_observation_id: Parent span ID for nested spans.

        Returns:
            The newly created span observation ID (UUID string).
        """
        span_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "batch": [
                {
                    "id": str(uuid.uuid4()),
                    "type": "span-create",
                    "body": {
                        "id": span_id,
                        "traceId": trace_id,
                        "name": name,
                        "input": input,
                        "output": output,
                        "metadata": metadata or {},
                        "parentObservationId": parent_observation_id,
                    },
                }
            ]
        }

        response = await self._client.post("/api/public/ingestion", json=payload)
        response.raise_for_status()
        logger.debug("Langfuse span created", span_id=span_id, trace_id=trace_id)
        return span_id

    async def create_generation(
        self,
        trace_id: str,
        name: str,
        model: str,
        input: Any | None = None,
        output: Any | None = None,
        usage: dict[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_observation_id: str | None = None,
    ) -> str:
        """Create a generation observation representing an LLM call.

        Args:
            trace_id: Parent trace ID.
            name: Human-readable generation name (e.g. "completion" or "chat").
            model: Model identifier (e.g. "claude-opus-4-6", "gpt-4o").
            input: Prompt or messages sent to the model.
            output: Model response.
            usage: Token usage dict with keys: input, output, total.
            metadata: Arbitrary key-value metadata.
            parent_observation_id: Parent span ID if nested.

        Returns:
            The newly created generation observation ID (UUID string).
        """
        generation_id = str(uuid.uuid4())
        body: dict[str, Any] = {
            "id": generation_id,
            "traceId": trace_id,
            "name": name,
            "model": model,
            "input": input,
            "output": output,
            "metadata": metadata or {},
            "parentObservationId": parent_observation_id,
        }
        if usage is not None:
            body["usage"] = {
                "input": usage.get("input", 0),
                "output": usage.get("output", 0),
                "total": usage.get("total", 0),
            }

        payload: dict[str, Any] = {
            "batch": [
                {
                    "id": str(uuid.uuid4()),
                    "type": "generation-create",
                    "body": body,
                }
            ]
        }

        response = await self._client.post("/api/public/ingestion", json=payload)
        response.raise_for_status()
        logger.debug("Langfuse generation created", generation_id=generation_id, model=model)
        return generation_id

    async def score_trace(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
        observation_id: str | None = None,
    ) -> None:
        """Score a trace or observation for quality evaluation.

        Scores are used to track output quality over time and in evals.

        Args:
            trace_id: Trace to score.
            name: Score metric name (e.g. "relevance", "faithfulness").
            value: Numeric score value.
            comment: Optional free-text explanation of the score.
            observation_id: Optional observation (span/generation) to attach score to.
        """
        payload: dict[str, Any] = {
            "traceId": trace_id,
            "name": name,
            "value": value,
        }
        if comment is not None:
            payload["comment"] = comment
        if observation_id is not None:
            payload["observationId"] = observation_id

        response = await self._client.post("/api/public/scores", json=payload)
        response.raise_for_status()
        logger.debug("Langfuse trace scored", trace_id=trace_id, name=name, value=value)

    async def health_check(self) -> bool:
        """Check if Langfuse is reachable.

        Returns:
            True if the Langfuse health endpoint returns 200.
        """
        try:
            response = await self._client.get("/api/public/health")
            return response.status_code == 200
        except Exception:
            logger.warning("Langfuse health check failed", host=self._host)
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client connection pool."""
        await self._client.aclose()
