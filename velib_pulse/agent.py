"""Agent « chef d'équipe terrain » : rédige le brief opérationnel à partir des marts dbt.

- Avec ANTHROPIC_API_KEY : Claude enquête lui-même avec les outils (historique d'une station,
  SQL en lecture seule…) puis rédige un brief priorisé.
- Sans clé : un brief déterministe est produit à partir des mêmes données (repli).

Usage :
    python -m velib_pulse.agent                       # brief complet
    python -m velib_pulse.agent "Pourquoi la station 17092 est-elle en alerte ?"
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import typing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .tools import TOOL_NAMES, PulseTools

SYSTEM = """Tu es le responsable des opérations d'un réseau de vélos en libre-service à Paris.
Tu rédiges en français, pour les équipes terrain, un brief court et actionnable.
Règles :
- Appuie chaque affirmation sur les résultats des outils ; n'invente aucun chiffre.
- Distingue les pannes techniques (station muette, bornettes HS, station fermée : intervention maintenance)
  des déséquilibres (station vide ou pleine : camion de régulation).
- Pour les anomalies critiques, consulte l'historique de la station avant de conclure.
- Format : un titre, 3 lignes de synthèse chiffrée, puis « Maintenance » et « Régulation » en listes
  ordonnées par priorité, et une phrase sur ce qu'il faut surveiller."""

QUESTION_BRIEF = "Rédige le brief opérationnel de maintenant."

PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}

LABELS = {
    "STALE_DATA": "station muette (ne remonte plus de données)",
    "OUT_OF_SERVICE": "station fermée (ni prêt ni retour)",
    "DOCKS_UNAVAILABLE": "bornettes hors service",
    "CHRONIC_EMPTY": "vide la plupart de la journée",
    "CHRONIC_FULL": "pleine la plupart de la journée",
}


def tool_schema(fn) -> dict:
    props, required = {}, []
    hints = typing.get_type_hints(fn)
    for name, p in inspect.signature(fn).parameters.items():
        t = hints.get(name, str)
        base = next((a for a in typing.get_args(t) if a is not type(None)), t)
        props[name] = {"type": PY_TO_JSON.get(base, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"name": fn.__name__, "description": (fn.__doc__ or "").strip(),
            "input_schema": {"type": "object", "properties": props, "required": required}}


def _fmt_time(d) -> str:
    """Horodatages stockés en UTC, affichés en heure de Paris."""
    if not isinstance(d, datetime):
        return str(d)
    d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    return d.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m %Hh%M")


def _fmt_metric(a: dict) -> str:
    if a["metric_label"].startswith("part"):
        return f"{a['metric_value']:.0%} {a['metric_label'].removeprefix('part des ').removeprefix('part du ')}"
    return f"{a['metric_value']:g} {a['metric_label']}"


def fallback_brief(tools: PulseTools) -> str:
    """Brief déterministe (sans LLM) : même structure, phrasé fixe."""
    status = tools.network_status()
    now, before = status["now"], status["yesterday_same_time"]
    anomalies = tools.list_anomalies()
    plan = tools.rebalancing_plan(10)
    tech = [a for a in anomalies if a["anomaly_type"] in ("STALE_DATA", "OUT_OF_SERVICE", "DOCKS_UNAVAILABLE")]

    delta = ""
    if before:
        diff = int(now["bikes_available"] - before["bikes_available"])
        delta = f" ({'+' if diff >= 0 else ''}{diff} par rapport à hier même heure)"
    lines = [f"# Brief opérations — {_fmt_time(now['bucket'])}", "",
             f"- **{int(now['bikes_available'])} vélos disponibles**{delta}, "
             f"{now['share_stations_usable']:.0%} des stations utilisables.",
             f"- **{len(tech)} panne(s) technique(s)** à traiter, dont "
             f"{sum(a['severity'] == 'critique' for a in tech)} critique(s).",
             f"- **{len(plan)} station(s) à rééquilibrer** maintenant.", "", "## Maintenance", ""]
    lines += [f"{i}. **{a['station_name']}** ({a['station_code']}, {a['capacity']} places) — "
              f"{LABELS[a['anomaly_type']]} depuis le {_fmt_time(a['since'])} "
              f"({_fmt_metric(a)})." for i, a in enumerate(tech, 1)] or ["Aucune panne."]
    lines += ["", "## Régulation", ""]
    lines += [f"{i}. **{p['station_name']}** ({p['station_code']}) — {p['action']} : "
              f"{p['bikes_to_move']} vélos." for i, p in enumerate(plan, 1)] or ["Aucune station à rééquilibrer."]
    chronic = [a for a in anomalies if a["anomaly_type"].startswith("CHRONIC")]
    if chronic:
        lines += ["", "## À surveiller", "",
                  "Stations structurellement déséquilibrées (à revoir dans le plan de régulation) : "
                  + ", ".join(f"{a['station_name']} ({LABELS[a['anomaly_type']]})" for a in chronic) + "."]
    return "\n".join(lines)


def run_agent(question: str = QUESTION_BRIEF, max_turns: int = 10, verbose: bool = True) -> str:
    tools = PulseTools()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if question != QUESTION_BRIEF:
            return "Les questions libres nécessitent ANTHROPIC_API_KEY. Voici le brief standard :\n\n" + fallback_brief(tools)
        return fallback_brief(tools)

    import anthropic

    fns = {n: getattr(tools, n) for n in TOOL_NAMES}
    client = anthropic.Anthropic()
    model = os.environ.get("VELIB_AGENT_MODEL", "claude-sonnet-5-5")
    messages = [{"role": "user", "content": question}]
    for _ in range(max_turns):
        resp = client.messages.create(model=model, max_tokens=2500, system=SYSTEM,
                                      tools=[tool_schema(f) for f in fns.values()], messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                if verbose:
                    print(f"  → {b.name}({json.dumps(b.input, ensure_ascii=False)})", file=sys.stderr)
                try:
                    out = fns[b.name](**b.input)
                except Exception as e:  # l'agent voit l'erreur et peut corriger sa requête
                    out = {"error": str(e)[:500]}
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, default=str, ensure_ascii=False)[:20000]})
        messages.append({"role": "user", "content": results})
    return fallback_brief(tools)


if __name__ == "__main__":
    print(run_agent(" ".join(sys.argv[1:]) or QUESTION_BRIEF))
