"""Évaluation de bout en bout de la détection d'incidents.

Pour chaque graine : simulation de 48 h avec 10 incidents injectés → chargement ClickHouse →
`dbt build` → comparaison de `mart_station_anomalies` à la vérité terrain.
Mesures : précision, rappel, délai de détection (écart entre début réel et début estimé).

Usage : python eval/evaluate.py --seeds 1 2 3 4 5
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from velib_pulse.config import clickhouse_client  # noqa: E402
from velib_pulse.simulator import NetworkSimulator  # noqa: E402
from velib_pulse.sinks import ClickHouseSink  # noqa: E402

TIMED = {"STALE_DATA", "OUT_OF_SERVICE", "DOCKS_UNAVAILABLE"}  # incidents à date de début mesurable


def load(seed: int, hours: float, stations: int) -> NetworkSimulator:
    ch = clickhouse_client()
    ch.command("CREATE DATABASE IF NOT EXISTS raw")
    for t in ("station_status", "station_information"):
        ch.command(f"DROP TABLE IF EXISTS raw.{t}")
    sink = ClickHouseSink(ch)
    sim = NetworkSimulator(n_stations=stations, seed=seed)
    sink.write_information(sim.information())
    batch = []
    for _, snap in sim.history(hours):
        batch += snap
    sink.write_status(batch)
    return sim


def dbt_build():
    env = {**os.environ, "DBT_PROFILES_DIR": str(ROOT / "dbt")}
    r = subprocess.run(["dbt", "build", "--full-refresh", "--quiet"], cwd=ROOT / "dbt", env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--hours", type=float, default=48)
    ap.add_argument("--stations", type=int, default=150)
    ap.add_argument("--out", default="eval/report.md")
    args = ap.parse_args()

    per_type = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0})
    delays = defaultdict(list)
    rows = []
    for seed in args.seeds:
        sim = load(seed, args.hours, args.stations)
        dbt_build()
        res = clickhouse_client().query(
            "SELECT station_id, anomaly_type, since FROM analytics.mart_station_anomalies")
        detected = {(r[0], r[1]): r[2] for r in res.result_rows}
        truth = {(i.station_id, i.kind): i.start for i in sim.incidents}
        tp = fp = fn = 0
        for key, start in truth.items():
            if key in detected:
                per_type[key[1]]["tp"] += 1; tp += 1
                if key[1] in TIMED:
                    since = detected[key].replace(tzinfo=None) if isinstance(detected[key], datetime) else detected[key]
                    delays[key[1]].append(abs((since - start).total_seconds()) / 60)
            else:
                per_type[key[1]]["fn"] += 1; fn += 1
        for key in detected.keys() - truth.keys():
            per_type[key[1]]["fp"] += 1; fp += 1
        rows.append((seed, tp, fn, fp))
        print(f"graine {seed} : {tp} détectés, {fn} manqués, {fp} fausses alertes")

    tp = sum(r[1] for r in rows); fn = sum(r[2] for r in rows); fp = sum(r[3] for r in rows)
    lines = ["# Évaluation de la détection d'incidents", "",
             f"{len(args.seeds)} simulations × {args.stations} stations × {args.hours:g} h, 10 incidents injectés "
             "par simulation (3 stations muettes, 2 pannes de bornettes, 1 fermeture, 2 stations toujours vides, "
             "2 toujours pleines).", "",
             f"- **Rappel : {tp / (tp + fn):.0%}** ({tp}/{tp + fn} incidents retrouvés)",
             f"- **Précision : {tp / (tp + fp):.0%}** ({fp} fausse(s) alerte(s))", "",
             "| Type | Détectés | Manqués | Fausses alertes | Écart médian sur l'heure de début |",
             "|---|---|---|---|---|"]
    for t in ["STALE_DATA", "DOCKS_UNAVAILABLE", "OUT_OF_SERVICE", "CHRONIC_EMPTY", "CHRONIC_FULL"]:
        c = per_type[t]
        d = f"{median(delays[t]):.0f} min" if delays[t] else "n/a (fenêtre 24 h)"
        lines.append(f"| {t} | {c['tp']} | {c['fn']} | {c['fp']} | {d} |")
    lines += ["", "| Graine | Détectés | Manqués | Fausses alertes |", "|---|---|---|---|"]
    lines += [f"| {s} | {a} | {b} | {c} |" for s, a, b, c in rows]
    lines += ["", "Limite : les données sont simulées, avec des signaux plus nets que le flux réel. "
              "Les seuils (`dbt_project.yml`, section `vars`) sont à recalibrer sur quelques semaines de données réelles."]
    Path(args.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:7]))


if __name__ == "__main__":
    main()
