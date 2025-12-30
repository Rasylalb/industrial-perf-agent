import uuid
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from .db import Base


def _uuid():
    return str(uuid.uuid4())


class Resource(Base):
    __tablename__ = "resources"

    id = Column(String, primary_key=True)  # "R1"
    name = Column(String, nullable=False)
    type = Column(String, default="machine", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class ProductFamily(Base):
    __tablename__ = "product_families"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    notes = Column(Text, nullable=True)


class Routing(Base):
    __tablename__ = "routings"

    id = Column(String, primary_key=True)
    family_id = Column(String, ForeignKey("product_families.id"), nullable=False)
    name = Column(String, nullable=False)

    steps = relationship("RoutingStep", back_populates="routing", cascade="all, delete-orphan")


class RoutingStep(Base):
    __tablename__ = "routing_steps"

    id = Column(String, primary_key=True, default=_uuid)
    routing_id = Column(String, ForeignKey("routings.id"), nullable=False)
    seq = Column(Integer, nullable=False)
    resource_id = Column(String, ForeignKey("resources.id"), nullable=False)

    setup_min = Column(Integer, default=0, nullable=False)
    run_min_per_unit = Column(Float, default=0.0, nullable=False)
    yield_expected = Column(Float, default=0.98, nullable=False)

    routing = relationship("Routing", back_populates="steps")


class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id = Column(String, primary_key=True)  # "SO001"
    family_id = Column(String, ForeignKey("product_families.id"), nullable=False)

    quantity = Column(Integer, nullable=False)
    priority = Column(Integer, default=0, nullable=False)

    release_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=False)


class ProductionCount(Base):
    __tablename__ = "production_counts"

    id = Column(String, primary_key=True, default=_uuid)
    resource_id = Column(String, ForeignKey("resources.id"), nullable=False)

    ts_start = Column(DateTime, nullable=False)
    ts_end = Column(DateTime, nullable=False)

    good = Column(Integer, nullable=False)
    scrap = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)

    ideal_rate_per_min = Column(Float, nullable=False)


class MachineState(Base):
    __tablename__ = "machine_states"

    id = Column(String, primary_key=True, default=_uuid)
    resource_id = Column(String, ForeignKey("resources.id"), nullable=False)

    ts_start = Column(DateTime, nullable=False)
    ts_end = Column(DateTime, nullable=False)

    state = Column(String, nullable=False)  # RUN/STOP/IDLE/SETUP
    reason_code = Column(String, nullable=True)  # if STOP
