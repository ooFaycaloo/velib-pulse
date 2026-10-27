"""Serveur MCP : le réseau Vélib' interrogeable depuis Claude Desktop, Claude Code ou tout client MCP.

Lancement : python -m velib_pulse.mcp_server
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from .tools import PulseTools

tools = PulseTools()
server = MCPServer(
    name="velib-pulse",
    instructions=("Supervision temps réel du réseau Vélib'. network_status pour la vue d'ensemble, "
                  "list_anomalies pour les pannes, rebalancing_plan pour la régulation, station_history "
                  "pour enquêter sur une station, query_sql pour l'analyse libre (base analytics, lecture seule)."),
)


def _dump(x) -> str:
    return json.dumps(x, default=str, ensure_ascii=False)


@server.tool()
def network_status() -> str:
    """État du réseau au dernier quart d'heure, comparé à la veille même heure."""
    return _dump(tools.network_status())


@server.tool()
def list_anomalies(anomaly_type: str | None = None) -> str:
    """Anomalies actives. anomaly_type optionnel : STALE_DATA, OUT_OF_SERVICE, DOCKS_UNAVAILABLE,
    CHRONIC_EMPTY, CHRONIC_FULL."""
    return _dump(tools.list_anomalies(anomaly_type))


@server.tool()
def rebalancing_plan(limit: int = 15) -> str:
    """Stations vides ou pleines à rééquilibrer, avec le nombre de vélos à déplacer."""
    return _dump(tools.rebalancing_plan(limit))


@server.tool()
def station_history(station_code: str, hours: int = 24) -> str:
    """Historique par quart d'heure d'une station (code à 4-5 chiffres)."""
    return _dump(tools.station_history(station_code, hours))


@server.tool()
def query_sql(sql: str) -> str:
    """SQL ClickHouse en lecture seule sur la base analytics (marts dbt). 200 lignes max."""
    return _dump(tools.query_sql(sql))


if __name__ == "__main__":
    server.run("stdio")
