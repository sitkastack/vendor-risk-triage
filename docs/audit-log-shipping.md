# Audit log shipping format

The framework produces `TriageRecord` JSON. Those records are already audit-quality: they carry decision IDs, timestamps, agent versions, evidence citations, and disposition rationale. A deploying organization that simply writes each record to a durable store is technically compliant with most current regulatory expectations for AI vendor-risk audit trails.

This document specifies the shipping envelope a deployment uses when records flow into a SIEM, archive, event bus, or compliance pipeline. The envelope adds operational metadata (content hash for integrity, sequence number for ordering, deployment ID for multi-tenant routing, shipping timestamp for ingestion-time queries) without modifying the underlying record.

The framework ships `reporting/audit_log.py` as a reference adapter. The illustrative consumer examples in Section 4 are not runnable production code; they show the shape a Splunk, S3, or Kafka consumer would handle.

## 1. Envelope schema

The envelope is a flat JSON object with seven fields. Wire format schema version: `1.0.0`.

```json
{
  "envelope_schema_version": "1.0.0",
  "record_content_hash": "sha256:56ae5c5d3c3660c7fa72f4f86ea187038d44889481c739e7b0be29a7b14a2bfb",
  "record": { ... full TriageRecord ... },
  "sequence_number": 42,
  "deployment_id": "acme-prod",
  "shipped_at": "2026-05-22T09:35:00.000000Z",
  "replay_of": null
}
```

### Field definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `envelope_schema_version` | string, `MAJOR.MINOR.PATCH` | yes | Wire format version. Consumers check the major. Bumped on any breaking change to envelope shape, hash algorithm, or canonical-bytes rules. |
| `record_content_hash` | string, `sha256:<64hex>` | yes | SHA-256 of the embedded TriageRecord's canonical JSON serialization. Receivers recompute and verify. |
| `record` | object | yes | The full TriageRecord as produced by the framework. Conforms to `schemas/output-contract-1.0.0.schema.json`. |
| `sequence_number` | integer, `>= 0` | yes | Monotonically increasing integer assigned by the deploying organization's shipping pipeline. Used to detect dropped or reordered messages. |
| `deployment_id` | string, 1-128 chars | yes | Stable identifier for the deployment environment. Used for multi-tenant SIEM routing and archive partitioning. Recommended pattern: `{org-slug}-{environment}` (e.g., `acme-prod`). |
| `shipped_at` | string, RFC 3339 datetime with timezone | yes | When the envelope was constructed for shipping. Distinct from `record.decision_timestamp`, which records when the agent produced the decision. |
| `replay_of` | string or null | no | When this is a replay of an earlier envelope, the prior envelope's `decision_id:sequence_number`. Omitted (or null) for first-time shipments. |

### Canonical serialization rules

The `record_content_hash` is computed over the embedded TriageRecord serialized with these rules. Producers and consumers must agree, or the hash will not verify:

- **Sorted keys**: alphabetical ordering at every JSON object level
- **Compact separators**: `","` between elements, `":"` after keys (no whitespace)
- **exclude_none**: optional fields with null values are omitted, not emitted as `null`
- **UTF-8 encoding**: bytes are UTF-8
- **Datetime serialization**: ISO 8601 strings, Pydantic mode="json" default

The framework's `_record_canonical_bytes()` helper implements these rules. Bumping `envelope_schema_version`'s major version signals a change to these rules (none planned for v1).

### Why these rules matter

The hash is the integrity check. If a record is corrupted in transit, tampered with at rest, or produced by a framework version using different canonical-serialization rules, the receiver's recomputed hash will not match the envelope's recorded hash. This catches:

- Transport corruption (rare but real)
- Active tampering (an attacker modifying records in a SIEM index)
- Version drift (a producer at v1.0.0 talking to a consumer at v2.0.0 without explicit migration)

The recorded hash is meaningful only to the extent the canonical-bytes rules are stable. Within a major schema version, they are.

## 2. Producer-side workflow

