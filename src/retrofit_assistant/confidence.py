"""Evidence levels fixed by mechanism, with Laplace estimates fitted on train."""

from dataclasses import dataclass
from math import isclose


@dataclass(frozen=True)
class EvidenceLevel:
    n: int
    alert_hits: int
    type_hits: int

    @property
    def alert_reliability(self):
        return (self.alert_hits + 1) / (self.n + 2)

    @property
    def type_reliability(self):
        return (self.type_hits + 1) / (self.n + 2)


RULE_LEVELS = {
    "official_protected": "high",
    "rediagnose_noise": "high",
    "rediagnose_spectrum": "high",
    "source_cavitation": "high",
    "source_stuck": "high",
    "official": "medium",
    "rediagnose_confirmed": "medium",
    "rediagnose_accelerometer": "low",
    "rediagnose_refuted": "low",
}
TRAIN_LEVELS = {
    "high": EvidenceLevel(n=14, alert_hits=14, type_hits=14),
    "medium": EvidenceLevel(n=34, alert_hits=31, type_hits=20),
    "low": EvidenceLevel(n=3, alert_hits=2, type_hits=0),
}


def evidence_level(value):
    """Recognise a level's alert estimate, allowing six-decimal CSV rounding."""
    for name, level in TRAIN_LEVELS.items():
        if isclose(float(value), level.alert_reliability, rel_tol=0, abs_tol=5e-7):
            return name
    return None


def assign_confidence(alerts):
    """Copy alerts, changing only confidence to the rule's train evidence level."""
    result = alerts.copy()
    if result.empty:
        return result
    if not result.decided_by.isin(RULE_LEVELS).all():
        raise ValueError("Unknown decided_by for evidence level")
    result["confidence"] = result.decided_by.map(RULE_LEVELS).map(
        {name: level.alert_reliability for name, level in TRAIN_LEVELS.items()}
    )
    return result
