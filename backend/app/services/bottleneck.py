from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from .. import models
from .oee import compute_oee


@dataclass
class BottleneckResult:
    window_start: datetime
    window_end: datetime
    winner_id: str
    winner_name: str
    score: float
    explain: Dict
    ranking: List[Dict]


def _top_reasons(db: Session, resource_id: str, start: datetime, end: datetime, k: int = 3) -> List[Dict]:
    """
    Top STOP reasons by total STOP minutes over the window.
    """
    states = (
        db.query(models.MachineState)
        .filter(
            models.MachineState.resource_id == resource_id,
            models.MachineState.ts_end > start,
            models.MachineState.ts_start < end,
            models.MachineState.state == "STOP",
        )
        .all()
    )

    def minutes(a: datetime, b: datetime) -> float:
        return max(0.0, (b - a).total_seconds() / 60.0)

    def overlap(a1: datetime, a2: datetime, b1: datetime, b2: datetime) -> float:
        s = max(a1, b1)
        e = min(a2, b2)
        return minutes(s, e) if e > s else 0.0

    buckets: Dict[str, float] = {}
    for s in states:
        m = overlap(s.ts_start, s.ts_end, start, end)
        key = s.reason_code or "UNKNOWN"
        buckets[key] = buckets.get(key, 0.0) + m

    top = sorted(buckets.items(), key=lambda x: x[1], reverse=True)[:k]
    return [{"reason": r, "stop_min": m} for r, m in top]


def detect_bottleneck_v1(db: Session, start: datetime, end: datetime) -> BottleneckResult:
    """
    V1 bottleneck detection (data-limited):
    - Uses utilization (run_min/planned_min) as main signal,
    - Adds a small penalty/weight for downtime share (stop_min/planned_min),
    - Provides explanations + top STOP reasons.
    This is a *pre-diagnostic* aligned with OEE-style monitoring.
    """
    resources = db.query(models.Resource).filter(models.Resource.is_active == True).order_by(models.Resource.id).all()

    ranking: List[Dict] = []
    best = None

    for r in resources:
        oee = compute_oee(db, resource_id=r.id, start=start, end=end)

        planned = max(oee.planned_min, 1e-9)
        run_ratio = oee.run_min / planned
        stop_ratio = oee.stop_min / planned

        # Transparent heuristic score (can be tuned later)
        score = 0.8 * run_ratio + 0.2 * stop_ratio

        item = {
            "resource_id": r.id,
            "name": r.name,
            "score": score,
            "signals": {
                "run_ratio": run_ratio,
                "stop_ratio": stop_ratio,
                "availability": oee.availability,
                "performance": oee.performance,
                "quality": oee.quality,
                "oee": oee.oee,
            },
        }
        ranking.append(item)

        if best is None or score > best["score"]:
            best = item

    ranking.sort(key=lambda x: x["score"], reverse=True)

    winner_id = best["resource_id"]
    winner_name = best["name"]

    reasons = _top_reasons(db, winner_id, start, end, k=3)
    explain = {
        "why": "Selected as most constraining resource using utilization (run_ratio) + downtime share (stop_ratio).",
        "winner_signals": best["signals"],
        "top_stop_reasons": reasons,
        "note": "V1 pre-diagnostic based on OEE logs; can be upgraded to course-aligned bottleneck via planned load / queues once scheduling data exists.",
    }

    return BottleneckResult(
        window_start=start,
        window_end=end,
        winner_id=winner_id,
        winner_name=winner_name,
        score=best["score"],
        explain=explain,
        ranking=ranking,
    )