The framework's reference adapter is `reporting/audit_log.py`. Usage:

```python
from reporting import build_envelope

envelope = build_envelope(
    record=triage_record,
    sequence_number=next_sequence(),
    deployment_id="acme-prod",
)
line = envelope.to_jsonl_line()
# Ship `line`. Transport is the deploying organization's concern.
```

### Sequence numbers

The framework does not assign sequence numbers. The deploying organization's shipping pipeline does. Reasonable sources:

- A Redis `INCR` counter scoped to the deployment_id
- The offset of a Kafka producer record
- A database SEQUENCE in PostgreSQL
- An S3 object's millisecond-precision timestamp suffix (loose ordering)

The sequence_number's purpose is to detect drops or reordering on the receiver side. Consumers compare each envelope's sequence_number to the prior, flag gaps as potential drops, and flag out-of-order arrivals for investigation.

The framework's TriageRecord already has decision_id (a stable UUID-like identifier produced at decision time). Sequence numbers complement decision_id: decision_id identifies the decision, sequence_number identifies the shipment instance.

### Replay semantics

When a downstream pipeline asks for replay of a window (e.g., "ship me everything from Q2 2026 again so I can re-index my SIEM"), the replay envelopes use `replay_of` to reference the original shipments:

```python
replay_envelope = build_envelope(
    record=original_record,
    sequence_number=new_sequence_number,  # fresh number from replay pipeline
    deployment_id="acme-prod",
    replay_of=f"{original_record.decision_id}:{original_sequence_number}",
)
```

Receivers seeing `replay_of` know to handle the envelope idempotently: insert or update by `decision_id`, not append.

### Shipping at scale

For SIEMs that accept batched POSTs (Splunk HEC, Datadog Logs API), wrap N envelopes' JSONL lines into a single HTTP body. The envelopes are independent; the batch is a transport optimization, not a semantic grouping. A future Phase 6 deliverable adds a `build_batch()` helper; for now, callers concatenate JSONL lines directly.

For Kafka/EventBridge/Pub/Sub, send one envelope per message. The deployment_id is a natural partition key.

For S3/GCS/Azure Blob archives, group envelopes into hourly or daily files keyed by deployment_id. A reasonable prefix scheme: `s3://your-bucket/vrt/{deployment_id}/{YYYY}/{MM}/{DD}/{HH}.jsonl`.

## 3. Consumer-side workflow

Consumers receive envelopes one at a time and use `parse_jsonl_line()` to unwrap with hash verification:

```python
from reporting import parse_jsonl_line, AuditLogParseError

try:
    envelope = parse_jsonl_line(line)
except AuditLogParseError as exc:
    # Surface to monitoring; do not silently drop
    logger.error("audit log parse failed: %s", exc)
    raise

# Access the framework's record
record = envelope.record
print(record.decision_id, record.risk_tier, record.recommended_disposition)
```

### Failure modes consumers handle

- **`AuditLogParseError`**: malformed JSON, schema mismatch, incompatible version, hash failure. Treat as data quality incidents; route to a dead-letter queue, alert on rate.
- **Out-of-order sequence numbers**: log and reorder via the decision_id, or buffer briefly to assemble in order. Most consumers can tolerate small reorderings; flagging is enough.
- **Gaps in sequence numbers**: indicates a possible drop. Alert if the gap exceeds a threshold (e.g., 100 messages over 5 minutes).
- **Replay envelopes**: handle idempotently via the decision_id. Upsert, do not append.

### Verifying without the framework code

A consumer that wants to verify hashes without depending on the framework's Python code can reproduce the canonical-bytes rules in any language:

```python
# Pseudocode; adapt to your consumer's language
import json, hashlib

record_dict = envelope["record"]
# Remove any null-valued optional fields (exclude_none equivalent)
canonical_dict = {k: v for k, v in record_dict.items() if v is not None}
canonical_bytes = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
recomputed = "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
assert recomputed == envelope["record_content_hash"]
```

