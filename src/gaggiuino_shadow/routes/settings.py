from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/settings", tags=["settings"])

VALID_CATEGORIES = ["boiler", "system", "theme", "display", "scales", "led", "versions"]


@router.get("")
async def get_all_settings(request: Request):
    db = request.app.state.db
    engine = request.app.state.sync_engine
    settings = await db.get_settings()
    combined = {s["category"]: s["data"] for s in settings}
    latest_sync = max((s["syncedAt"] for s in settings), default=None) if settings else None
    return {
        "data": combined,
        "syncedAt": latest_sync,
        "machineOnline": engine.machine_online,
    }


@router.get("/{category}")
async def get_settings_by_category(request: Request, category: str):
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}",
        )
    db = request.app.state.db
    engine = request.app.state.sync_engine
    settings = await db.get_settings(category)
    if not settings:
        raise HTTPException(status_code=404, detail=f"No {category} settings synced yet")
    return {
        "data": settings["data"],
        "syncedAt": settings["syncedAt"],
        "machineOnline": engine.machine_online,
    }
