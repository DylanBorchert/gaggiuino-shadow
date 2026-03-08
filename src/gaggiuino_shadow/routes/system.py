from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
async def get_health(request: Request):
    engine = request.app.state.sync_engine
    db = request.app.state.db
    latest_health = await db.get_latest_health()
    sync_status = engine.status
    return {
        "shadowHealthy": True,
        "machineOnline": engine.machine_online,
        "lastHealthCheck": latest_health,
        "sync": sync_status,
    }


@router.get("/health/history")
async def get_health_history(request: Request, limit: int = Query(100, ge=1, le=1000)):
    db = request.app.state.db
    history = await db.get_health_history(limit=limit)
    return {"data": history, "count": len(history)}
