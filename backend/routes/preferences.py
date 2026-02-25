# Preference CRUD API endpoints
# Manages user preferences that influence all Claude prompts

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from auth.middleware import require_auth
from learning.preferences import preferences_manager

preferences_router = APIRouter()


class AddPreferenceRequest(BaseModel):
    content: str = Field(..., min_length=3, max_length=500)
    category: str = Field(default="soft_preference", pattern="^(hard_constraint|soft_preference|context)$")


class PreferenceResponse(BaseModel):
    id: str
    content: str
    category: str
    source: str
    active: bool
    created_at: str


@preferences_router.get("")
async def get_preferences(token: str = Depends(require_auth)):
    """Return all user preferences with version info."""
    return preferences_manager.get_all()


@preferences_router.post("", response_model=PreferenceResponse)
async def add_preference(req: AddPreferenceRequest, token: str = Depends(require_auth)):
    """Add a new user preference."""
    pref = await preferences_manager.add(
        content=req.content,
        category=req.category,
        source="explicit",
    )
    return pref


@preferences_router.put("/{pref_id}")
async def toggle_preference(pref_id: str, token: str = Depends(require_auth)):
    """Toggle a preference active/inactive."""
    result = await preferences_manager.toggle(pref_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Preference not found")
    return result


@preferences_router.delete("/{pref_id}")
async def delete_preference(pref_id: str, token: str = Depends(require_auth)):
    """Delete a preference."""
    deleted = await preferences_manager.delete(pref_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Preference not found")
    return {"deleted": True}
