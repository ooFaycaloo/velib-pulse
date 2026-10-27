"""Configuration par variables d'environnement (valeurs par défaut = docker-compose local)."""
from __future__ import annotations

import os

GBFS_BASE = os.environ.get(
    "VELIB_GBFS_BASE", "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:19092")
TOPIC_STATUS = os.environ.get("VELIB_TOPIC_STATUS", "velib.station_status")
TOPIC_INFO = os.environ.get("VELIB_TOPIC_INFO", "velib.station_information")

CH_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
CH_USER = os.environ.get("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
CH_DB_RAW = os.environ.get("CLICKHOUSE_DB_RAW", "raw")
CH_DB_MARTS = os.environ.get("CLICKHOUSE_DB_MARTS", "analytics")


def clickhouse_client():
    import clickhouse_connect

    # compress=False : requis par le serveur de dev chDB, sans impact notable en local
    return clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, username=CH_USER,
                                         password=CH_PASSWORD, compress=False)
