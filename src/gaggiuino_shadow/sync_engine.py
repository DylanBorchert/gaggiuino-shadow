import asyncio
import logging
from datetime import datetime, timezone

from gaggiuino_shadow.config import Config
from gaggiuino_shadow.database import Database
from gaggiuino_shadow.machine_client import MachineClient

logger = logging.getLogger(__name__)

SETTINGS_CATEGORIES = ["boiler", "system", "theme", "display", "scales", "led", "versions"]


class SyncEngine:
    def __init__(self, config: Config, db: Database, client: MachineClient):
        self._config = config
        self._db = db
        self._client = client
        self._task: asyncio.Task | None = None
        self._last_shot_id: int | None = None
        self._last_full_sync: datetime | None = None
        self._force_sync = asyncio.Event()
        self.machine_online: bool = False
        self.last_poll: datetime | None = None

    async def start(self):
        stored_id = await self._db.get_sync_state("last_shot_id")
        if stored_id is not None:
            self._last_shot_id = int(stored_id)
            logger.info("Resuming from last shot ID: %d", self._last_shot_id)

        stored_sync = await self._db.get_sync_state("last_full_sync")
        if stored_sync:
            self._last_full_sync = datetime.fromisoformat(stored_sync)

        self._task = asyncio.create_task(self._run())
        logger.info("Sync engine started (poll=%ds, full_sync=%ds)",
                     self._config.poll_interval, self._config.full_sync_interval)

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Sync engine stopped")

    def trigger_sync(self):
        self._force_sync.set()

    @property
    def status(self) -> dict:
        return {
            "machineOnline": self.machine_online,
            "lastPoll": self.last_poll.isoformat() if self.last_poll else None,
            "lastShotId": self._last_shot_id,
            "lastFullSync": self._last_full_sync.isoformat() if self._last_full_sync else None,
            "pollInterval": self._config.poll_interval,
            "fullSyncInterval": self._config.full_sync_interval,
        }

    async def _run(self):
        while True:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sync cycle error")

            interval = self._config.poll_interval if self.machine_online else self._config.poll_interval * 2
            try:
                await asyncio.wait_for(self._force_sync.wait(), timeout=interval)
                self._force_sync.clear()
                logger.info("Forced sync triggered")
            except asyncio.TimeoutError:
                pass

    async def _poll_cycle(self):
        was_online = self.machine_online
        online = await self._client.check_health()
        self.machine_online = online
        self.last_poll = datetime.now(timezone.utc)

        if online != was_online:
            await self._db.record_health_event(online, self._client.last_response_time_ms)
            logger.info("Machine went %s", "online" if online else "offline")

        if not online:
            return

        # Poll status
        status = await self._client.get_status()
        if status:
            await self._db.save_status(status)

        # Detect new shots
        latest_id = await self._client.get_latest_shot_id()
        if latest_id is not None and latest_id != self._last_shot_id:
            await self._sync_new_shots(latest_id)

        # Periodic full sync
        if self._should_full_sync():
            await self._sync_profiles()
            await self._sync_all_settings()
            await self._prune_old_data()
            self._last_full_sync = datetime.now(timezone.utc)
            await self._db.set_sync_state("last_full_sync", self._last_full_sync.isoformat())

    async def _sync_new_shots(self, latest_id: int):
        start_id = (self._last_shot_id or 0) + 1
        synced = 0
        not_found_streak = 0

        for shot_id in range(start_id, latest_id + 1):
            shot_data = await self._client.get_shot(shot_id)
            if shot_data:
                await self._db.save_shot(shot_id, shot_data)
                synced += 1
                not_found_streak = 0
            else:
                not_found_streak += 1
                if not_found_streak >= 5:
                    break

        # Always sync the latest even if we hit gaps
        if synced == 0 or latest_id > start_id + synced:
            shot_data = await self._client.get_shot(latest_id)
            if shot_data:
                await self._db.save_shot(latest_id, shot_data)
                synced += 1

        self._last_shot_id = latest_id
        await self._db.set_sync_state("last_shot_id", str(latest_id))
        logger.info("Synced %d new shot(s), latest ID: %d", synced, latest_id)

    async def _sync_profiles(self):
        profiles = await self._client.get_profiles()
        if not profiles:
            return
        for p in profiles:
            pid = p.get("id") or p.get("profile_id") or str(hash(p.get("name", "")))
            name = p.get("name", "Unknown")
            await self._db.save_profile(str(pid), name, p)
        logger.info("Synced %d profiles", len(profiles))

    async def _sync_all_settings(self):
        for category in SETTINGS_CATEGORIES:
            data = await self._client.get_settings(category)
            if data:
                await self._db.save_settings(category, data)
        logger.info("Synced all settings categories")

    def _should_full_sync(self) -> bool:
        if self._last_full_sync is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_full_sync).total_seconds()
        return elapsed >= self._config.full_sync_interval

    async def _prune_old_data(self):
        await self._db.prune_status_history(self._config.status_history_max_age_days)
        await self._db.prune_health_history(self._config.health_history_max_age_days)
        logger.debug("Pruned old status and health history")
