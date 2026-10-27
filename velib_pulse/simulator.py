"""Simulateur réaliste d'un réseau de stations Vélib' (même format que le flux GBFS).

Sert à la démo hors ligne et à l'évaluation : on y injecte des incidents connus
(station figée, bornettes HS, station fermée, station toujours vide / pleine)
et on mesure si le pipeline les retrouve.

Le simulateur est déterministe : l'état d'une station à l'instant t ne dépend que de
(graine, station, t), ce qui permet de rejouer n'importe quelle période.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

STREETS = ["Rivoli", "Saint-Antoine", "Oberkampf", "Belleville", "Ménilmontant", "Voltaire", "République",
           "Saint-Michel", "Saint-Germain", "Montparnasse", "Alésia", "Convention", "Vaugirard", "Grenelle",
           "Passy", "Wagram", "Clichy", "Batignolles", "Pigalle", "Magenta", "Lafayette", "Jaurès",
           "Bercy", "Tolbiac", "Gobelins", "Mouffetard", "Daumesnil", "Nation", "Gambetta", "Pyrénées"]
PLACES = ["Mairie", "Gare", "Marché", "Métro", "Square", "Église", "Lycée", "Parc", "Place", "Théâtre"]


@dataclass
class Station:
    station_id: int
    station_code: str
    name: str
    lat: float
    lon: float
    capacity: int
    profile: str
    phases: tuple[float, float, float]


@dataclass
class Incident:
    station_id: int
    station_code: str
    kind: str  # STALE_DATA | DOCKS_UNAVAILABLE | OUT_OF_SERVICE | CHRONIC_EMPTY | CHRONIC_FULL
    start: datetime
    params: dict = field(default_factory=dict)


def _gauss(h: float, center: float, width: float) -> float:
    d = min(abs(h - center), 24 - abs(h - center))
    return math.exp(-(d * d) / (2 * width * width))


PROFILES = {
    # base, [(amplitude, centre, largeur)] — occupation (vélos / capacité) selon l'heure locale
    "residential": (0.62, [(-0.45, 8.5, 1.4), (+0.10, 20.0, 2.0)]),
    "business": (0.35, [(+0.45, 12.5, 3.2), (-0.10, 20.5, 2.0)]),
    "leisure": (0.50, [(-0.25, 15.5, 2.5), (+0.10, 10.0, 1.5)]),
    "balanced": (0.50, [(+0.08, 9.0, 2.0), (-0.08, 18.5, 2.0)]),
}


class NetworkSimulator:
    def __init__(self, n_stations: int = 150, seed: int = 42, now: datetime | None = None):
        self.rng = random.Random(seed)
        self.seed = seed
        self.now = (now or datetime.now(timezone.utc).replace(tzinfo=None)).replace(second=0, microsecond=0)
        self.stations = [self._make_station(i) for i in range(n_stations)]
        self.incidents = self._plan_incidents()
        self._by_station = {i.station_id: i for i in self.incidents}

    def _make_station(self, i: int) -> Station:
        r = self.rng
        code = f"{r.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])}{i:03d}"
        return Station(
            station_id=100_000_000 + i * 7919,
            station_code=code,
            name=f"{r.choice(PLACES)} {r.choice(STREETS)} - {r.choice(STREETS)}",
            lat=round(r.uniform(48.822, 48.898), 6),
            lon=round(r.uniform(2.262, 2.408), 6),
            capacity=r.choice([18, 20, 22, 25, 28, 30, 35, 40, 45, 50, 60]),
            profile=r.choices(list(PROFILES), weights=[4, 3, 1, 2])[0],
            phases=(r.uniform(0, 6.28), r.uniform(0, 6.28), r.uniform(0, 6.28)),
        )

    def _plan_incidents(self) -> list[Incident]:
        picks = self.rng.sample(self.stations, 10)
        plan = [("STALE_DATA", 7), ("STALE_DATA", 4), ("STALE_DATA", 2.5),
                ("DOCKS_UNAVAILABLE", 6), ("DOCKS_UNAVAILABLE", 3.5),
                ("OUT_OF_SERVICE", 2),
                ("CHRONIC_EMPTY", 60), ("CHRONIC_EMPTY", 60),
                ("CHRONIC_FULL", 60), ("CHRONIC_FULL", 60)]
        out = []
        for st, (kind, hours_ago) in zip(picks, plan):
            params = {"broken_share": 0.5} if kind == "DOCKS_UNAVAILABLE" else {}
            out.append(Incident(st.station_id, st.station_code, kind,
                                self.now - timedelta(hours=hours_ago), params))
        return out

    # ------------------------------------------------------------------ état

    def _ratio(self, st: Station, t: datetime) -> float:
        local = t.replace(tzinfo=ZoneInfo("UTC")).astimezone(PARIS)
        h = local.hour + local.minute / 60
        base, bumps = PROFILES[st.profile]
        if local.weekday() >= 5:  # week-end : profils lissés
            bumps = [(a * 0.4, c + 2, w * 1.5) for a, c, w in bumps]
        x = base + sum(a * _gauss(h, c, w) for a, c, w in bumps)
        minutes = (t - datetime(2026, 1, 1)).total_seconds() / 60
        p1, p2, p3 = st.phases
        x += 0.05 * math.sin(minutes / 37 + p1) + 0.04 * math.sin(minutes / 113 + p2) + 0.03 * math.sin(minutes / 11 + p3)
        return min(1.0, max(0.0, x))

    def _jitter(self, st: Station, t: datetime) -> int:
        h = hashlib.blake2b(f"{self.seed}:{st.station_id}:{t:%Y%m%d%H%M}".encode(), digest_size=2).digest()
        return h[0] % 3 - 1  # -1, 0 ou +1

    def status(self, st: Station, t: datetime) -> dict:
        inc = self._by_station.get(st.station_id)
        last_reported = t - timedelta(seconds=(st.station_id + t.minute) % 50)
        is_renting = is_returning = 1
        broken = 0
        ratio = self._ratio(st, t)

        if inc and t >= inc.start:
            if inc.kind == "STALE_DATA":
                return self.status_frozen(st, inc, t)
            if inc.kind == "DOCKS_UNAVAILABLE":
                broken = int(st.capacity * inc.params["broken_share"])
            if inc.kind == "OUT_OF_SERVICE":
                is_renting = is_returning = 0
        if inc and inc.kind == "CHRONIC_EMPTY":
            ratio = 0.015 if self._jitter(st, t) != 1 else 0.08
        if inc and inc.kind == "CHRONIC_FULL":
            ratio = 0.99 if self._jitter(st, t) != 1 else 0.9

        usable = st.capacity - broken
        bikes = max(0, min(usable, round(ratio * usable) + (self._jitter(st, t) if ratio not in (0.015, 0.99) else 0)))
        ebike = round(bikes * (0.25 + 0.15 * math.sin(st.phases[0])))
        return {
            "station_id": st.station_id, "station_code": st.station_code, "polled_at": t,
            "last_reported": last_reported, "num_bikes_available": bikes,
            "num_mechanical": bikes - ebike, "num_ebike": ebike,
            "num_docks_available": usable - bikes,
            "is_installed": 1, "is_renting": is_renting, "is_returning": is_returning,
        }

    def status_frozen(self, st: Station, inc: Incident, t: datetime) -> dict:
        """Station qui ne remonte plus : dernières valeurs répétées, last_reported figé."""
        frozen = self.status(st, inc.start - timedelta(minutes=1))
        return {**frozen, "polled_at": t, "last_reported": frozen["last_reported"]}

    def snapshot(self, t: datetime) -> list[dict]:
        return [self.status(st, t) for st in self.stations]

    def information(self, t: datetime | None = None) -> list[dict]:
        t = t or self.now
        return [{"station_id": s.station_id, "station_code": s.station_code, "name": s.name,
                 "lat": s.lat, "lon": s.lon, "capacity": s.capacity, "updated_at": t} for s in self.stations]

    def history(self, hours: float, step_minutes: int = 5):
        t = self.now - timedelta(hours=hours)
        while t <= self.now:
            yield t, self.snapshot(t)
            t += timedelta(minutes=step_minutes)

    def ground_truth(self) -> list[dict]:
        return [{"station_id": i.station_id, "station_code": i.station_code, "anomaly_type": i.kind,
                 "start": i.start.isoformat()} for i in self.incidents]
