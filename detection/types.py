"""Shared types for detection rules.

The detection framework defines its own input and output types rather
than depending on external data structures. Phase 5 implements adapters
between these types and the institution's actual operational data
sources (logs, metrics systems, etc.).

The deliberate decoupling supports portability: an institution running
the gate on AWS with CloudWatch logs and one running on GCP with Cloud
Logging both implement the same detection rules against the same types;
only their adapters differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DetectionSeverity(str, Enum):
    """Qualitative severity, consistent with threat model's no-numerical-score approach."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DetectionEvidence:
    """A structured piece of evidence supporting a detection."""
    source: str
    timestamp: datetime
    description: str
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionResult:
    """Result of running a detection rule against operational data."""
    threat_id: str
    detected: bool
    severity: DetectionSeverity
    evidence: list[DetectionEvidence] = field(default_factory=list)
    recommended_action: str | None = None

    @classmethod
    def not_detected(cls, threat_id: str) -> "DetectionResult":
        """Build a 'no threat detected' result for the given threat."""
        return cls(threat_id=threat_id, detected=False, severity=DetectionSeverity.NONE)


@dataclass
class AuditLogWindow:
    """A window of audit log events (auth, API requests, queries)."""
    start: datetime
    end: datetime
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TriageRecordWindow:
    """A window of triage records from the Triage Records store."""
    start: datetime
    end: datetime
    records: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderInteractionWindow:
    """A window of LLM provider interactions (calls, responses, latencies)."""
    start: datetime
    end: datetime
    interactions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ConfigurationSnapshot:
    """Snapshot of the gate's operational configuration at a point in time.

    Includes database role permissions, region configuration, provider
    endpoint, retention policy, and other settings detection rules
    may need to inspect.
    """
    timestamp: datetime
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionContext:
    """Context passed to every detection rule.

    Provides access to the data sources detection rules consume. Phase 5
    implements the actual data source connections; this class defines
    the interface so detection signatures are stable across institutional
    implementations.
    """
    audit_log: AuditLogWindow
    triage_records: TriageRecordWindow
    provider_interactions: ProviderInteractionWindow
    configuration: ConfigurationSnapshot
