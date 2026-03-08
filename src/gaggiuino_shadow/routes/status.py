from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("")
async def get_status(request: Request):
    db = request.app.state.db
    engine = request.app.state.sync_engine
    status = await db.get_latest_status()
    return {
        "data": status["data"] if status else None,
        "syncedAt": status["timestamp"] if status else None,
        "machineOnline": engine.machine_online,
    }


@router.get("/history")
async def get_status_history(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    since: str | None = Query(None),
):
    db = request.app.state.db
    rows = await db.get_status_history(limit=limit, since=since)
    return {"data": rows, "count": len(rows)}
