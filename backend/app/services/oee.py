from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_

from .. import models


@dataclass
class OeeResult:
    resource_id: str
    window_start: datetime
    window_end: datetime

    planned_min: float
    run_min: float
    stop_min: float

    good: int
    scrap: int
    total: int

    availability: float
    performance: float
    quality: float
    oee: float


def _minutes(dt_start: datetime, dt_end: datetime) -> float:
    return max(0.0, (dt_end - dt_start).total_seconds() / 60.0)


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    """Return overlap duration in minutes between [a_start,a_end] and [b_start,b_end]."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return _minutes(start, end) if end > start else 0.0


def compute_oee(db: Session, resource_id: str, start: datetime, end: datetime) -> OeeResult:
    """
    OEE over a time window.
    - Planned time: full window duration (simple V1 assumption).
    - Run/Stop from machine_states overlap with window.
    - Counts (good/scrap/total) from production_counts overlap with window.
    - Performance compares total output vs ideal output using ideal_rate_per_min.
    """

    planned_min = _minutes(start, end)

    # 1) Availability from machine states
    states = (
        db.query(models.MachineState)
        .filter(
            models.MachineState.resource_id == resource_id,
            models.MachineState.ts_end > start,
            models.MachineState.ts_start < end,
        )
        .all()
    )

    run_min = 0.0
    stop_min = 0.0
    for s in states:
        ol = _overlap(s.ts_start, s.ts_end, start, end)
        if s.state == "RUN":
            run_min += ol
        elif s.state == "STOP":
            stop_min += ol
        # IDLE/SETUP ignored in V1 availability (can be refined later)

    availability = (run_min / planned_min) if planned_min > 0 else 0.0

    # 2) Quality from counts
    counts = (
        db.query(models.ProductionCount)
        .filter(
            models.ProductionCount.resource_id == resource_id,
            models.ProductionCount.ts_end > start,
            models.ProductionCount.ts_start < end,
        )
        .all()
    )

    good = 0
    scrap = 0
    total = 0

    ideal_units = 0.0  # theoretical output at ideal rate (for performance)

    for c in counts:
        ol_min = _overlap(c.ts_start, c.ts_end, start, end)

        # Pro-rate counts by overlap fraction (simple and robust for buckets)
        bucket_min = _minutes(c.ts_start, c.ts_end)
        frac = (ol_min / bucket_min) if bucket_min > 0 else 0.0

        good += int(round(c.good * frac))
        scrap += int(round(c.scrap * frac))
        total += int(round(c.total * frac))

        ideal_units += c.ideal_rate_per_min * ol_min

    quality = (good / total) if total > 0 else 0.0

    # 3) Performance: actual output / ideal output (over same window)
    performance = (total / ideal_units) if ideal_units > 0 else 0.0

    oee = availability * performance * quality

    return OeeResult(
        resource_id=resource_id,
        window_start=start,
        window_end=end,
        planned_min=planned_min,
        run_min=run_min,
        stop_min=stop_min,
        good=good,
        scrap=scrap,
        total=total,
        availability=availability,
        performance=performance,
        quality=quality,
        oee=oee,
    )
