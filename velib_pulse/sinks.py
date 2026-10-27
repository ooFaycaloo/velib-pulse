"""Destinations des relevés : Kafka (production) ou ClickHouse en direct (développement)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import KAFKA_BOOTSTRAP, TOPIC_INFO, TOPIC_STATUS, clickhouse_client
from .gbfs import INFO_COLUMNS, STATUS_COLUMNS

log = logging.getLogger(__name__)
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def to_json(record: dict) -> bytes:
    """JSONEachRow compatible ClickHouse : dates au format 'YYYY-MM-DD hh:mm:ss'."""
    return json.dumps({k: (v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v)
                       for k, v in record.items()}, ensure_ascii=False).encode()


class KafkaSink:
    def __init__(self, bootstrap: str = KAFKA_BOOTSTRAP, producer=None):
        if producer is None:
            from confluent_kafka import Producer

            producer = Producer({"bootstrap.servers": bootstrap, "linger.ms": 200,
                                 "compression.type": "zstd", "enable.idempotence": True})
        self.producer = producer
        self.errors = 0

    def _on_delivery(self, err, msg):
        if err is not None:
            self.errors += 1
            log.error("échec de livraison Kafka : %s", err)

    def _send(self, topic: str, records: list[dict]):
        for r in records:
            # clé = station : tous les relevés d'une station vont dans la même partition (ordre garanti)
            self.producer.produce(topic, key=str(r["station_id"]).encode(), value=to_json(r),
                                  on_delivery=self._on_delivery)
            self.producer.poll(0)
        self.producer.flush(30)

    def write_status(self, records: list[dict]):
        self._send(TOPIC_STATUS, records)

    def write_information(self, records: list[dict]):
        self._send(TOPIC_INFO, records)


class ClickHouseSink:
    def __init__(self, client=None):
        self.client = client or clickhouse_client()
        self.ensure_schema()

    def ensure_schema(self):
        for stmt in (SQL_DIR / "01_raw_tables.sql").read_text().split(";"):
            body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if body:
                self.client.command(body)

    @staticmethod
    def _row(r: dict, cols: list[str]) -> list:
        # les horodatages internes sont en UTC « naïf » : on le rend explicite pour le client
        return [r[c].replace(tzinfo=timezone.utc) if isinstance(r[c], datetime) else r[c] for c in cols]

    def write_status(self, records: list[dict]):
        if records:
            self.client.insert("raw.station_status", [self._row(r, STATUS_COLUMNS) for r in records],
                               column_names=STATUS_COLUMNS)

    def write_information(self, records: list[dict]):
        if records:
            self.client.insert("raw.station_information", [self._row(r, INFO_COLUMNS) for r in records],
                               column_names=INFO_COLUMNS)
