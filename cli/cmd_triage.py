"""``vrt triage`` subcommand: run the agent against a submission JSON.

Usage::

    # Print summary to stdout, write full record to file
    vrt triage submission.json --output record.json

    # Print summary only (no file output)
    vrt triage submission.json

    # Print full JSON to stdout (machine-readable, suitable for piping)
    vrt triage submission.json --json

    # Override the model
    vrt triage submission.json --model openai:gpt-4o

    # Refuse the call if estimated upper-bound cost exceeds budget.
    # --cost-budget requires --max-output-tokens to be specified.
    vrt triage submission.json --cost-budget 0.50 --max-output-tokens 8192

The submission JSON file must conform to the input contract
(``schemas/input-contract-1.0.0.schema.json``). The output, when
saved, conforms to the output contract.

Exit codes:

- ``0``: triage completed successfully
- ``1``: input validation failed (submission JSON malformed or
  missing required fields), or the agent raised an error, or the
  cost budget gate refused the call
- ``2``: setup error (file not found, model not configured, missing
  API key with no clear remediation, --cost-budget without
  --max-output-tokens)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


__all__ = ["add_arguments", "run"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``triage`` arguments."""
    parser.add_argument(
        "submission",
        type=Path,
        help="Path to the submission JSON file.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help=(
            "Optional path to write the full TriageRecord JSON. "
            "When omitted, only a human-readable summary is printed."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_only",
        help=(
            "Print the full TriageRecord JSON to stdout instead of "
            "the human-readable summary. Suitable for piping to jq."
        ),
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "PydanticAI model identifier. Defaults to the framework's "
            "DEFAULT_MODEL. Example: 'anthropic:claude-sonnet-4-5', "
            "'openai:gpt-4o'."
        ),
    )
    parser.add_argument(
        "--cost-budget",
        type=float,
        default=None,
        dest="cost_budget",
        metavar="DOLLARS",
        help=(
            "Maximum allowed cost for this LLM call in USD. Refuses "
            "the call if the upper-bound cost estimate (input tokens "
            "+ max output tokens at standard rates) exceeds the "
            "budget. Requires --max-output-tokens to be specified. "
            "Estimate uses a character-based heuristic (~4 chars per "
            "token) for input tokens and the published price table "
            "for dollar conversion."
        ),
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        dest="max_output_tokens",
        metavar="N",
        help=(
            "Maximum output tokens the LLM call can produce. Required "
            "when --cost-budget is set; ignored otherwise. The exact "
            "value depends on the configured PydanticAI model's "
            "max_tokens setting (typically 4096 or 8192)."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Run a triage decision and emit results."""
    from agent.agent import TriageAgent, TriageAgentConfig
    from cli.output import print_summary

    if not args.submission.exists():
        print(
            f"ERROR: submission file not found: {args.submission}",
            file=sys.stderr,
        )
        return 2

    try:
        submission = json.loads(args.submission.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: submission is not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 1

    if not isinstance(submission, dict):
        print(
            f"ERROR: submission must be a JSON object, got "
            f"{type(submission).__name__}",
            file=sys.stderr,
        )
        return 1

    # Validate budget-gate flag pairing before doing anything expensive.
    # The check itself runs after agent construction (so we have the
    # model resolved), but the flag-pairing errors should surface
    # immediately.
    if args.cost_budget is not None:
        if args.max_output_tokens is None:
            print(
                "ERROR: --cost-budget requires --max-output-tokens to "
                "be specified. Provide both flags or remove "
                "--cost-budget. The budget gate needs the max output "
                "token count to compute an upper bound on the LLM "
                "call's cost.",
                file=sys.stderr,
            )
            return 2
        if args.cost_budget < 0:
            print(
                f"ERROR: --cost-budget must be non-negative; "
                f"got {args.cost_budget}",
                file=sys.stderr,
            )
            return 2
        if args.max_output_tokens < 1:
            print(
                f"ERROR: --max-output-tokens must be at least 1; "
                f"got {args.max_output_tokens}",
                file=sys.stderr,
            )
            return 2

    # Build the agent. If the user supplied a real-LLM model and there's
    # no API key, surface a clear error rather than a stack trace.
    config_kwargs: dict[str, Any] = {}
    if args.model is not None:
        config_kwargs["model"] = args.model
        if not _has_api_key_for(args.model):
            provider = args.model.split(":", 1)[0] if ":" in args.model else args.model
            print(
                f"ERROR: no API key configured for provider '{provider}'. "
                f"Set the appropriate environment variable "
                f"(e.g., ANTHROPIC_API_KEY, OPENAI_API_KEY) and retry.",
                file=sys.stderr,
            )
            return 2

    try:
        agent = TriageAgent(TriageAgentConfig(**config_kwargs))
    except Exception as exc:
        print(
            f"ERROR: failed to construct agent: {exc}",
            file=sys.stderr,
        )
        return 2

    # Budget gate: now that we have the resolved model_id, estimate the
    # LLM call's upper-bound cost and refuse to proceed if it exceeds
    # the budget. The estimate uses a character-based heuristic for
    # input tokens and the user-supplied max_output_tokens; the gate
    # is conservative by design (overestimates rather than
    # underestimates).
    if args.cost_budget is not None:
        from agent.agent import _format_user_prompt
        from pricing import check_budget
        prompt_text = _format_user_prompt(submission, None, None)
        model_id = str(agent._config.model)
        result = check_budget(
            model_id=model_id,
            prompt=prompt_text,
            max_output_tokens=args.max_output_tokens,
            budget_usd=args.cost_budget,
        )
        if not result.allowed:
            print(
                f"ERROR: cost budget check failed.\n  {result.reason}",
                file=sys.stderr,
            )
            return 1

    start = time.time()
    try:
        record = agent.triage(submission)
    except Exception as exc:
        # The agent surfaces TriageInputError, ValidationError, or
        # PydanticAI runtime errors. We catch broadly and emit a
        # clear, single-line failure rather than a stack trace.
        print(f"ERROR: triage failed: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - start

    record_dict = record.model_dump(mode="json", exclude_none=True)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(record_dict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json_only:
        print(json.dumps(record_dict, indent=2, sort_keys=True))
    else:
        print_summary(record_dict, elapsed_seconds=elapsed)
        if args.output is not None:
            print(
                f"  Full record written to: {args.output}",
                file=sys.stdout,
            )
            print()

    return 0


def _has_api_key_for(model: str) -> bool:
    """Check whether the relevant API key is set for a provider-prefixed model.

    Best-effort: handles the common provider prefixes ('anthropic:',
    'openai:', 'google-gla:'). For non-string model identifiers (a
    Model instance), assume the caller configured credentials.
    """
    if not isinstance(model, str) or ":" not in model:
        return True
    provider = model.split(":", 1)[0]
    env_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google-gla": "GEMINI_API_KEY",
        "google-vertex": "GOOGLE_APPLICATION_CREDENTIALS",
    }
    env_var = env_var_map.get(provider)
    if env_var is None:
        return True  # Unknown provider; don't gate on credentials
    return bool(os.environ.get(env_var))
