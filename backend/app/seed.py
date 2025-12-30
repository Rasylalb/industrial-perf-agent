from datetime import datetime, timedelta
import random

from .db import engine, SessionLocal
from . import models


def reset_db():
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)


def seed_reference(db):
    db.add_all(
        [
            models.Resource(id="R1", name="Impression"),
            models.Resource(id="R2", name="Découpe"),
            models.Resource(id="R3", name="Pliage/Collage"),
        ]
    )

    fam = models.ProductFamily(id="FAM_KRAFT_BAG", name="Sac kraft (famille démo)")
    db.add(fam)

    routing = models.Routing(
        id="RTG_KRAFT", family_id=fam.id, name="Impression → Découpe → Pliage/Collage"
    )
    db.add(routing)
    db.flush()

    db.add_all(
        [
            models.RoutingStep(
                routing_id=routing.id, seq=1, resource_id="R1", setup_min=12, run_min_per_unit=0.08
            ),
            models.RoutingStep(
                routing_id=routing.id, seq=2, resource_id="R2", setup_min=8, run_min_per_unit=0.06
            ),
            models.RoutingStep(
                routing_id=routing.id, seq=3, resource_id="R3", setup_min=10, run_min_per_unit=0.10
            ),
        ]
    )


def seed_orders(db, now: datetime):
    for i in range(1, 7):
        qty = random.choice([500, 800, 1200, 1500])
        prio = random.choice([1, 2, 3, 5])
        due = now + timedelta(days=random.choice([1, 2, 3, 4]))
        rel = now - timedelta(hours=random.choice([0, 3, 6]))
        db.add(
            models.SalesOrder(
                id=f"SO{i:03d}",
                family_id="FAM_KRAFT_BAG",
                quantity=qty,
                priority=prio,
                release_date=rel,
                due_date=due,
            )
        )


def seed_evocon_like(db, now: datetime):
    start = now - timedelta(hours=6)
    bucket = timedelta(minutes=5)

    configs = {
        "R1": {"ideal_rate": 40, "stop_prob": 0.08},
        "R2": {"ideal_rate": 50, "stop_prob": 0.12},
        "R3": {"ideal_rate": 35, "stop_prob": 0.06},
    }
    stop_reasons = ["Panne", "Manque_matiere", "Reglage", "Micro_arret"]

    t = start
    while t < now:
        for rid, cfg in configs.items():
            ideal = cfg["ideal_rate"]
            will_stop = random.random() < cfg["stop_prob"]

            ts_start = t
            ts_end = min(t + bucket, now)

            if will_stop:
                db.add(
                    models.MachineState(
                        resource_id=rid,
                        ts_start=ts_start,
                        ts_end=ts_end,
                        state="STOP",
                        reason_code=random.choice(stop_reasons),
                    )
                )
                total = random.randint(0, 10)
            else:
                db.add(
                    models.MachineState(
                        resource_id=rid,
                        ts_start=ts_start,
                        ts_end=ts_end,
                        state="RUN",
                        reason_code=None,
                    )
                )
                minutes = int((ts_end - ts_start).total_seconds() // 60)
                expected = ideal * minutes
                total = max(0, int(random.gauss(expected, expected * 0.08)))

            scrap = max(0, int(total * random.choice([0.01, 0.02, 0.03])))
            good = max(0, total - scrap)

            db.add(
                models.ProductionCount(
                    resource_id=rid,
                    ts_start=ts_start,
                    ts_end=ts_end,
                    good=good,
                    scrap=scrap,
                    total=total,
                    ideal_rate_per_min=float(ideal),
                )
            )
        t += bucket


def main():
    now = datetime.now().replace(tzinfo=None)
    reset_db()

    db = SessionLocal()
    try:
        seed_reference(db)
        seed_orders(db, now)
        seed_evocon_like(db, now)
        db.commit()
        print("Seed OK: perf.db created with demo data.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
