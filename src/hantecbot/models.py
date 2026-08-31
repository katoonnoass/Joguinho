"""Tipos de dados básicos usados em todo o bot (stdlib puro, sem dependências)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True)
class Candle:
    """Candle OHLCV fechado."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bull(self) -> bool:
        return self.close >= self.open


@dataclass(frozen=True)
class Signal:
    """Intenção de operar produzida por uma estratégia.

    `stop` e `take` são preços absolutos. `stop` é obrigatório: sem stop
    definido o risco não é mensurável e a ordem é recusada pelo RiskManager.
    """

    side: Side
    stop: float
    take: Optional[float] = None
    reason: str = ""
    confidence: float = 1.0


@dataclass
class Position:
    symbol: str
    side: Side
    volume: float          # em lotes
    entry_price: float
    stop: float
    take: Optional[float]
    opened_at: datetime
    reason: str = ""
    magic: int = 0
    trail_anchor: Optional[float] = None

    def unrealized(self, price: float, contract_size: float) -> float:
        return (price - self.entry_price) * self.side.sign * self.volume * contract_size


@dataclass
class Trade:
    """Operação encerrada — a unidade de contabilidade do sistema."""

    symbol: str
    side: Side
    volume: float
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl: float
    fees: float = 0.0
    reason_in: str = ""
    reason_out: str = ""
    equity_after: float = 0.0
    r_multiple: float = 0.0

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    def as_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "volume": round(self.volume, 4),
            "entry_time": self.entry_time.isoformat(),
            "entry_price": round(self.entry_price, 6),
            "exit_time": self.exit_time.isoformat(),
            "exit_price": round(self.exit_price, 6),
            "pnl": round(self.pnl, 2),
            "fees": round(self.fees, 2),
            "r_multiple": round(self.r_multiple, 3),
            "reason_in": self.reason_in,
            "reason_out": self.reason_out,
            "equity_after": round(self.equity_after, 2),
        }


@dataclass
class SymbolSpec:
    """Especificação do instrumento (espelha o que o MT5 devolve)."""

    symbol: str = "EURUSD"
    digits: int = 5
    point: float = 0.00001
    contract_size: float = 100_000.0     # 1 lote padrão
    volume_min: float = 0.01
    volume_max: float = 50.0
    volume_step: float = 0.01
    spread_points: float = 8.0           # spread típico em points
    commission_per_lot: float = 3.5      # ida e volta, na moeda da conta
    swap_long_per_lot: float = 0.0       # por dia mantido
    swap_short_per_lot: float = 0.0

    @property
    def pip(self) -> float:
        """1 pip = 10 points em pares de 5/3 dígitos."""
        return self.point * (10 if self.digits in (3, 5) else 1)

    def value_per_price_unit(self, volume: float) -> float:
        return volume * self.contract_size

    def normalize_volume(self, volume: float) -> float:
        if volume <= 0:
            return 0.0
        steps = int(volume / self.volume_step + 1e-9)
        vol = round(steps * self.volume_step, 8)
        vol = min(max(vol, 0.0), self.volume_max)
        return vol if vol >= self.volume_min else 0.0

    def round_price(self, price: float) -> float:
        return round(price, self.digits)


@dataclass
class AccountState:
    balance: float
    equity: float
    open_positions: int = 0
    day_start_equity: float = 0.0
    peak_equity: float = 0.0
    consecutive_losses: int = 0
    halted_reason: str = ""
    extras: dict = field(default_factory=dict)
