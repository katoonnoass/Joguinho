"""Leitura/escrita de candles em CSV (formato compatível com export do MT5)."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

from ..models import Candle

TIMEFRAMES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def timeframe_minutes(tf: str) -> int:
    tf = tf.upper()
    if tf not in TIMEFRAMES:
        raise ValueError(f"timeframe inválido: {tf}. Use {sorted(TIMEFRAMES)}")
    return TIMEFRAMES[tf]


def _parse_time(raw: str) -> datetime:
    raw = raw.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=dt.tzinfo or timezone.utc)
        except ValueError:
            continue
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    raise ValueError(f"data não reconhecida: {raw!r}")


def load_csv(path: str, limit: Optional[int] = None) -> List[Candle]:
    """Aceita cabeçalhos time/date, open, high, low, close, volume (case-insensitive)."""
    out: List[Candle] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        delim = "\t" if "\t" in sample.splitlines()[0] else ","
        reader = csv.DictReader(fh, delimiter=delim)
        if reader.fieldnames is None:
            raise ValueError("CSV sem cabeçalho")
        cols = {c.lower().strip().lstrip("<").rstrip(">"): c for c in reader.fieldnames}
        tcol = cols.get("time") or cols.get("date") or cols.get("datetime")
        if tcol is None:
            raise ValueError(f"coluna de tempo ausente em {path}")
        dcol = cols.get("date") if tcol != cols.get("date") else None
        for row in reader:
            raw_time = row[tcol].strip()
            if dcol and cols.get("time") == tcol:
                pass
            if dcol and tcol == cols.get("time"):
                raw_time = f"{row[dcol].strip()} {raw_time}"
            try:
                out.append(Candle(
                    time=_parse_time(raw_time),
                    open=float(row[cols["open"]]),
                    high=float(row[cols["high"]]),
                    low=float(row[cols["low"]]),
                    close=float(row[cols["close"]]),
                    volume=float(row.get(cols.get("volume", ""), 0) or 0),
                ))
            except (KeyError, ValueError):
                continue
    out.sort(key=lambda c: c.time)
    return out[-limit:] if limit else out


def save_csv(path: str, candles: Iterable[Candle]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.time.strftime("%Y-%m-%d %H:%M:%S"), f"{c.open:.6f}",
                        f"{c.high:.6f}", f"{c.low:.6f}", f"{c.close:.6f}", int(c.volume)])
            n += 1
    return n


def split(candles: Sequence[Candle], ratio: float = 0.7):
    """Divide em treino/teste preservando a ordem temporal."""
    k = int(len(candles) * ratio)
    return list(candles[:k]), list(candles[k:])
