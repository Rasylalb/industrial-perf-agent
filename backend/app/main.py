from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .db import get_db
from . import models
from .schemas import PatchOrder, ResourceOut, SalesOrderOut, RoutingOut

from .services.oee import compute_oee
from .services.bottleneck import detect_bottleneck_v1
from .services.scheduler import plan_schedule, persist_schedule

app = FastAPI(title="Industrial Perf Agent (V1)", version="0.4.0")


@app.get("/")
def root():
    return {"message": "API running. Go to /docs or /ui/gantt"}


# ============================================================
# Reference / Orders
# ============================================================

@app.get("/resources", response_model=list[ResourceOut])
def list_resources(db: Session = Depends(get_db)):
    return db.query(models.Resource).order_by(models.Resource.id).all()


@app.get("/orders", response_model=list[SalesOrderOut])
def list_orders(db: Session = Depends(get_db)):
    return db.query(models.SalesOrder).order_by(models.SalesOrder.due_date).all()


@app.patch("/orders/{order_id}")
def patch_order(order_id: str, patch: PatchOrder, db: Session = Depends(get_db)):
    o = db.query(models.SalesOrder).filter(models.SalesOrder.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")

    if patch.due_date is not None:
        o.due_date = patch.due_date.replace(tzinfo=None)
    if patch.priority is not None:
        o.priority = patch.priority
    if patch.quantity is not None:
        o.quantity = patch.quantity
    if patch.release_date is not None:
        o.release_date = patch.release_date.replace(tzinfo=None)

    db.commit()
    return {"status": "ok", "updated": order_id}


@app.get("/routings/{family_id}", response_model=list[RoutingOut])
def get_routings(family_id: str, db: Session = Depends(get_db)):
    routings = db.query(models.Routing).filter(models.Routing.family_id == family_id).all()

    out = []
    for r in routings:
        steps = (
            db.query(models.RoutingStep)
            .filter(models.RoutingStep.routing_id == r.id)
            .order_by(models.RoutingStep.seq)
            .all()
        )
        out.append(
            {
                "id": r.id,
                "family_id": r.family_id,
                "name": r.name,
                "steps": [
                    {
                        "seq": s.seq,
                        "resource_id": s.resource_id,
                        "setup_min": s.setup_min,
                        "run_min_per_unit": s.run_min_per_unit,
                        "yield_expected": s.yield_expected,
                    }
                    for s in steps
                ],
            }
        )
    return out


# ============================================================
# Metrics — OEE
# ============================================================

@app.get("/metrics/oee")
def oee_single(resource_id: str, hours: int = 6, db: Session = Depends(get_db)):
    end = datetime.now().replace(tzinfo=None)
    start = end - timedelta(hours=hours)

    res = compute_oee(db, resource_id=resource_id, start=start, end=end)
    return {
        "resource_id": res.resource_id,
        "window": {"start": res.window_start, "end": res.window_end},
        "time_min": {"planned": res.planned_min, "run": res.run_min, "stop": res.stop_min},
        "counts": {"good": res.good, "scrap": res.scrap, "total": res.total},
        "rates": {
            "availability": res.availability,
            "performance": res.performance,
            "quality": res.quality,
            "oee": res.oee,
        },
    }


@app.get("/metrics/oee/overview")
def oee_overview(hours: int = 6, db: Session = Depends(get_db)):
    end = datetime.now().replace(tzinfo=None)
    start = end - timedelta(hours=hours)

    resources = db.query(models.Resource).order_by(models.Resource.id).all()
    items = []
    for r in resources:
        res = compute_oee(db, resource_id=r.id, start=start, end=end)
        items.append(
            {
                "resource_id": r.id,
                "name": r.name,
                "availability": res.availability,
                "performance": res.performance,
                "quality": res.quality,
                "oee": res.oee,
            }
        )

    return {"window": {"start": start, "end": end}, "items": items}


# ============================================================
# Metrics — Bottleneck
# ============================================================

@app.get("/metrics/bottleneck")
def bottleneck(hours: int = 6, db: Session = Depends(get_db)):
    end = datetime.now().replace(tzinfo=None)
    start = end - timedelta(hours=hours)

    res = detect_bottleneck_v1(db, start=start, end=end)
    return {
        "window": {"start": res.window_start, "end": res.window_end},
        "bottleneck": {
            "resource_id": res.winner_id,
            "name": res.winner_name,
            "score": res.score,
        },
        "explain": res.explain,
        "ranking": res.ranking,
    }


# ============================================================
# Scheduling — Plan / Get / Replan
# ============================================================

@app.post("/schedule/plan")
def schedule_plan(db: Session = Depends(get_db)):
    now = datetime.now().replace(tzinfo=None)
    plan = plan_schedule(db, now=now)
    saved = persist_schedule(db, plan)
    return {
        "status": saved["status"],
        "ops_count": saved["ops_count"],
        "plan": {"generated_at": plan["generated_at"], "lateness": plan["lateness"]},
    }


@app.get("/schedule")
def get_schedule(db: Session = Depends(get_db)):
    ops = db.query(models.ScheduledOp).order_by(models.ScheduledOp.start_ts.asc()).all()
    return {
        "ops": [
            {
                "order_id": o.order_id,
                "resource_id": o.resource_id,
                "step_seq": o.step_seq,
                "start_ts": o.start_ts,
                "end_ts": o.end_ts,
                "quantity": o.quantity,
            }
            for o in ops
        ]
    }


@app.post("/schedule/replan")
def schedule_replan(db: Session = Depends(get_db)):
    now = datetime.now().replace(tzinfo=None)
    plan = plan_schedule(db, now=now)
    saved = persist_schedule(db, plan)
    return {
        "status": saved["status"],
        "ops_count": saved["ops_count"],
        "plan": {"generated_at": plan["generated_at"], "lateness": plan["lateness"]},
    }


# ============================================================
# UI — Gantt
# ============================================================

@app.get("/ui/gantt", response_class=HTMLResponse)
def ui_gantt():
    html_path = Path(__file__).parent / "static" / "gantt.html"
    return html_path.read_text(encoding="utf-8")
