"""Gestão de posição aberta: breakeven, realização parcial e trailing por ATR.

Isolado num módulo próprio para que backtest e execução ao vivo usem
EXATAMENTE a mesma lógica — divergência aqui é a causa nº1 de um robô que
"funcionava no teste" e perde dinheiro na conta real.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .config import ExecutionConfig
from .models import Position, Side, SymbolSpec


@dataclass
class ManageAction:
    kind: str                      # "modify_stop" | "partial_close"
    value: float                   # novo stop, ou fração a fechar
    reason: str = ""


def manage(pos: Position, price: float, atr_value: Optional[float],
           risk_per_unit: float, cfg: ExecutionConfig, spec: SymbolSpec,
           partial_done: bool) -> List[ManageAction]:
    actions: List[ManageAction] = []
    if risk_per_unit <= 0:
        return actions
    progress_r = (price - pos.entry_price) * pos.side.sign / risk_per_unit

    # 1) realização parcial
    if (cfg.partial_take_at_r and not partial_done and progress_r >= cfg.partial_take_at_r
            and spec.normalize_volume(pos.volume / 2) > 0):
        actions.append(ManageAction("partial_close", 0.5,
                                    f"parcial em {cfg.partial_take_at_r}R"))

    # 2) breakeven
    if cfg.breakeven_at_r and progress_r >= cfg.breakeven_at_r:
        be = pos.entry_price + (spec.point * 2) * pos.side.sign
        if _is_better_stop(pos, be):
            actions.append(ManageAction("modify_stop", be, "breakeven"))

    # 3) trailing por ATR (usa a melhor cotação alcançada como âncora)
    if cfg.trail_atr_mult and atr_value:
        anchor = pos.trail_anchor if pos.trail_anchor is not None else price
        anchor = max(anchor, price) if pos.side is Side.BUY else min(anchor, price)
        pos.trail_anchor = anchor
        trail = anchor - cfg.trail_atr_mult * atr_value * pos.side.sign
        if _is_better_stop(pos, trail) and progress_r >= 1.0:
            actions.append(ManageAction("modify_stop", trail, "trailing ATR"))

    return actions


def _is_better_stop(pos: Position, new_stop: float) -> bool:
    """Stop só se move a favor: nunca aumentamos o risco de uma posição."""
    if pos.side is Side.BUY:
        return new_stop > pos.stop
    return new_stop < pos.stop
