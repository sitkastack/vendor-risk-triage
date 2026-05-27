"""Audit log shipping adapter.

Wraps a TriageRecord in an envelope suitable for shipping to a SIEM,
archive, event bus, or compliance pipeline. The framework's
TriageRecord is already audit-quality; this module adds the
operational metadata a downstream pipeline needs (content hash,
sequence number, routing key, ingestion-friendly timestamps) without
modifying the underlying record.

Design principles:

1. **Additive only**. The envelope wraps the TriageRecord; the
   record itself is unchanged. A downstream consumer that knows about
   TriageRecord but not about the envelope can unwrap the
   ``record`` field and get exactly what the framework produced.

2. **Content-addressed integrity**. Every envelope carries a SHA-256
   hash of the embedded TriageRecord's canonical JSON. A receiver
   recomputes the hash on the unwrapped record and verifies. Hash
   mismatch surfaces tampering, corruption, or version drift.

3. **Stable wire format**. The envelope shape is the framework's
   contract with downstream consumers. The schema version
   (``envelope_schema_version``) is bumped on any breaking change.
   Today the version is ``1.0.0``.

4. **Multi-consumer**. The envelope is flat enough to work as a SIEM
   event (one line of JSON), an archive object (one file per
   envelope), or an event-bus message (one envelope per topic
   message). Specific consumer adapters live downstream of this
   module.

Usage::

    from reporting.audit_log import AuditLogEnvelope, build_envelope

    envelope = build_envelope(
        record=triage_record,
        sequence_number=42,
        deployment_id="acme-prod",
    )
    line = envelope.to_jsonl_line()
    # Ship `line` via your SIEM HEC, S3 PutObject, Kafka producer, etc.

The module also provides ``parse_jsonl_line()`` for receiver-side
unwrapping with hash verification.

Deferred:

- ``[deferred-phase-6]`` Batch-shipping helper (wrapping N envelopes
  in one HTTP POST for SIEM throughput optimization)
- ``[deferred-phase-6]`` Encryption-at-rest adapter (envelope-level
  AES-GCM for archives where transport encryption is insufficient)
- ``[deferred-phase-7]`` Cross-envelope chained-hash for full-chain
  forensic verification (each envelope's hash includes the prior
  envelope's hash; tampering with one breaks the chain)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.output_models import TriageRecord


__all__ = [
    "AuditLogEnvelope",
    "AuditLogParseError",
    "ENVELOPE_SCHEMA_VERSION",
    "build_envelope",
    "parse_jsonl_line",
]


ENVELOPE_SCHEMA_VERSION: str = "1.0.0"
"""Envelope wire format schema version.

