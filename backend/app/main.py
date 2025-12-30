from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from . import models
from .schemas import PatchOrder, ResourceOut, SalesOrderOut, RoutingOut
from .services.oee import compute_oee
from .services.bottleneck import detect_bottleneck_v1

app = FastAPI(title="Industrial Perf Agent (V1)", version="0.2.0")


@app.get("/")
def root():
    return {"message": "API running. Go to /docs"}


# -------------------------
# Reference / Orders
# -------------------------

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


# -------------------------
# Metrics: OEE
# -------------------------

@app.get("/metrics/oee")
def oee_single(resource_id: str, hours: int = 6, db: Session = Depends(get_db)):
    """
    Compute OEE on the last N hours for one resource.
    Example: /metrics/oee?resource_id=R2&hours=4
    """
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
    """
    Compute OEE on the last N hours for all resources.
    Example: /metrics/oee/overview?hours=6
    """
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


# -------------------------
# Metrics: Bottleneck (V1)
# -------------------------

@app.get("/metrics/bottleneck")
def bottleneck(hours: int = 6, db: Session = Depends(get_db)):
    """
    V1 bottleneck pre-diagnostic on the last N hours.
    Example: /metrics/bottleneck?hours=6
    """
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