Note that "exclude_none" in Pydantic excludes top-level None values. Nested objects' None values are also excluded. A non-Python consumer reimplementing the canonical-bytes rules needs to apply exclude_none recursively at every nesting level, or match the framework's serialization exactly.

## 4. Illustrative consumer examples

The examples below are illustrative, not runnable production code. Vendor SDKs evolve; consult current docs when implementing. Each example shows the envelope-parsing shape, not the vendor-specific transport plumbing.

### 4.1 Splunk HEC consumer (HTTP Event Collector)

Splunk's HEC accepts JSON events one per HTTP request body (or batched). A consumer parsing inbound events from Splunk's `/services/collector/event` endpoint:

```python
# Illustrative; see Splunk HEC documentation for current SDK
from reporting import parse_jsonl_line, AuditLogParseError

def handle_splunk_event(raw_event_text: str) -> None:
    """Splunk HEC consumer side. Parses a single envelope event."""
    try:
        envelope = parse_jsonl_line(raw_event_text)
    except AuditLogParseError as exc:
        # Route to dead-letter index
        splunk_dlq_index(raw_event_text, str(exc))
        return

    # Now drive Splunk indexing decisions from the envelope content.
    # Splunk's host/source/sourcetype map naturally to the envelope fields.
    splunk_index_event(
        index="vrt_audit",
        host=envelope.deployment_id,
        source=f"vrt-agent:{envelope.record.agent_version}",
        sourcetype="vrt:triage_record",
        event=envelope.record.model_dump(mode="json"),
    )
```

Recommended Splunk index strategy: one index per `deployment_id` (or one shared with `host` set to deployment_id for filtering). Per-record fields most useful for Splunk searches are `record.risk_tier`, `record.recommended_disposition`, `record.input_submission_id` (vendor_id), and `record.regulatory_framework_tags`.

### 4.2 S3 archive consumer

For long-term retention, envelopes typically batch into hourly or daily JSONL files in S3. A consumer reading those files for audit queries:

```python
# Illustrative; see boto3 documentation for current SDK
import boto3
from reporting import parse_jsonl_line, AuditLogParseError

def read_audit_day(deployment_id: str, year: int, month: int, day: int):
    """Read a day's worth of envelopes from S3, yielding each record."""
    s3 = boto3.client("s3")
    prefix = f"vrt/{deployment_id}/{year:04d}/{month:02d}/{day:02d}/"
    response = s3.list_objects_v2(Bucket="your-audit-bucket", Prefix=prefix)
    for obj in response.get("Contents", []):
        body = s3.get_object(Bucket="your-audit-bucket", Key=obj["Key"])["Body"]
        for line in body.iter_lines():
            try:
                envelope = parse_jsonl_line(line.decode("utf-8"))
                yield envelope.record
            except AuditLogParseError as exc:
                # Log; continue (audit-time queries tolerate per-line failures)
                logger.warning("skipped envelope in %s: %s", obj["Key"], exc)
```

For archives, deduplication on `decision_id` handles replays naturally: a query that aggregates by decision_id with `MAX(sequence_number)` (or `MAX(shipped_at)`) returns the latest shipment per decision.

### 4.3 Kafka consumer

For real-time streaming, envelopes flow through a Kafka topic with `deployment_id` as the partition key. A consumer driving downstream analytics:

```python
# Illustrative; see confluent-kafka or aiokafka documentation for current SDK
from confluent_kafka import Consumer
from reporting import parse_jsonl_line, AuditLogParseError

consumer = Consumer({
    "bootstrap.servers": "kafka.example.com:9092",
    "group.id": "vrt-analytics-consumer",
    "auto.offset.reset": "earliest",
})
consumer.subscribe(["vrt-audit-records"])

while True:
    msg = consumer.poll(timeout=1.0)
    if msg is None or msg.error():
        continue
    try:
        envelope = parse_jsonl_line(msg.value().decode("utf-8"))
    except AuditLogParseError as exc:
        # Dead-letter topic
        dlq_producer.send("vrt-audit-records-dlq", msg.value())
        continue

    # Drive downstream analytics
    analytics_pipeline.ingest(
        decision_id=envelope.record.decision_id,
        deployment_id=envelope.deployment_id,
        tier=envelope.record.risk_tier,
        disposition=envelope.record.recommended_disposition,
        confidence=envelope.record.confidence_signal.score,
        shipped_at=envelope.shipped_at,
    )
```

