from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
async def get_sync_status(request: Request):
    engine = request.app.state.sync_engine
    return engine.status


@router.post("/trigger")
async def trigger_sync(request: Request):
    engine = request.app.state.sync_engine
    engine.trigger_sync()
    return JSONResponse(
        status_code=202,
        content={"message": "Sync triggered", "machineOnline": engine.machine_online},
    )
