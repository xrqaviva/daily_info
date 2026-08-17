from dataclasses import asdict, dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class Observation:
    source: str
    instrument: str
    value: float
    previous_value: Optional[float]
    change_pct: Optional[float]
    market_date: str
    unit: str
    url: str
    as_of: str
    contract: Optional[str] = None
    previous_market_date: Optional[str] = None
    date_quality: str = "explicit"

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    status: str
    consensus_value: Any
    consensus_change_pct: Optional[float]
    observations: Tuple[Observation, ...]
    reason: Optional[str] = None
    relative_difference: Optional[float] = None

    def to_dict(self):
        return {
            "status": self.status,
            "consensus_value": self.consensus_value,
            "consensus_change_pct": self.consensus_change_pct,
            "observations": [item.to_dict() for item in self.observations],
            "reason": self.reason,
            "relative_difference": self.relative_difference,
        }


@dataclass(frozen=True)
class BreadthResult:
    sample_size: int
    up: int
    down: int
    flat: int
    up_rate: Optional[float]
    down_rate: Optional[float]
    market_date: Optional[str] = None
    codes: Tuple[str, ...] = ()
    duplicate_codes: Tuple[str, ...] = ()

    def to_dict(self):
        return asdict(self)
