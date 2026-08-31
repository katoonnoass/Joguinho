"""Interface de estratégia.

Contrato anti-look-ahead: `on_bar` recebe apenas candles JÁ FECHADOS
(`history[-1]` é o último candle fechado) e o motor executa o sinal na
abertura do candle seguinte.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..models import Candle, Position, Signal, SymbolSpec


@dataclass
class StrategyContext:
    spec: SymbolSpec
    equity: float
    position: Optional[Position] = None


class Strategy:
    name = "base"

    #: candles mínimos antes de produzir qualquer sinal
    warmup = 100

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

    def on_bar(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[Signal]:
        raise NotImplementedError

    def should_exit(self, history: Sequence[Candle], ctx: StrategyContext) -> Optional[str]:
        """Saída discricionária (além de stop/take/trailing). None = manter."""
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__}({self.params()})"


def last_valid(series: List[Optional[float]], idx: int) -> Optional[float]:
    return series[idx] if 0 <= idx < len(series) else None
