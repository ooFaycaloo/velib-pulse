"""Rapport HTML autonome : brief de l'agent, indicateurs, courbes du réseau, carte des stations.

Usage : python -m velib_pulse.report --out reports/velib_pulse.html
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .agent import LABELS, run_agent
from .tools import PulseTools

PARIS = ZoneInfo("Europe/Paris")
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def to_paris(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc).astimezone(PARIS) if d.tzinfo is None else d.astimezone(PARIS)


def md_to_html(md: str) -> str:
    """Convertisseur Markdown minimal (titres, listes, gras) pour le brief."""
    out, list_tag = [], None

    def inline(s):
        s = html.escape(s)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

    for line in md.splitlines():
        m_ol, m_ul = re.match(r"^\d+\.\s+(.*)", line), re.match(r"^[-*]\s+(.*)", line)
        tag = "ol" if m_ol else "ul" if m_ul else None
        if list_tag and tag != list_tag:
            out.append(f"</{list_tag}>"); list_tag = None
        if tag:
            if not list_tag:
                out.append(f"<{tag}>"); list_tag = tag
            out.append(f"<li>{inline((m_ol or m_ul).group(1))}</li>")
        elif line.startswith("# "):
            out.append(f"<h2>{inline(line[2:])}</h2>")
        elif line.startswith("## "):
            out.append(f"<h3>{inline(line[3:])}</h3>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if list_tag:
        out.append(f"</{list_tag}>")
    return "\n".join(out)


# ------------------------------------------------------------------ graphiques SVG

W, H, PAD_L, PAD_R, PAD_T, PAD_B = 720, 240, 48, 72, 16, 28


def line_chart(chart_id: str, times: list[datetime], series: list[dict], y_label: str) -> str:
    """Courbes temporelles : 2 px, grille discrète, étiquettes directes en bout de courbe."""
    n = len(times)
    y_max = max(max(s["values"]) for s in series) or 1
    step = 10 ** max(0, len(str(int(y_max))) - 1)
    y_max = (int(y_max / step) + 1) * step
    x = lambda i: PAD_L + i * (W - PAD_L - PAD_R) / max(n - 1, 1)
    y = lambda v: PAD_T + (H - PAD_T - PAD_B) * (1 - v / y_max)

    parts = [f'<svg id="{chart_id}" class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(y_label)}">']
    for k in range(5):
        v = y_max * k / 4
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD_L - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{v:,.0f}</text>'.replace(",", " "))
    for i, t in enumerate(times):
        if t.minute == 0 and t.hour % 6 == 0:
            label = f"{JOURS[t.weekday()]} 0h" if t.hour == 0 else t.strftime("%Hh")
            parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{label}</text>')
    parts.append(f'<line class="axis" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    for s in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s["values"]))
        parts.append(f'<polyline class="line" style="stroke:var({s["color"]})" points="{pts}"/>')
        if len(series) > 1:  # étiquette directe au dernier point
            parts.append(f'<text class="direct" x="{x(n - 1) + 6:.1f}" y="{y(s["values"][-1]) + 4:.1f}">{s["name"]}</text>')
    parts.append(f'<line class="cross" x1="0" x2="0" y1="{PAD_T}" y2="{y(0):.1f}" visibility="hidden"/>')
    parts.append(f'<rect class="hit" x="{PAD_L}" y="{PAD_T}" width="{W - PAD_L - PAD_R}" height="{H - PAD_T - PAD_B}"/>')
    parts.append("</svg>")
    data = {"labels": [f"{JOURS[t.weekday()]} {t:%d/%m %Hh%M}" for t in times],
            "series": [{"name": s["name"], "color": s["color"], "values": s["values"]} for s in series],
            "geom": {"padL": PAD_L, "padR": PAD_R, "W": W, "n": n}}
    return "\n".join(parts) + f'\n<script type="application/json" id="{chart_id}-data">{json.dumps(data)}</script>'


STATE_STYLE = {  # couleur de statut + libellé : jamais la couleur seule
    "critique": ("--status-critical", "Critique : station muette", "▲"),
    "élevée": ("--status-serious", "Élevée : panne ou fermeture", "◆"),
    "moyenne": ("--status-warning", "Moyenne : déséquilibre chronique", "●"),
    "rééquilibrage": ("--series-1", "À rééquilibrer", "●"),
    "ok": ("--muted", "Normale", "●"),
}


def station_map(stations: list[dict]) -> str:
    lats, lons = [s["lat"] for s in stations], [s["lon"] for s in stations]
    la0, la1, lo0, lo1 = min(lats), max(lats), min(lons), max(lons)
    # projection équirectangulaire corrigée de la latitude (cos 48,86° ≈ 0,658), cadrée sur les données
    MW = 720
    sc = (MW - 40) / ((lo1 - lo0) * 0.658)
    MH = round((la1 - la0) * sc + 40)
    px = lambda lo: 20 + (lo - lo0) * 0.658 * sc
    py = lambda la: MH - 20 - (la - la0) * sc
    parts = [f'<svg id="map" class="chart" viewBox="0 0 {MW} {MH}" role="img" aria-label="Carte des stations">']
    order = ["ok", "rééquilibrage", "moyenne", "élevée", "critique"]  # les alertes au-dessus
    for st in sorted(stations, key=lambda s: order.index(s["state"])):
        var, _, _ = STATE_STYLE[st["state"]]
        r = 4 if st["state"] == "ok" else 7
        tip = f'{st["station_name"]} ({st["station_code"]}) · {st["capacity"]} places'
        if st["anomaly_type"]:
            tip += " · " + LABELS[st["anomaly_type"]]
        parts.append(f'<circle class="dot{" alert" if st["state"] != "ok" else ""}" cx="{px(st["lon"]):.1f}" '
                     f'cy="{py(st["lat"]):.1f}" r="{r}" style="fill:var({var})" data-tip="{html.escape(tip)}"/>')
    parts.append("</svg>")
    present = {s["state"] for s in stations}
    legend = "".join(
        f'<span class="key"><span class="swatch" style="color:var({v})">{icon}</span>{label}</span>'
        for state, (v, label, icon) in STATE_STYLE.items() if state in present)
    return f'<div class="legend">{legend}</div>' + "\n".join(parts)


# ------------------------------------------------------------------ page

CSS = """
:root{--surface-1:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;--grid:#e1e0d9;
--axis:#c3c2b7;--border:rgba(11,11,11,.10);--series-1:#2a78d6;--series-2:#eb6834;--status-critical:#d03b3b;
--status-serious:#ec835a;--status-warning:#fab219;--good:#006300;--bad:#b42525}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface-1:#1a1a19;--page:#0d0d0d;--ink:#f0efec;
--ink-2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--series-1:#3987e5;
--series-2:#d95926;--good:#0ca30c;--bad:#e66767;color-scheme:dark}}
:root[data-theme="dark"]{--surface-1:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink-2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;--good:#0ca30c;--bad:#e66767;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding-block:24px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
header h1{font-size:22px;margin:0 0 4px}
header p{margin:0;color:var(--ink-2)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.tile,.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px}
.tile .label{color:var(--ink-2);font-size:13px}
.tile .value{font-size:30px;font-weight:600;margin-top:2px}
.tile .delta{font-size:13px;color:var(--ink-2)}
.delta.up{color:var(--good)}.delta.down{color:var(--bad)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:12px}
.card{margin-bottom:12px;min-width:0}
.card h2{font-size:16px;margin:0 0 2px}
.card .sub{color:var(--ink-2);font-size:13px;margin:0 0 10px}
.brief h2{font-size:18px;margin:0 0 8px}.brief h3{font-size:15px;margin:16px 0 4px}
.brief ol,.brief ul{margin:4px 0;padding-left:22px}.brief li{margin:3px 0}
.chart{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.direct{fill:var(--ink-2);font-size:12px}
.cross{stroke:var(--axis);stroke-width:1}
.hit{fill:transparent;cursor:crosshair}
.dot{stroke:var(--surface-1);stroke-width:2}.dot.alert{cursor:pointer}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--ink-2);margin-bottom:8px}
.key{display:inline-flex;align-items:center;gap:6px}.swatch{font-size:12px}
.tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--ink);border:1px solid var(--border);
border-radius:8px;padding:6px 10px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;z-index:9;max-width:280px}
.tip b{display:block;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink-2);font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-flex;gap:4px;align-items:center;white-space:nowrap}
.scroll{overflow-x:auto}
footer{color:var(--muted);font-size:12px;margin-top:24px}
"""

JS = """
const tip=document.querySelector('.tip');
function show(e,h){tip.innerHTML=h;tip.style.display='block';
 const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'}
function hide(){tip.style.display='none'}
document.querySelectorAll('svg.chart[id^="line"]').forEach(svg=>{
 const d=JSON.parse(document.getElementById(svg.id+'-data').textContent),g=d.geom,cross=svg.querySelector('.cross');
 svg.querySelector('.hit').addEventListener('mousemove',e=>{
  const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());
  const i=Math.max(0,Math.min(g.n-1,Math.round((p.x-g.padL)/((g.W-g.padL-g.padR)/(g.n-1)))));
  const cx=g.padL+i*(g.W-g.padL-g.padR)/(g.n-1);cross.setAttribute('x1',cx);cross.setAttribute('x2',cx);cross.setAttribute('visibility','visible');
  show(e,'<b>'+d.labels[i]+'</b>'+d.series.map(s=>'<span style="color:var('+s.color+')">●</span> '+s.name+' : '+Math.round(s.values[i]).toLocaleString('fr-FR')).join('<br>'));
 });
 svg.querySelector('.hit').addEventListener('mouseleave',()=>{cross.setAttribute('visibility','hidden');hide()});
});
document.querySelectorAll('#map .dot').forEach(c=>{c.addEventListener('mousemove',e=>show(e,c.dataset.tip));c.addEventListener('mouseleave',hide)});
"""


def tile(label: str, value: str, delta: str = "", cls: str = "") -> str:
    return (f'<div class="tile"><div class="label">{label}</div><div class="value">{value}</div>'
            f'<div class="delta {cls}">{delta}</div></div>')


def build(out: str, data_note: str = "données réelles GBFS Vélib' Métropole"):
    tools = PulseTools()
    status = tools.network_status()
    now, before = status["now"], status["yesterday_same_time"]
    series = tools.network_series(48)
    anomalies = tools.list_anomalies()
    plan = tools.rebalancing_plan(15)
    stations = tools.stations_map()
    brief = run_agent(verbose=False)

    times = [to_paris(r["bucket"]) for r in series]
    diff = int(now["bikes_available"] - before["bikes_available"]) if before else 0
    tiles = "".join([
        tile("Vélos disponibles", f'{int(now["bikes_available"]):,}'.replace(",", " "),
             (f'{"▲" if diff >= 0 else "▼"} {abs(diff)} vs hier même heure' if before else ""),
             "up" if diff >= 0 else "down"),
        tile("Stations utilisables", f'{now["share_stations_usable"]:.0%}',
             f'{now["stations_reporting"]} stations suivies'),
        tile("Anomalies actives", str(len(anomalies)),
             f'{sum(a["severity"] == "critique" for a in anomalies)} critique(s)'),
        tile("Stations à rééquilibrer", str(len(plan)),
             f'{sum(p["bikes_to_move"] for p in plan)} vélos à déplacer'),
    ])

    sev_icon = {"critique": ("▲", "--status-critical"), "élevée": ("◆", "--status-serious"),
                "moyenne": ("●", "--status-warning")}
    rows_a = "".join(
        f'<tr><td><span class="badge"><span style="color:var({sev_icon[a["severity"]][1]})">'
        f'{sev_icon[a["severity"]][0]}</span>{a["severity"]}</span></td>'
        f'<td>{html.escape(a["station_name"])}<br><span style="color:var(--muted)">{a["station_code"]}</span></td>'
        f'<td>{LABELS[a["anomaly_type"]]}</td><td>{"sur 24 h" if a["anomaly_type"].startswith("CHRONIC") else f"{to_paris(a['since']):%d/%m %Hh%M}"}</td>'
        f'<td class="num">{a["capacity"]}</td></tr>' for a in anomalies)
    rows_p = "".join(
        f'<tr><td>{html.escape(p["station_name"])}<br><span style="color:var(--muted)">{p["station_code"]}</span></td>'
        f'<td>{p["action"]}</td><td class="num">{p["bikes_to_move"]}</td><td>{p["usage_profile"]}</td></tr>'
        for p in plan)

    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Vélib Pulse</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{CSS}</style></head><body><main>
<header><h1>Vélib Pulse — supervision du réseau</h1>
<p>Situation au {to_paris(now["bucket"]):%d/%m/%Y à %Hh%M} (heure de Paris) · Kafka → ClickHouse → dbt → agent IA</p></header>
<section class="tiles">{tiles}</section>
<section class="card brief">{md_to_html(brief)}</section>
<div class="grid2">
<section class="card"><h2>Vélos disponibles sur le réseau</h2><p class="sub">48 dernières heures, par quart d'heure</p>
{line_chart("line-bikes", times, [{"name": "Vélos", "color": "--series-1", "values": [r["bikes_available"] for r in series]}], "Vélos disponibles")}</section>
<section class="card"><h2>Stations en panne technique</h2><p class="sub">Muettes, fermées ou avec des bornettes hors service</p>
{line_chart("line-faulty", times, [{"name": "Stations en panne", "color": "--series-2", "values": [r["stations_faulty"] for r in series]}], "Stations en panne technique")}</section>
</div>
<section class="card"><h2>Carte des stations</h2><p class="sub">Survolez un point pour le détail</p>{station_map(stations)}</section>
<div class="grid2">
<section class="card"><h2>Anomalies actives</h2><div class="scroll"><table><thead><tr><th>Gravité</th><th>Station</th>
<th>Problème</th><th>Depuis</th><th class="num">Places</th></tr></thead><tbody>{rows_a}</tbody></table></div></section>
<section class="card"><h2>Plan de régulation</h2><div class="scroll"><table><thead><tr><th>Station</th><th>Action</th>
<th class="num">Vélos</th><th>Profil</th></tr></thead><tbody>{rows_p}</tbody></table></div></section>
</div>
<footer>Généré le {datetime.now(PARIS):%d/%m/%Y %Hh%M} · {data_note} · Fayçal Boubekri</footer>
</main><div class="tip"></div><script>{JS}</script></body></html>"""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(page, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/velib_pulse.html")
    ap.add_argument("--simulated", action="store_true", help="mentionner des données simulées dans le pied de page")
    args = ap.parse_args()
    note = "données simulées au format GBFS Vélib' Métropole" if args.simulated else "données réelles GBFS Vélib' Métropole"
    print(f"Rapport écrit : {build(args.out, note)}")


if __name__ == "__main__":
    main()
