# Interaction logging endpoint — receives frontend behavior signals
# Lightweight fire-and-forget: never blocks the UI

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from auth.middleware import require_auth
from learning.interaction_logger import interaction_logger

log_router = APIRouter()


class InteractionEvent(BaseModel):
    session_id: Optional[str] = None
    action: str = Field(..., min_length=1, max_length=100)
    flight_rank: Optional[int] = None
    flight_id: Optional[str] = None
    details: Optional[dict] = None


@log_router.post("/interaction")
async def log_interaction(event: InteractionEvent, token: str = Depends(require_auth)):
    """Record a frontend user interaction (click, expand, etc.)."""
    await interaction_logger.log_interaction(
        session_id=event.session_id,
        action=event.action,
        details={
            k: v for k, v in {
                "flight_rank": event.flight_rank,
                "flight_id": event.flight_id,
                **(event.details or {}),
            }.items() if v is not None
        },
    )
    return {"logged": True}
