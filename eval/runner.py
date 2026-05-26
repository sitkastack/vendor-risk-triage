"""Evaluation runner.

Takes a TriageAgent and a Dataset; produces an EvalReport. Per-example
errors are caught and recorded as failures rather than aborting the run,
so a single bad example cannot mask the agent's behaviour on the rest.

The runner does not depend on the agent's concrete class; it requires
only the ``triage(submission, decision_id=...)`` interface that
``agent.agent.TriageAgent`` provides. This lets future work substitute
mock or wrapper agents without touching the runner.

Concurrency: MVP runner is sequential, single-threaded. Concurrent
execution is tagged for follow-up work; sequential is correct for the
8-example baseline dataset and any near-term suites under ~100 examples.

Deferred:

- [deferred-subsystem-3-followup] Concurrent example execution
  (asyncio.gather over the agent's async path; meaningful at suite sizes
  beyond ~50 examples or when LLM call latency dominates)
- [deferred-subsystem-3-followup] Progress reporting (callback hook or
  generator interface for long suites)
- [deferred-phase-4] Multiple-run aggregation (the same dataset run N
  times to measure variance; foundation for calibration)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent.output_models import TriageRecord
from eval.dataset import Dataset
from eval.metrics import AggregateMetrics, ExampleResult, compute_metrics


__all__ = [
    "EvalReport",
    "TriageEvalRunner",
    "AgentProtocol",
]


class AgentProtocol(Protocol):
    """Structural interface the runner requires of an agent.

    Any object providing ``triage(submission, decision_id) -> TriageRecord``
    and an ``agent_version`` string property satisfies the protocol.
    ``agent.agent.TriageAgent`` is the canonical implementation; tests
    substitute lighter doubles that conform to the same shape.
    """

    @property
    def agent_version(self) -> str:
        ...  # pragma: no cover - protocol declaration

    def triage(
        self, submission: dict[str, Any], decision_id: Optional[str] = None
    ) -> TriageRecord:
        ...  # pragma: no cover - protocol declaration


class EvalReport(BaseModel):
    """The complete output of a single eval run.

    Captures everything an auditor needs to reconstruct the run:
    when it ran, what agent produced the results, what dataset they
    were graded against, every per-example result, and the aggregates.

    Two reports are comparable when they share the same dataset_name
    AND dataset_content_hash. Comparing reports across datasets is
    meaningless (different question being asked).

    Attributes:
        run_timestamp: When the runner began iterating. UTC-aware.
        agent_version: The agent's ``agent_version`` string at the time
            of the run. Encodes provider, model, prompt hash.
        dataset_name: The dataset's name (typically the filename stem).
        dataset_content_hash: First 16 hex chars of SHA-256 over the
            dataset's canonical contents. Reports with the same dataset
            name but different hash were run on different versions.
        results: One ExampleResult per dataset example, in dataset order.
        metrics: The aggregate metrics computed from results.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_timestamp: datetime
    agent_version: str = Field(min_length=1, max_length=128)
    dataset_name: str = Field(min_length=1, max_length=128)
    dataset_content_hash: str = Field(pattern=r"^[0-9a-f]{16}$")
    results: list[ExampleResult]
    metrics: AggregateMetrics


class TriageEvalRunner:
    """Runs an agent against a dataset and produces an EvalReport.

    Usage::

        runner = TriageEvalRunner(agent)
        report = runner.run(dataset)
        print(f"Tier agreement: {report.metrics.tier_agreement_rate:.0%}")

    The runner is stateless across runs; constructing one and running
    multiple datasets is fine. The agent's ``agent_version`` is read at
    each run, not at construction, so swapping agents on the same runner
    instance is also fine.
    """

    def __init__(self, agent: AgentProtocol) -> None:
        """Construct a runner bound to an agent.

        Args:
            agent: Anything satisfying AgentProtocol. The canonical case
                is an ``agent.agent.TriageAgent``; tests pass FunctionModel-
                backed agents or hand-rolled stubs.
        """
        self._agent: AgentProtocol = agent

    def run(self, dataset: Dataset) -> EvalReport:
        """Run the agent against every example in the dataset.

        Iterates through ``dataset.examples`` in order. Each example is
        triaged independently; an exception on one example is recorded
        and the run continues. The eval is over when every example has
        either a record or an error.

        Idempotency:

        Running the same dataset against the same agent twice produces
        two reports with the same ``dataset_content_hash`` and
        ``agent_version`` but different ``run_timestamp`` and different
        per-example ``decision_id`` values. The aggregate metrics may
        differ if the underlying agent is non-deterministic (real LLM
        calls); deterministic agents (FunctionModel-backed) produce
        identical metrics on repeat runs. Comparing two reports for
        audit purposes is meaningful when their dataset_content_hash
        and agent_version match.

        Args:
            dataset: A loaded Dataset.

        Returns:
            An EvalReport containing per-example results and aggregates.
        """
        run_timestamp = datetime.now(timezone.utc)
        results: list[ExampleResult] = []

        for example in dataset.examples:
            decision_id = f"d-eval-{dataset.name}-{example.id}"
            try:
                record = self._agent.triage(
                    example.submission, decision_id=decision_id
                )
                results.append(
                    ExampleResult(
                        example_id=example.id,
                        expected_tier=example.expected_tier,
                        expected_disposition=example.expected_disposition,
                        record=record,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - intentional broad capture
                # Per-example isolation: record the failure and continue.
                # The error_type and error_message let an auditor see
                # which examples failed and why without losing the rest
                # of the run.
                results.append(
                    ExampleResult(
                        example_id=example.id,
                        expected_tier=example.expected_tier,
                        expected_disposition=example.expected_disposition,
                        record=None,
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:4000],
                    )
                )

        metrics = compute_metrics(results)
        return EvalReport(
            run_timestamp=run_timestamp,
            agent_version=self._agent.agent_version,
            dataset_name=dataset.name,
            dataset_content_hash=dataset.content_hash,
            results=results,
            metrics=metrics,
        )
