from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class PatchOrder(BaseModel):
    due_date: Optional[datetime] = None
    priority: Optional[int] = None
    quantity: Optional[int] = Field(default=None, ge=1)
    release_date: Optional[datetime] = None


class ResourceOut(BaseModel):
    id: str
    name: str
    type: str
    is_active: bool


class SalesOrderOut(BaseModel):
    id: str
    family_id: str
    quantity: int
    priority: int
    release_date: Optional[datetime]
    due_date: datetime


class RoutingStepOut(BaseModel):
    seq: int
    resource_id: str
    setup_min: int
    run_min_per_unit: float
    yield_expected: float


class RoutingOut(BaseModel):
    id: str
    family_id: str
    name: str
    steps: List[RoutingStepOut]
