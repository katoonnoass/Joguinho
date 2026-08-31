"""Diário de operações: JSONL + CSV, à prova de crash (append + flush)."""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from .models import Trade

CSV_COLUMNS = ["symbol", "side", "volume", "entry_time", "entry_price", "exit_time",
               "exit_price", "pnl", "fees", "r_multiple", "reason_in", "reason_out",
               "equity_after"]


class Journal:
    def __init__(self, directory: str = "runs", name: str | None = None):
        os.makedirs(directory, exist_ok=True)
        stamp = name or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.events_path = os.path.join(directory, f"{stamp}-events.jsonl")
        self.trades_path = os.path.join(directory, f"{stamp}-trades.csv")
        if not os.path.exists(self.trades_path):
            with open(self.trades_path, "w", encoding="utf-8", newline="") as fh:
                csv.writer(fh).writerow(CSV_COLUMNS)

    def event(self, kind: str, **payload: Any) -> None:
        rec: Dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind}
        rec.update(payload)
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
            fh.flush()

    def trade(self, t: Trade) -> None:
        row = t.as_row()
        with open(self.trades_path, "a", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerow([row[c] for c in CSV_COLUMNS])
            fh.flush()
        self.event("trade_closed", **row)
