import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gaggiuino_shadow.config import Config
from gaggiuino_shadow.database import Database
from gaggiuino_shadow.machine_client import MachineClient
from gaggiuino_shadow.sync_engine import SyncEngine
from gaggiuino_shadow.routes import shots, profiles, settings, status, sync, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config()

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    db = Database(config.db_path)
    await db.connect()

    client = MachineClient(config.gaggiuino_url)
    await client.connect()

    engine = SyncEngine(config, db, client)
    await engine.start()

    app.state.config = config
    app.state.db = db
    app.state.client = client
    app.state.sync_engine = engine

    logger.info("Gaggiuino Shadow started — tracking %s", config.gaggiuino_url)
    yield

    await engine.stop()
    await client.close()
    await db.close()
    logger.info("Gaggiuino Shadow stopped")


app = FastAPI(
    title="Gaggiuino Shadow",
    description="Persistent shadow API for Gaggiuino espresso machine",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(status.router)
app.include_router(shots.router)
app.include_router(profiles.router)
app.include_router(settings.router)
app.include_router(system.router)
app.include_router(sync.router)


@app.get("/")
async def root():
    return {
        "service": "gaggiuino-shadow",
        "version": "0.1.0",
        "docs": "/docs",
    }
