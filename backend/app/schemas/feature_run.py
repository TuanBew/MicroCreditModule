from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FeatureRunRequest(BaseModel):
    input_payload: dict = {}


class FeatureRunResponse(BaseModel):
    id: uuid.UUID
    feature_key: str
    credits_spent: int
    result_payload: dict
    balance: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
