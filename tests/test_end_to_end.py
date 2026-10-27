"""Test de bout en bout sur un vrai moteur ClickHouse (chDB) : simulateur → ClickHouse → dbt → outils → MCP."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    pytest.importorskip("chdb")
    port = _free_port()
    server = subprocess.Popen([sys.executable, str(ROOT / "devtools/chdb_http_server.py"),
                               "--path", str(tmp_path_factory.mktemp("ch")), "--port", str(port)],
                              env={**os.environ, "TZ": "UTC"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    os.environ["CLICKHOUSE_HOST"], os.environ["CLICKHOUSE_PORT"] = "127.0.0.1", str(port)
    import velib_pulse.config as cfg
    cfg.CH_HOST, cfg.CH_PORT = "127.0.0.1", port

    from velib_pulse.simulator import NetworkSimulator
    from velib_pulse.sinks import ClickHouseSink

    sim = NetworkSimulator(n_stations=60, seed=7)
    sink = ClickHouseSink()
    sink.write_information(sim.information())
    sink.write_status([r for _, snap in sim.history(30) for r in snap])
    r = subprocess.run(["dbt", "build", "--quiet"], cwd=ROOT / "dbt", capture_output=True, text=True,
                       env={**os.environ, "DBT_PROFILES_DIR": str(ROOT / "dbt")})
    assert r.returncode == 0, r.stdout[-2000:]
    yield sim, port
    server.terminate()


def test_all_injected_incidents_are_detected(warehouse):
    sim, _ = warehouse
    from velib_pulse.tools import PulseTools

    found = {(a["station_code"], a["anomaly_type"]) for a in PulseTools().list_anomalies()}
    expected = {(i.station_code, i.kind) for i in sim.incidents}
    assert expected <= found
    assert len(found - expected) == 0


def test_tools_and_brief(warehouse):
    from velib_pulse.agent import fallback_brief
    from velib_pulse.tools import PulseTools

    t = PulseTools()
    assert t.network_status()["now"]["stations_reporting"] == 60
    assert t.station_history("00000").get("error")
    assert "error" in t.query_sql("DROP DATABASE analytics")
    brief = fallback_brief(t)
    assert "## Maintenance" in brief and "station muette" in brief


def test_report_builds(warehouse, tmp_path):
    from velib_pulse.report import build

    out = build(str(tmp_path / "r.html"), "données de test")
    html = Path(out).read_text()
    assert "Vélib Pulse" in html and 'id="map"' in html


def test_mcp_server_lists_tools(warehouse):
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, port = warehouse

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "velib_pulse.mcp_server"], cwd=str(ROOT),
                                       env={**os.environ, "CLICKHOUSE_HOST": "127.0.0.1", "CLICKHOUSE_PORT": str(port)})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("list_anomalies", {"anomaly_type": "STALE_DATA"})
                return names, res.content[0].text

    names, text = anyio.run(run)
    assert {"network_status", "list_anomalies", "rebalancing_plan", "station_history", "query_sql"} <= names
    assert "STALE_DATA" in text