Kafka's partition guarantees order within a partition. Using `deployment_id` as the key keeps each deployment's events in a single partition, which preserves sequence_number ordering for that deployment.

## 5. Operational considerations

### Retention

The framework does not opine on retention duration. Regulators differ:

- OSFI E-23 expects model risk records retained "for the lifetime of the model and a reasonable period thereafter." Common interpretation: 7 years post-decommission.
- SOX requires 7 years for financial reporting controls evidence.
- EU AI Act Article 12 (record-keeping) specifies records retained for "at least 10 years."
- GDPR Article 5(1)(e) requires storage limitation: retain only as long as necessary for the purpose.

A deploying organization sets retention policy based on its regulatory mix, typically using the longest applicable period. The framework's envelope format is independent of retention; the same format works for 90-day SIEM hot storage and 10-year cold archive.

### Encryption

The framework does not encrypt envelopes. Encryption-at-rest is the storage layer's concern (S3 SSE, Splunk index-time encryption, Kafka topic encryption). Encryption-in-transit is the transport layer's concern (TLS).

For archives where transport encryption is insufficient (e.g., shipping to a third-party archive provider), envelope-level AES-GCM encryption is queued as a Phase 6 deliverable. The base envelope format is unchanged; an outer encrypted wrapper would add the cipher metadata.

### Time synchronization

Both `shipped_at` and `record.decision_timestamp` rely on clock accuracy. Deployments should synchronize clocks (NTP) to limit timestamp skew. The envelope tolerates small skews (the `shipped_at` field is informational, not used for ordering - that's `sequence_number`'s job).

### Multi-tenant deployments

When a single framework instance serves multiple deploying organizations (a managed-service scenario), each gets a distinct `deployment_id`. The framework does not enforce multi-tenancy itself; the managed-service operator sets `deployment_id` per call. Phase 7 sub-system (multi-tenant corpora) adds explicit multi-tenant support; Phase 5's envelope already supports multi-tenant deployment-IDs via the field.

## 6. Schema evolution

The envelope schema version is `1.0.0`. Major version bumps signal breaking changes:

- New required fields (consumers must update before producers ship)
- Renamed fields
- Changes to canonical-bytes rules
- Changes to the hash algorithm (e.g., SHA-256 → SHA-512)

Minor and patch bumps signal backwards-compatible additions:

- New optional fields (consumers ignore unknowns)
- Documentation refinements
- Performance optimizations that preserve wire format

The framework's `ENVELOPE_SCHEMA_VERSION` constant is the source of truth. Consumers should check the major version on parse and refuse incompatible majors with a clear error message.

A breaking change requires a migration story. The framework will document the migration when a v2 bump is needed. For v1, no migration is planned.

## Deferred

- `[deferred-phase-6]` Batch-shipping helper (`build_batch()` wrapping N envelopes in one HTTP body)
- `[deferred-phase-6]` Encryption-at-rest adapter (envelope-level AES-GCM for archive scenarios)
- `[deferred-phase-7]` Cross-envelope chained-hash for full-chain forensic verification (each envelope's hash includes the prior envelope's hash; tampering with one breaks the chain across the entire deployment's history)
- `[deferred-phase-7]` Tamper-evident sequencing via signed checkpoints (the deploying organization periodically signs a checkpoint of the form `{deployment_id, last_sequence_number, hash_of_all_envelopes_to_date}` and ships it alongside; provides auditor-verifiable evidence the log has not been retroactively edited)
