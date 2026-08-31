"""Interface comum entre o simulador (backtest/paper) e o MT5 real."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence

from ..models import AccountState, Candle, Position, Side, SymbolSpec, Trade


@dataclass
class Quote:
    time: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    def spread_points(self, spec: SymbolSpec) -> float:
        return (self.ask - self.bid) / spec.point

    def price_for(self, side: Side) -> float:
        return self.ask if side is Side.BUY else self.bid


class Broker:
    """Contrato mínimo que o runner precisa."""

    spec: SymbolSpec

    def history(self, count: int) -> List[Candle]:
        raise NotImplementedError

    def quote(self) -> Quote:
        raise NotImplementedError

    def account(self) -> AccountState:
        raise NotImplementedError

    def position(self) -> Optional[Position]:
        raise NotImplementedError

    def open(self, side: Side, volume: float, stop: float,
             take: Optional[float], reason: str = "") -> Optional[Position]:
        raise NotImplementedError

    def modify(self, stop: Optional[float] = None, take: Optional[float] = None) -> bool:
        raise NotImplementedError

    def close(self, reason: str = "", fraction: float = 1.0) -> Optional[Trade]:
        raise NotImplementedError

    def closed_trades(self) -> Sequence[Trade]:
        return []
