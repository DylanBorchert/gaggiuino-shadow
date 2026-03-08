from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/shots", tags=["shots"])


@router.get("")
async def get_shots(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    profileName: str | None = Query(None),
):
    db = request.app.state.db
    engine = request.app.state.sync_engine
    shots = await db.get_shots(limit=limit, offset=offset, profile_name=profileName)
    summaries = []
    for s in shots:
        d = dict(s["data"])
        d.pop("datapoints", None)
        profile = d.get("profile")
        if isinstance(profile, dict):
            d["profile"] = {k: v for k, v in profile.items() if k != "phases"}
        summaries.append(d)
    return {
        "data": summaries,
        "count": len(summaries),
        "machineOnline": engine.machine_online,
    }


@router.get("/latest")
async def get_latest_shot(request: Request):
    db = request.app.state.db
    engine = request.app.state.sync_engine
    shot = await db.get_latest_shot()
    if not shot:
        raise HTTPException(status_code=404, detail="No shots synced yet")
    return {
        **shot["data"],
        "syncedAt": shot["syncedAt"],
        "machineOnline": engine.machine_online,
    }


@router.get("/stats")
async def get_shot_stats(request: Request):
    db = request.app.state.db
    stats = await db.get_shot_stats()
    return {"data": stats}


@router.get("/{id}")
async def get_shot(request: Request, id: int):
    db = request.app.state.db
    engine = request.app.state.sync_engine
    shot = await db.get_shot(id)
    if not shot:
        raise HTTPException(status_code=404, detail=f"Shot {id} not found")
    return {
        **shot["data"],
        "syncedAt": shot["syncedAt"],
        "machineOnline": engine.machine_online,
    }
