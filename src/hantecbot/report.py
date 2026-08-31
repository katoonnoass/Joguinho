"""Relatório HTML autocontido (curva de equity em SVG, sem dependências)."""
from __future__ import annotations

import html
import os
from datetime import datetime
from typing import List, Sequence, Tuple

from .backtest.metrics import Metrics
from .models import Trade


def _svg_curve(points: Sequence[Tuple[datetime, float]], width: int = 960,
               height: int = 320) -> str:
    if len(points) < 2:
        return "<p>sem dados suficientes para o gráfico</p>"
    step = max(1, len(points) // 1500)
    pts = points[::step]
    ys = [e for _, e in pts]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    pad = 40
    w, h = width - pad * 2, height - pad * 2

    def xy(i: int, v: float) -> Tuple[float, float]:
        x = pad + (i / (len(pts) - 1)) * w
        y = pad + h - ((v - lo) / span) * h
        return x, y

    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in enumerate(ys)))
    area = f"{pad},{pad+h} {line} {pad+w},{pad+h}"
    # drawdown shading (peak-to-valley)
    peak = ys[0]
    dd_pts = []
    for i, v in enumerate(ys):
        peak = max(peak, v)
        dd_pts.append((i, (v / peak - 1.0) * 100.0))
    dd_min = min(d for _, d in dd_pts) or -1.0
    dd_line = " ".join(
        f"{pad + (i/(len(pts)-1))*w:.1f},{height-14 - (d/dd_min)*18:.1f}" for i, d in dd_pts)
    first, last = pts[0][0], pts[-1][0]
    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#2dd4bf" stop-opacity=".45"/>
    <stop offset="100%" stop-color="#2dd4bf" stop-opacity="0"/>
  </linearGradient></defs>
  <rect x="0" y="0" width="{width}" height="{height}" fill="#0b1120"/>
  <polygon points="{area}" fill="url(#g)"/>
  <polyline points="{line}" fill="none" stroke="#2dd4bf" stroke-width="2"/>
  <polyline points="{dd_line}" fill="none" stroke="#f87171" stroke-width="1" opacity=".8"/>
  <text x="{pad}" y="24" fill="#94a3b8" font-size="12">equity {lo:,.0f} → {hi:,.0f}</text>
  <text x="{pad}" y="{height-2}" fill="#64748b" font-size="10">{first:%Y-%m-%d} … {last:%Y-%m-%d} (linha vermelha = drawdown)</text>
</svg>"""


def render_html(metrics: Metrics, trades: Sequence[Trade],
                equity_curve: Sequence[Tuple[datetime, float]],
                title: str = "Relatório de Backtest", meta: dict | None = None) -> str:
    m = metrics.to_dict()
    cards = [
        ("Retorno", f"{m['return_pct']:+.2f}%"),
        ("Lucro líquido", f"{m['net_profit']:,.2f}"),
        ("Drawdown máx.", f"{m['max_drawdown_pct']:.2f}%"),
        ("Profit factor", f"{m['profit_factor']:.2f}"),
        ("Acerto", f"{m['win_rate']:.1f}%"),
        ("Expectativa", f"{m['expectancy_r']:+.3f} R"),
        ("Sharpe", f"{m['sharpe']:.2f}"),
        ("Trades", f"{m['trades']}"),
    ]
    card_html = "".join(
        f'<div class="card"><span>{html.escape(k)}</span><strong>{html.escape(v)}</strong></div>'
        for k, v in cards)
    rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in t.as_row().values()) + "</tr>"
        for t in list(trades)[-200:])
    columns = ["symbol", "side", "volume", "entry_time", "entry_price", "exit_time",
               "exit_price", "pnl", "fees", "r_multiple", "reason_in", "reason_out",
               "equity_after"]
    headers = "".join(f"<th>{h}</th>" for h in columns)
    meta_html = "".join(f"<li><b>{html.escape(str(k))}</b>: {html.escape(str(v))}</li>"
                        for k, v in (meta or {}).items())
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
 :root{{color-scheme:dark}}
 body{{margin:0;background:#0b1120;color:#e2e8f0;font:14px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto}}
 .wrap{{max-width:1040px;margin:0 auto;padding:32px 20px 80px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#94a3b8;margin-bottom:24px}}
 .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
 .card{{background:#111c33;border:1px solid #1e293b;border-radius:12px;padding:14px}}
 .card span{{display:block;color:#94a3b8;font-size:12px}} .card strong{{font-size:20px}}
 table{{width:100%;border-collapse:collapse;font-size:12px;margin-top:12px}}
 th,td{{padding:6px 8px;border-bottom:1px solid #1e293b;text-align:right;white-space:nowrap}}
 th:first-child,td:first-child{{text-align:left}}
 th{{color:#94a3b8;font-weight:600;position:sticky;top:0;background:#0b1120}}
 .warn{{background:#2a1414;border:1px solid #7f1d1d;color:#fecaca;padding:12px 14px;border-radius:10px;margin-top:28px}}
 ul{{color:#94a3b8}} .tablewrap{{max-height:520px;overflow:auto;border:1px solid #1e293b;border-radius:12px}}
</style></head><body><div class="wrap">
<h1>{html.escape(title)}</h1>
<div class="sub">gerado em {datetime.utcnow():%Y-%m-%d %H:%M} UTC</div>
<ul>{meta_html}</ul>
<div class="cards">{card_html}</div>
{_svg_curve(list(equity_curve))}
<h2>Últimas operações</h2>
<div class="tablewrap"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>
<div class="warn"><b>Aviso de risco:</b> resultados passados ou simulados não garantem
resultados futuros. CFDs e forex são alavancados e podem gerar perdas rápidas do
capital investido. Use apenas conta demo até validar o sistema por conta própria.</div>
</div></body></html>"""


def write_report(path: str, metrics: Metrics, trades: Sequence[Trade],
                 equity_curve: Sequence[Tuple[datetime, float]],
                 title: str = "Relatório de Backtest", meta: dict | None = None) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(metrics, trades, equity_curve, title, meta))
    return path
