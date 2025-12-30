from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from .. import models


def _minutes_to_td(m: float) -> timedelta:
    return timedelta(minutes=float(m))


def plan_schedule(db: Session, now: datetime) -> Dict:
    """
    V1: forward scheduling (ASAP)
    - Sort orders by due_date asc, then priority desc
    - For each order, route steps sequentially
    - Each resource is single-capacity; we track next available time
    """
    orders = (
        db.query(models.SalesOrder)
        .order_by(models.SalesOrder.due_date.asc(), models.SalesOrder.priority.desc())
        .all()
    )

    # Preload routing for the family (V1: one routing per family)
    # If multiple routings exist later, we’ll select by rule.
    family_to_routing: Dict[str, models.Routing] = {}
    for o in orders:
        if o.family_id not in family_to_routing:
            r = (
                db.query(models.Routing)
                .filter(models.Routing.family_id == o.family_id)
                .first()
            )
            if not r:
                raise ValueError(f"No routing found for family_id={o.family_id}")
            family_to_routing[o.family_id] = r

    # machine availability timeline
    next_free: Dict[str, datetime] = {}
    for r in db.query(models.Resource).all():
        next_free[r.id] = now

    ops_out: List[Dict] = []

    for o in orders:
        routing = family_to_routing[o.family_id]
        steps = (
            db.query(models.RoutingStep)
            .filter(models.RoutingStep.routing_id == routing.id)
            .order_by(models.RoutingStep.seq.asc())
            .all()
        )

        prev_end = o.release_date.replace(tzinfo=None) if o.release_date else now

        for s in steps:
            machine_ready = next_free.get(s.resource_id, now)
            start = max(prev_end, machine_ready)

            duration_min = float(s.setup_min) + float(o.quantity) * float(s.run_min_per_unit)
            end = start + _minutes_to_td(duration_min)

            ops_out.append(
                {
                    "order_id": o.id,
                    "routing_id": routing.id,
                    "step_seq": s.seq,
                    "resource_id": s.resource_id,
                    "start_ts": start,
                    "end_ts": end,
                    "setup_min": s.setup_min,
                    "run_min_per_unit": s.run_min_per_unit,
                    "quantity": o.quantity,
                    "due_date": o.due_date,
                    "priority": o.priority,
                }
            )

            next_free[s.resource_id] = end
            prev_end = end

    # lateness summary (simple)
    lateness = []
    # last op end per order
    last_end: Dict[str, datetime] = {}
    for op in ops_out:
        last_end[op["order_id"]] = max(last_end.get(op["order_id"], now), op["end_ts"])

    for o in orders:
        if o.id in last_end:
            tardy_min = max(0.0, (last_end[o.id] - o.due_date).total_seconds() / 60.0)
            lateness.append({"order_id": o.id, "tardy_min": tardy_min})

    lateness.sort(key=lambda x: x["tardy_min"], reverse=True)

    return {
        "generated_at": now,
        "ops": ops_out,
        "lateness": lateness,
    }


def persist_schedule(db: Session, plan: Dict) -> Dict:
    # clear old schedule
    db.query(models.ScheduledOp).delete()

    for op in plan["ops"]:
        db.add(
            models.ScheduledOp(
                order_id=op["order_id"],
                routing_id=op["routing_id"],
                step_seq=op["step_seq"],
                resource_id=op["resource_id"],
                start_ts=op["start_ts"],
                end_ts=op["end_ts"],
                setup_min=op["setup_min"],
                run_min_per_unit=op["run_min_per_unit"],
                quantity=op["quantity"],
            )
        )

    db.commit()
    return {"status": "ok", "ops_count": len(plan["ops"])}
