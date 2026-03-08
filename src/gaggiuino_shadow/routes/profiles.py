from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
async def get_profiles(request: Request):
    db = request.app.state.db
    engine = request.app.state.sync_engine
    profiles = await db.get_profiles()
    return {
        "data": profiles,
        "count": len(profiles),
        "machineOnline": engine.machine_online,
    }


@router.get("/{profileId}")
async def get_profile(request: Request, profileId: str):
    db = request.app.state.db
    engine = request.app.state.sync_engine
    profile = await db.get_profile(profileId)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profileId} not found")
    return {
        "data": profile["data"],
        "syncedAt": profile["syncedAt"],
        "machineOnline": engine.machine_online,
    }
