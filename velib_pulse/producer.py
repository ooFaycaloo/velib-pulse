"""Producteur : interroge le flux GBFS (ou le simulateur) et publie les relevés.

Exemples :
    # production : flux réel → Redpanda/Kafka, toutes les 60 s
    python -m velib_pulse.producer --source live --sink kafka --interval 60

    # démo hors ligne : 48 h d'historique simulé écrites directement dans ClickHouse
    python -m velib_pulse.producer --source simulate --sink clickhouse --backfill-hours 48 --once
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .sinks import ClickHouseSink, KafkaSink

log = logging.getLogger("velib_pulse.producer")


def run(source: str, sink_name: str, interval: int, backfill_hours: float, once: bool,
        n_stations: int, seed: int, truth_path: str | None):
    sink = KafkaSink() if sink_name == "kafka" else ClickHouseSink()

    if source == "simulate":
        from .simulator import NetworkSimulator

        sim = NetworkSimulator(n_stations=n_stations, seed=seed)
        sink.write_information(sim.information())
        if truth_path:
            Path(truth_path).parent.mkdir(parents=True, exist_ok=True)
            Path(truth_path).write_text(json.dumps(sim.ground_truth(), indent=2, ensure_ascii=False))
        if backfill_hours:
            batch, n = [], 0
            for _, snap in sim.history(backfill_hours):
                batch += snap
                if len(batch) >= 20_000:
                    sink.write_status(batch); n += len(batch); batch = []
            sink.write_status(batch); n += len(batch)
            log.info("historique simulé : %s relevés sur %s h", n, backfill_hours)
        if once:
            return
        while True:
            t = datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
            sink.write_status(sim.snapshot(t))
            log.info("relevé simulé %s", t)
            time.sleep(interval)

    from .gbfs import GBFSClient

    gbfs = GBFSClient()
    sink.write_information(gbfs.station_information())
    last_info = datetime.now(timezone.utc).replace(tzinfo=None)
    while True:
        try:
            records = gbfs.station_status()
            sink.write_status(records)
            log.info("%s stations publiées", len(records))
            if datetime.now(timezone.utc).replace(tzinfo=None) - last_info > timedelta(hours=6):
                sink.write_information(gbfs.station_information())
                last_info = datetime.now(timezone.utc).replace(tzinfo=None)
        except Exception:  # un appel raté ne doit pas arrêter le flux
            log.exception("échec de l'interrogation GBFS, nouvel essai au prochain cycle")
        if once:
            return
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["live", "simulate"], default="live")
    ap.add_argument("--sink", choices=["kafka", "clickhouse"], default="kafka")
    ap.add_argument("--interval", type=int, default=60, help="secondes entre deux relevés")
    ap.add_argument("--backfill-hours", type=float, default=0, help="simulateur : historique à générer")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--stations", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--truth", default="data/ground_truth.json", help="simulateur : incidents injectés")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.source, args.sink, args.interval, args.backfill_hours, args.once, args.stations, args.seed,
        args.truth)


if __name__ == "__main__":
    main()
