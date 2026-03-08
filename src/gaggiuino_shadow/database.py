import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


def _to_camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camel_dict(d: dict) -> dict:
    return {_to_camel(k): v for k, v in d.items()}

SCHEMA = """
CREATE TABLE IF NOT EXISTS machine_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    is_online INTEGER NOT NULL,
    response_time_ms REAL
);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shots (
    shot_id INTEGER PRIMARY KEY,
    synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    duration REAL,
    profile_name TEXT,
    timestamp TEXT,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    category TEXT PRIMARY KEY,
    synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_status_history_timestamp ON status_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_shots_timestamp ON shots(timestamp);
CREATE INDEX IF NOT EXISTS idx_machine_health_timestamp ON machine_health(timestamp);
"""


class Database:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("Database initialized at %s", self._db_path)

    async def close(self):
        if self._db:
            await self._db.close()

    # -- Sync state --

    async def get_sync_state(self, key: str) -> str | None:
        async with self._db.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def set_sync_state(self, key: str, value: str):
        await self._db.execute(
            "INSERT INTO sync_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._db.commit()

    # -- Health --

    async def record_health_event(self, is_online: bool, response_time_ms: float | None = None):
        await self._db.execute(
            "INSERT INTO machine_health (is_online, response_time_ms) VALUES (?, ?)",
            (int(is_online), response_time_ms),
        )
        await self._db.commit()

    async def get_latest_health(self) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM machine_health ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return _camel_dict(dict(row)) if row else None

    async def get_health_history(self, limit: int = 100) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM machine_health ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            return [_camel_dict(dict(row)) async for row in cursor]

    # -- Status --

    async def save_status(self, data: dict):
        await self._db.execute(
            "INSERT INTO status_history (data) VALUES (?)",
            (json.dumps(data),),
        )
        await self._db.commit()

    async def get_latest_status(self) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM status_history ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            result = _camel_dict(dict(row))
            result["data"] = json.loads(result["data"])
            return result

    async def get_status_history(self, limit: int = 100, since: str | None = None) -> list[dict]:
        if since:
            query = "SELECT * FROM status_history WHERE timestamp >= ? ORDER BY id DESC LIMIT ?"
            params = (since, limit)
        else:
            query = "SELECT * FROM status_history ORDER BY id DESC LIMIT ?"
            params = (limit,)
        async with self._db.execute(query, params) as cursor:
            rows = []
            async for row in cursor:
                r = _camel_dict(dict(row))
                r["data"] = json.loads(r["data"])
                rows.append(r)
            return rows

    # -- Shots --

    async def save_shot(self, shot_id: int, data: dict):
        duration = data.get("duration")
        profile = data.get("profile", {})
        profile_name = profile.get("name") if isinstance(profile, dict) else None
        timestamp = data.get("timestamp")
        await self._db.execute(
            "INSERT OR REPLACE INTO shots (shot_id, duration, profile_name, timestamp, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (shot_id, duration, profile_name, timestamp, json.dumps(data)),
        )
        await self._db.commit()

    async def get_shot(self, shot_id: int) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM shots WHERE shot_id = ?", (shot_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            result = _camel_dict(dict(row))
            result["data"] = json.loads(result["data"])
            return result

    async def get_shots(
        self, limit: int = 20, offset: int = 0, profile_name: str | None = None
    ) -> list[dict]:
        if profile_name:
            query = (
                "SELECT * FROM shots WHERE profile_name = ? "
                "ORDER BY shot_id DESC LIMIT ? OFFSET ?"
            )
            params = (profile_name, limit, offset)
        else:
            query = "SELECT * FROM shots ORDER BY shot_id DESC LIMIT ? OFFSET ?"
            params = (limit, offset)
        async with self._db.execute(query, params) as cursor:
            rows = []
            async for row in cursor:
                r = _camel_dict(dict(row))
                r["data"] = json.loads(r["data"])
                rows.append(r)
            return rows

    async def get_latest_shot(self) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM shots ORDER BY shot_id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            result = _camel_dict(dict(row))
            result["data"] = json.loads(result["data"])
            return result

    async def get_shot_stats(self) -> dict:
        stats = {}
        async with self._db.execute("SELECT COUNT(*) as count FROM shots") as cursor:
            row = await cursor.fetchone()
            stats["totalShots"] = row["count"]

        async with self._db.execute(
            "SELECT AVG(duration) as avg_duration FROM shots WHERE duration IS NOT NULL"
        ) as cursor:
            row = await cursor.fetchone()
            stats["avgDurationMs"] = row["avg_duration"]

        async with self._db.execute(
            "SELECT profile_name as profileName, COUNT(*) as count FROM shots "
            "WHERE profile_name IS NOT NULL GROUP BY profile_name ORDER BY count DESC"
        ) as cursor:
            stats["shotsPerProfile"] = [dict(row) async for row in cursor]

        async with self._db.execute(
            "SELECT DATE(timestamp) as day, COUNT(*) as count FROM shots "
            "WHERE timestamp IS NOT NULL GROUP BY day ORDER BY day DESC LIMIT 30"
        ) as cursor:
            stats["shotsPerDay"] = [dict(row) async for row in cursor]

        # Cumulative water dispensed over time
        cumulative = 0.0
        ml_array = []
        ts_array = []
        async with self._db.execute("SELECT data FROM shots ORDER BY shot_id") as cursor:
            async for row in cursor:
                shot_data = json.loads(row["data"])
                datapoints = shot_data.get("datapoints", {})
                shot_weight = datapoints.get("shotWeight", [])
                if shot_weight:
                    cumulative += shot_weight[-1] / 10
                ml_array.append(round(cumulative, 1))
                ts_array.append(shot_data.get("timestamp"))
        stats["totalWaterDispensedMl"] = round(cumulative, 1)
        stats["waterDispensed"] = {"ml": ml_array, "timestamp": ts_array}

        return stats

    # -- Profiles --

    async def save_profile(self, profile_id: str, name: str, data: dict):
        await self._db.execute(
            "INSERT OR REPLACE INTO profiles (profile_id, name, data) VALUES (?, ?, ?)",
            (profile_id, name, json.dumps(data)),
        )
        await self._db.commit()

    async def get_profiles(self) -> list[dict]:
        async with self._db.execute("SELECT * FROM profiles ORDER BY name") as cursor:
            rows = []
            async for row in cursor:
                r = _camel_dict(dict(row))
                r["data"] = json.loads(r["data"])
                rows.append(r)
            return rows

    async def get_profile(self, profile_id: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM profiles WHERE profile_id = ?", (profile_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            result = _camel_dict(dict(row))
            result["data"] = json.loads(result["data"])
            return result

    # -- Settings --

    async def save_settings(self, category: str, data: dict):
        await self._db.execute(
            "INSERT OR REPLACE INTO settings (category, data, synced_at) "
            "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (category, json.dumps(data)),
        )
        await self._db.commit()

    async def get_settings(self, category: str | None = None) -> dict | list[dict]:
        if category:
            async with self._db.execute(
                "SELECT * FROM settings WHERE category = ?", (category,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                result = _camel_dict(dict(row))
                result["data"] = json.loads(result["data"])
                return result
        else:
            async with self._db.execute("SELECT * FROM settings ORDER BY category") as cursor:
                rows = []
                async for row in cursor:
                    r = _camel_dict(dict(row))
                    r["data"] = json.loads(r["data"])
                    rows.append(r)
                return rows

    # -- Pruning --

    async def prune_status_history(self, max_age_days: int):
        await self._db.execute(
            "DELETE FROM status_history WHERE timestamp < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
            (f"-{max_age_days} days",),
        )
        await self._db.commit()

    async def prune_health_history(self, max_age_days: int):
        await self._db.execute(
            "DELETE FROM machine_health WHERE timestamp < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
            (f"-{max_age_days} days",),
        )
        await self._db.commit()
