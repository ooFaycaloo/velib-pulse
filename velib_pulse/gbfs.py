"""Lecture du flux GBFS public de Vélib' Métropole et mise à plat des enregistrements."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .config import GBFS_BASE

STATUS_COLUMNS = ["station_id", "station_code", "polled_at", "last_reported", "num_bikes_available",
                  "num_mechanical", "num_ebike", "num_docks_available", "is_installed", "is_renting",
                  "is_returning"]
INFO_COLUMNS = ["station_id", "station_code", "name", "lat", "lon", "capacity", "updated_at"]


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def _types(raw: dict) -> tuple[int, int]:
    mech = ebike = 0
    for t in raw.get("num_bikes_available_types") or []:
        mech += int(t.get("mechanical", 0))
        ebike += int(t.get("ebike", 0))
    return mech, ebike


def flatten_status(raw: dict, polled_at: datetime) -> dict:
    mech, ebike = _types(raw)
    return {
        "station_id": int(raw["station_id"]),
        "station_code": str(raw.get("stationCode", "")),
        "polled_at": polled_at,
        "last_reported": _utc(raw["last_reported"]) if raw.get("last_reported") else polled_at,
        "num_bikes_available": int(raw.get("num_bikes_available", raw.get("numBikesAvailable", 0))),
        "num_mechanical": mech,
        "num_ebike": ebike,
        "num_docks_available": int(raw.get("num_docks_available", raw.get("numDocksAvailable", 0))),
        "is_installed": int(raw.get("is_installed", 1)),
        "is_renting": int(raw.get("is_renting", 1)),
        "is_returning": int(raw.get("is_returning", 1)),
    }


def flatten_info(raw: dict, updated_at: datetime) -> dict:
    return {
        "station_id": int(raw["station_id"]),
        "station_code": str(raw.get("stationCode", "")),
        "name": raw.get("name", ""),
        "lat": float(raw["lat"]),
        "lon": float(raw["lon"]),
        "capacity": int(raw.get("capacity", 0)),
        "updated_at": updated_at,
    }


class GBFSClient:
    def __init__(self, base: str = GBFS_BASE, timeout: float = 20):
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=timeout, headers={"User-Agent": "velib-pulse/1.0"})

    def _get(self, feed: str) -> dict:
        r = self.http.get(f"{self.base}/{feed}.json")
        r.raise_for_status()
        return r.json()

    def station_status(self) -> list[dict]:
        polled_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        return [flatten_status(s, polled_at) for s in self._get("station_status")["data"]["stations"]]

    def station_information(self) -> list[dict]:
        now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        return [flatten_info(s, now) for s in self._get("station_information")["data"]["stations"]]
