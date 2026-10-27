import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from velib_pulse.gbfs import flatten_info, flatten_status  # noqa: E402
from velib_pulse.simulator import NetworkSimulator  # noqa: E402
from velib_pulse.sinks import KafkaSink, to_json  # noqa: E402
from velib_pulse.tools import FORBIDDEN  # noqa: E402

# même structure que le flux réel station_status.json
RAW_STATUS = {
    "station_id": 213688169, "stationCode": "16107", "num_bikes_available": 10, "numBikesAvailable": 10,
    "num_bikes_available_types": [{"mechanical": 7}, {"ebike": 3}], "num_docks_available": 25,
    "numDocksAvailable": 25, "is_installed": 1, "is_returning": 1, "is_renting": 1,
    "last_reported": 1793038700, "station_opening_hours": None,
}
RAW_INFO = {"station_id": 213688169, "stationCode": "16107", "name": "Benjamin Godard - Victor Hugo",
            "lat": 48.865983, "lon": 2.275725, "capacity": 35, "station_opening_hours": None}


def test_flatten_status():
    polled = datetime(2026, 10, 26, 19, 0)
    r = flatten_status(RAW_STATUS, polled)
    assert (r["num_mechanical"], r["num_ebike"], r["num_docks_available"]) == (7, 3, 25)
    assert r["station_code"] == "16107" and r["polled_at"] == polled
    assert r["last_reported"] == datetime(2026, 10, 26, 18, 18, 20)  # epoch 1793038700 en UTC


def test_flatten_info():
    r = flatten_info(RAW_INFO, datetime(2026, 10, 26))
    assert r["capacity"] == 35 and r["name"].startswith("Benjamin")


def test_simulator_is_deterministic():
    now = datetime(2026, 10, 26, 18, 0)
    a, b = NetworkSimulator(50, seed=3, now=now), NetworkSimulator(50, seed=3, now=now)
    assert a.snapshot(now) == b.snapshot(now)


def test_simulator_respects_capacity():
    sim = NetworkSimulator(80, seed=1, now=datetime(2026, 10, 26, 18, 0))
    for _, snap in sim.history(24, step_minutes=60):
        for r in snap:
            cap = next(s.capacity for s in sim.stations if s.station_id == r["station_id"])
            assert r["num_bikes_available"] + r["num_docks_available"] <= cap
            assert r["num_mechanical"] + r["num_ebike"] == r["num_bikes_available"]


def test_frozen_station_stops_reporting():
    now = datetime(2026, 10, 26, 18, 0)
    sim = NetworkSimulator(150, seed=42, now=now)
    inc = next(i for i in sim.incidents if i.kind == "STALE_DATA")
    st = next(s for s in sim.stations if s.station_id == inc.station_id)
    r1 = sim.status(st, inc.start + timedelta(minutes=10))
    r2 = sim.status(st, now)
    assert r1["last_reported"] == r2["last_reported"] < inc.start
    assert r1["num_bikes_available"] == r2["num_bikes_available"]


def test_to_json_uses_clickhouse_datetime_format():
    payload = json.loads(to_json({"polled_at": datetime(2026, 10, 26, 19, 0, 5), "x": 1}))
    assert payload == {"polled_at": "2026-10-26 19:00:05", "x": 1}


class FakeProducer:
    def __init__(self):
        self.messages = []

    def produce(self, topic, key, value, on_delivery=None):
        self.messages.append((topic, key, value))

    def poll(self, _):
        return 0

    def flush(self, _):
        return 0


def test_kafka_sink_keys_by_station():
    fake = FakeProducer()
    KafkaSink(producer=fake).write_status([flatten_status(RAW_STATUS, datetime(2026, 10, 26, 19, 0))])
    topic, key, value = fake.messages[0]
    assert topic == "velib.station_status" and key == b"213688169"
    assert json.loads(value)["num_ebike"] == 3


def test_sql_guard_blocks_writes_and_table_functions():
    for bad in ("DROP TABLE x", "SELECT * FROM file('/etc/passwd')", "SELECT * FROM url('http://x', CSV)",
                "INSERT INTO t VALUES (1)", "SELECT * FROM remote('h', db.t)", "SELECT * FROM system.users"):
        assert FORBIDDEN.search(bad), bad
    assert not FORBIDDEN.search("SELECT station_code, count() FROM analytics.mart_station_anomalies GROUP BY 1")
