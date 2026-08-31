#!/usr/bin/env python3
"""Normaliza CSVs de candles de terceiros para o formato do hantecbot e audita a qualidade.

Uso:
    python tools/import_csv.py entrada.csv data/EURUSD_M15.csv --timeframe M15

Aceita datas em vários formatos (MT5, TradingView, "M/D/YYYY H:MM", epoch) e
reporta os problemas que costumam envenenar backtest: duplicatas, buracos,
candles inconsistentes (high < low, close fora do range) e barras de fim de semana.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hantecbot.data.loader import TIMEFRAMES, save_csv  # noqa: E402
from hantecbot.models import Candle  # noqa: E402

FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
           "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]


def parse_time(raw: str) -> datetime:
    raw = raw.strip().strip('"')
    for fmt in FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    raise ValueError(f"data não reconhecida: {raw!r}")


def load_any(path: str) -> list[Candle]:
    out: list[Candle] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        head = fh.readline()
        fh.seek(0)
        delim = "\t" if "\t" in head else (";" if head.count(";") > head.count(",") else ",")
        reader = csv.DictReader(fh, delimiter=delim)
        cols = {c.lower().strip().lstrip("<").rstrip(">"): c for c in (reader.fieldnames or [])}
        tcol = cols.get("time") or cols.get("date") or cols.get("datetime") or cols.get("timestamp")
        if not tcol:
            raise SystemExit(f"coluna de tempo não encontrada. Colunas: {reader.fieldnames}")
        for row in reader:
            try:
                out.append(Candle(
                    time=parse_time(row[tcol]),
                    open=float(row[cols["open"]]), high=float(row[cols["high"]]),
                    low=float(row[cols["low"]]), close=float(row[cols["close"]]),
                    volume=float(row.get(cols.get("volume", ""), 0) or 0)))
            except (KeyError, ValueError):
                continue
    out.sort(key=lambda c: c.time)
    return out


def audit(candles: list[Candle], timeframe: str) -> dict:
    step = timedelta(minutes=TIMEFRAMES[timeframe.upper()])
    dup = broken = weekend = flat = 0
    gaps: Counter = Counter()
    seen = set()
    prev = None
    for c in candles:
        if c.time in seen:
            dup += 1
        seen.add(c.time)
        if c.high < c.low or not (c.low <= c.open <= c.high) or not (c.low <= c.close <= c.high):
            broken += 1
        if c.time.weekday() >= 5:
            weekend += 1
        if c.high == c.low:
            flat += 1
        if prev is not None:
            delta = c.time - prev.time
            if delta > step:
                gaps[delta] += 1
        prev = c
    weekend_gaps = sum(n for d, n in gaps.items() if d >= timedelta(hours=24))
    intraday_gaps = sum(n for d, n in gaps.items() if d < timedelta(hours=24))
    return {"candles": len(candles), "de": candles[0].time, "ate": candles[-1].time,
            "duplicados": dup, "inconsistentes": broken, "fim_de_semana": weekend,
            "sem_range": flat, "buracos_intradiarios": intraday_gaps,
            "pausas_de_fim_de_semana": weekend_gaps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada")
    ap.add_argument("saida")
    ap.add_argument("--timeframe", default="M15")
    ap.add_argument("--drop-weekend", action="store_true", default=True)
    args = ap.parse_args()

    candles = load_any(args.entrada)
    if not candles:
        raise SystemExit("nenhum candle lido")
    rel = audit(candles, args.timeframe)
    print("Auditoria do arquivo de origem:")
    for k, v in rel.items():
        print(f"  {k:26s}: {v}")

    limpos, seen = [], set()
    for c in candles:
        if c.time in seen:
            continue
        if c.high < c.low or not (c.low <= c.open <= c.high) or not (c.low <= c.close <= c.high):
            continue
        if args.drop_weekend and c.time.weekday() >= 5:
            continue
        seen.add(c.time)
        limpos.append(c)

    n = save_csv(args.saida, limpos)
    print(f"\n✓ {n} candles gravados em {args.saida} "
          f"({len(candles) - n} descartados na limpeza)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