Bumped on any breaking change to the envelope's fields, the hash
algorithm, or the canonical JSON serialization rules. Consumers
should check the major version and refuse to process envelopes
they don't understand.
"""


class AuditLogParseError(Exception):
    """Raised when an envelope JSONL line cannot be parsed or verified.

    Causes:

    - The line is not valid JSON
    - The line is JSON but does not match the envelope schema
    - The envelope schema version is incompatible with this consumer
    - The embedded record's SHA-256 disagrees with the envelope's
      ``record_content_hash`` (corruption or tampering)
    """


class AuditLogEnvelope(BaseModel):
    """Operational wrapper around a TriageRecord, suitable for shipping.

    The envelope adds metadata a downstream pipeline needs that the
    framework's TriageRecord does not carry: content hash for integrity,
    sequence number for ordering, deployment_id for multi-tenant
    routing, shipped_at for ingestion-time queries.

    Attributes:
        envelope_schema_version: The wire format schema version
            (currently ``1.0.0``). Receivers check the major version.
        record_content_hash: SHA-256 of the TriageRecord's canonical
            JSON serialization, formatted ``sha256:<hex>``. Receivers
            recompute and verify on parse.
        record: The full TriageRecord being shipped. The audit-quality
            payload.
        sequence_number: Monotonically increasing integer assigned by
            the deploying organization. Used to detect dropped or
            reordered messages on the receiver side. The framework
            does not assign sequence numbers; the deploying
            organization's shipping pipeline does (typically from a
            Redis INCR, a Kafka partition offset, or a database
            sequence).
        deployment_id: Stable identifier for the deploying
            organization's environment. Used for multi-tenant SIEM
            routing and for partitioning archive prefixes. Format is
            up to the deploying organization; recommended pattern is
            ``{org-slug}-{environment}`` (e.g., ``acme-prod``,
            ``acme-staging``, ``contoso-dr``).
        shipped_at: ISO 8601 timestamp recording when this envelope
            was constructed for shipping. Distinct from
            ``record.decision_timestamp``, which records when the
            agent produced the decision. The two timestamps can
            differ when records are re-shipped, replayed, or
            buffered through a downstream queue.
        replay_of: Optional reference to an earlier envelope this
            shipment replays. None for normal first-time shipments.
            When set, the value is the prior envelope's
            ``decision_id + sequence_number`` concatenation, so a
            receiver can identify the replay relationship.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_schema_version: str = Field(min_length=1, max_length=32)
    record_content_hash: str = Field(
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    record: TriageRecord
    sequence_number: int = Field(ge=0)
    deployment_id: str = Field(min_length=1, max_length=128)
    shipped_at: datetime
    replay_of: Optional[str] = Field(
        default=None, min_length=1, max_length=256,
    )

    @field_validator("shipped_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        """Reject naive datetimes. Audit timestamps require timezone info."""
        if value.tzinfo is None:
            raise ValueError(
                "shipped_at must be timezone-aware (RFC 3339)"
            )
        return value

    def to_jsonl_line(self) -> str:
        """Serialize the envelope as a single JSON line.

        The output is a string ending in a single ``\\n`` newline,
        suitable for appending to a JSONL file, posting to a SIEM HEC
        endpoint, or sending as a Kafka producer record value.

        Internal field ordering is stable (sorted keys) so two
        envelopes with identical inputs produce byte-identical output,
        which simplifies replay-detection on the receiver side.
        """
        payload = self.model_dump(mode="json", exclude_none=True)
        return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the envelope as a dict for non-line transports.

        Some transports (event buses with structured payloads, archive
        formats like Parquet) prefer a dict over a JSON string. The
        dict is the same shape as ``to_jsonl_line()`` parsed back to
        Python.
        """
        return self.model_dump(mode="json", exclude_none=True)


def build_envelope(
    record: TriageRecord,
    sequence_number: int,
    deployment_id: str,
    shipped_at: Optional[datetime] = None,
    replay_of: Optional[str] = None,
) -> AuditLogEnvelope:
    """Build an envelope around a TriageRecord, computing the content hash.

    The envelope's ``record_content_hash`` is the SHA-256 of the
    record's canonical JSON serialization (sorted keys, no
    extraneous whitespace). Receivers recompute and verify on parse.

    Args:
        record: The TriageRecord to ship.
        sequence_number: Monotonically increasing integer from the
            deploying organization's shipping pipeline. Used to
            detect drops or reordering.
        deployment_id: Stable deployment identifier
            (e.g., ``acme-prod``). Used for multi-tenant routing.
        shipped_at: Optional explicit shipping timestamp. Defaults to
            the current UTC time. Tests can pass a fixed value for
            determinism; production callers usually omit this.
        replay_of: Optional reference to an earlier envelope being
            replayed. None for normal shipments. When set, format
            is ``{decision_id}:{sequence_number}`` of the prior
            envelope.

    Returns:
        A new AuditLogEnvelope ready for transport.
    """
    record_hash = "sha256:" + hashlib.sha256(
        _record_canonical_bytes(record)
    ).hexdigest()
    return AuditLogEnvelope(
        envelope_schema_version=ENVELOPE_SCHEMA_VERSION,
        record_content_hash=record_hash,
        record=record,
        sequence_number=sequence_number,
        deployment_id=deployment_id,
        shipped_at=shipped_at if shipped_at is not None else datetime.now(timezone.utc),
        replay_of=replay_of,
    )


def parse_jsonl_line(
    line: str,
    verify_hash: bool = True,
) -> AuditLogEnvelope:
    """Parse a JSONL envelope line, optionally verifying the content hash.

    Args:
        line: A single JSONL line as produced by
            ``AuditLogEnvelope.to_jsonl_line()``. Trailing newline is
            tolerated.
        verify_hash: When True (default), recompute the embedded
            TriageRecord's SHA-256 and compare to the envelope's
            ``record_content_hash``. Mismatch raises AuditLogParseError.
            Set False only when the caller has a separate integrity
            mechanism (signed transport, encrypted-at-rest store with
            its own integrity guarantees).

    Returns:
        The parsed AuditLogEnvelope.

    Raises:
        AuditLogParseError: For any failure category listed on the
            exception class.
    """
    try:
        payload = json.loads(line.rstrip("\n"))
    except json.JSONDecodeError as exc:
        raise AuditLogParseError(
            f"Envelope line is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise AuditLogParseError(
            f"Envelope must be a JSON object; got {type(payload).__name__}"
        )

    # Major-version compatibility check before attempting full parse.
    version = payload.get("envelope_schema_version", "")
    try:
        bundle_major = int(version.split(".")[0])
    except (ValueError, AttributeError, IndexError):
        raise AuditLogParseError(
            f"Envelope schema version is missing or malformed: "
            f"{version!r}"
        )
    current_major = int(ENVELOPE_SCHEMA_VERSION.split(".")[0])
    if bundle_major != current_major:
        raise AuditLogParseError(
            f"Envelope schema version {version} is incompatible "
            f"with this consumer (expects v{current_major}.x.x). "
            f"Upgrade the consumer or downgrade the producer."
        )

    try:
        envelope = AuditLogEnvelope(**payload)
    except Exception as exc:
        raise AuditLogParseError(
            f"Envelope does not match schema: {exc}"
        ) from exc

    if verify_hash:
        actual_hash = "sha256:" + hashlib.sha256(
            _record_canonical_bytes(envelope.record)
        ).hexdigest()
        if actual_hash != envelope.record_content_hash:
            raise AuditLogParseError(
                f"Content hash mismatch. Envelope recorded "
                f"{envelope.record_content_hash}; recomputed "
                f"{actual_hash}. The record may have been tampered "
                f"with, corrupted in transit, or produced by a "
                f"framework version using a different canonical "
                f"serialization."
            )

    return envelope


# -- helpers --------------------------------------------------------------


def _record_canonical_bytes(record: TriageRecord) -> bytes:
    """Serialize a TriageRecord to canonical JSON bytes for hashing.

    Canonical serialization rules:

    - Sorted keys (for deterministic output across Python versions)
    - No whitespace (compact separators)
    - exclude_none=True (the framework's TriageRecord.model_dump
      default; matches the schema's "type": "string" not "string |
      null" treatment of optional fields)
    - UTF-8 encoding
    - Datetimes as ISO 8601 strings (Pydantic's mode="json" default)

    Two callers computing the hash of the same record must agree
    on these rules or the hash will differ. The rules are stable
    across framework versions within the envelope schema major
    version; a bump to ENVELOPE_SCHEMA_VERSION's major signals a
    canonical-serialization change.
    """
    payload = record.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
