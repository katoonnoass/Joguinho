"""Registro de estratégias."""
from __future__ import annotations

from typing import Any, Dict

from .base import Strategy, StrategyContext
from .trend_atr import TrendATR
from .mean_reversion import MeanReversion

REGISTRY: Dict[str, type] = {
    "trend_atr": TrendATR,
    "mean_reversion": MeanReversion,
}


def build(name: str, params: Dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"estratégia desconhecida: {name}. Disponíveis: {sorted(REGISTRY)}")
    return REGISTRY[name](**(params or {}))


__all__ = ["Strategy", "StrategyContext", "TrendATR", "MeanReversion", "REGISTRY", "build"]
