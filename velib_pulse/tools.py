"""Outils de lecture des marts dbt, partagés par l'agent, le serveur MCP et le rapport."""
from __future__ import annotations

import re

from .config import CH_DB_MARTS as DB
from .config import clickhouse_client

FORBIDDEN = re.compile(
    r"\b(insert|alter|create|drop|truncate|rename|delete|update|optimize|attach|detach|kill|grant|revoke|"
    r"system|set|use|exchange|file|url|s3|hdfs|remote\w*|mysql|postgresql|executable|input|jdbc|odbc)\b",
    re.IGNORECASE)


def _rows(result) -> list[dict]:
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


class PulseTools:
    def __init__(self, client=None):
        self.ch = client or clickhouse_client()

    def q(self, sql: str, params: dict | None = None) -> list[dict]:
        return _rows(self.ch.query(sql, parameters=params or {}))

    # ---------------------------------------------------------------- outils
    def network_status(self) -> dict:
        """État du réseau au dernier quart d'heure, comparé à la même heure la veille."""
        rows = self.q(f"""
            SELECT bucket, stations_reporting, bikes_available, ebikes_available, docks_available,
                   stations_empty, stations_full, stations_stale, share_stations_usable
            FROM {DB}.mart_network_kpis_15min
            WHERE bucket IN (SELECT max(bucket) FROM {DB}.mart_network_kpis_15min)
               OR bucket IN (SELECT max(bucket) - INTERVAL 1 DAY FROM {DB}.mart_network_kpis_15min)
            ORDER BY bucket DESC""")
        return {"now": rows[0] if rows else None, "yesterday_same_time": rows[1] if len(rows) > 1 else None}

    def list_anomalies(self, anomaly_type: str | None = None) -> list[dict]:
        """Anomalies actives, les plus prioritaires d'abord. Types : STALE_DATA, OUT_OF_SERVICE,
        DOCKS_UNAVAILABLE, CHRONIC_EMPTY, CHRONIC_FULL."""
        where = "WHERE anomaly_type = {t:String}" if anomaly_type else ""
        return self.q(f"""
            SELECT station_code, station_name, capacity, anomaly_type, severity, since,
                   round(metric_value, 3) AS metric_value, metric_label, priority_score
            FROM {DB}.mart_station_anomalies {where}
            ORDER BY multiIf(severity = 'critique', 0, severity = 'élevée', 1, 2), priority_score DESC""", {"t": anomaly_type} if anomaly_type else None)

    def rebalancing_plan(self, limit: int = 15) -> list[dict]:
        """Stations vides ou pleines à rééquilibrer maintenant, avec le nombre de vélos à déplacer."""
        return self.q(f"""
            SELECT station_code, station_name, capacity, action, bikes_to_move, usage_profile
            FROM {DB}.mart_rebalancing_needs ORDER BY bikes_to_move DESC LIMIT {{n:UInt32}}""",
                      {"n": min(int(limit), 100)})

    def station_history(self, station_code: str, hours: int = 24) -> dict:
        """Historique d'une station par quart d'heure (vélos, bornettes, retard de remontée)."""
        info = self.q(f"SELECT * FROM {DB}.dim_station WHERE station_code = {{c:String}}", {"c": station_code})
        if not info:
            return {"error": f"station {station_code} inconnue"}
        series = self.q(f"""
            SELECT bucket, round(avg_bikes, 1) AS bikes, round(avg_docks, 1) AS docks,
                   max_report_lag_minutes AS report_lag_min, share_closed
            FROM {DB}.int_station_status_15min
            WHERE station_id = {{id:UInt64}}
              AND bucket >= (SELECT max(bucket) FROM {DB}.int_station_status_15min) - INTERVAL {{h:UInt32}} HOUR
            ORDER BY bucket""", {"id": info[0]["station_id"], "h": min(int(hours), 168)})
        return {"station": info[0], "series": series}

    def query_sql(self, sql: str) -> list[dict] | dict:
        """SQL ClickHouse en lecture seule (SELECT / WITH) sur la base analytics. 200 lignes max."""
        stmt = sql.strip().rstrip(";")
        if ";" in stmt or not re.match(r"^(select|with)\b", stmt, re.IGNORECASE) or FORBIDDEN.search(stmt):
            return {"error": "seules les requêtes SELECT/WITH sur les tables d'analyse sont autorisées"}
        return self.q(f"SELECT * FROM ({stmt}) LIMIT 200")

    # ---------------------------------------------------------------- pour le rapport
    def network_series(self, hours: int = 48) -> list[dict]:
        return self.q(f"""
            SELECT bucket, bikes_available, stations_empty, stations_full, stations_faulty, share_stations_usable
            FROM {DB}.mart_network_kpis_15min
            WHERE bucket >= (SELECT max(bucket) FROM {DB}.mart_network_kpis_15min) - INTERVAL {{h:UInt32}} HOUR
            ORDER BY bucket""", {"h": hours})

    def stations_map(self) -> list[dict]:
        return self.q(f"""
            SELECT d.station_code AS station_code, d.station_name AS station_name, d.lat AS lat, d.lon AS lon,
                   d.capacity AS capacity,
                   multiIf(a.severity != '', a.severity, r.station_id != 0, 'rééquilibrage', 'ok') AS state,
                   a.anomaly_type AS anomaly_type
            FROM {DB}.dim_station AS d
            LEFT JOIN (SELECT station_id, argMax(severity, priority_score) AS severity,
                              argMax(anomaly_type, priority_score) AS anomaly_type
                       FROM {DB}.mart_station_anomalies GROUP BY station_id) AS a ON a.station_id = d.station_id
            LEFT JOIN {DB}.mart_rebalancing_needs AS r ON r.station_id = d.station_id""")


TOOL_NAMES = ["network_status", "list_anomalies", "rebalancing_plan", "station_history", "query_sql"]
