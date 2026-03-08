import logging
import time

from gaggiuino_api import GaggiuinoAPI
from gaggiuino_api.exceptions import (
    GaggiuinoConnectionError,
    GaggiuinoConnectionTimeoutError,
    GaggiuinoEndpointNotFoundError,
    GaggiuinoError,
)

logger = logging.getLogger(__name__)

_CONN_ERRORS = (GaggiuinoConnectionError, GaggiuinoConnectionTimeoutError, GaggiuinoError, OSError)


class MachineClient:
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._api: GaggiuinoAPI | None = None
        self.is_online: bool = False
        self.last_response_time_ms: float | None = None

    @property
    def _api_base(self) -> str:
        return f"{self._base_url}/api"

    async def connect(self):
        self._api = GaggiuinoAPI(base_url=self._base_url)
        await self._api.connect()

    async def close(self):
        if self._api:
            await self._api.disconnect()

    async def check_health(self) -> bool:
        try:
            start = time.monotonic()
            healthy = await self._api.healthy()
            self.last_response_time_ms = (time.monotonic() - start) * 1000
            self.is_online = healthy
            return healthy
        except _CONN_ERRORS:
            self.is_online = False
            self.last_response_time_ms = None
            return False

    async def get_status(self) -> dict | None:
        try:
            url = f"{self._api_base}/system/status"
            result = await self._api.get(url)
            if result and isinstance(result, list):
                return result[0]
            return result
        except _CONN_ERRORS as e:
            logger.warning("Failed to get status: %s", e)
            return None

    async def get_latest_shot_id(self) -> int | None:
        try:
            url = f"{self._api_base}/shots/latest"
            result = await self._api.get(url)
            if result and isinstance(result, list):
                return int(result[0].get("lastShotId", 0))
            return None
        except _CONN_ERRORS as e:
            logger.warning("Failed to get latest shot ID: %s", e)
            return None

    async def get_shot(self, shot_id: int) -> dict | None:
        try:
            url = f"{self._api_base}/shots/{shot_id}"
            return await self._api.get(url)
        except GaggiuinoEndpointNotFoundError:
            logger.debug("Shot %d not found", shot_id)
            return None
        except _CONN_ERRORS as e:
            logger.warning("Failed to get shot %d: %s", shot_id, e)
            return None

    async def get_profiles(self) -> list[dict] | None:
        try:
            url = f"{self._api_base}/profiles/all"
            return await self._api.get(url)
        except _CONN_ERRORS as e:
            logger.warning("Failed to get profiles: %s", e)
            return None

    async def get_settings(self, category: str) -> dict | None:
        valid = ["boiler", "system", "theme", "display", "scales", "led", "versions"]
        if category not in valid:
            return None
        try:
            url = f"{self._api_base}/settings/{category}"
            return await self._api.get(url)
        except _CONN_ERRORS as e:
            logger.warning("Failed to get %s settings: %s", category, e)
            return None
