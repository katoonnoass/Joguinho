"""Configuração declarativa do bot (YAML -> dataclasses validadas)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from .models import SymbolSpec
from .prop import GuardConfig, PropRules


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.5       # % do equity arriscado por operação
    max_daily_loss_pct: float = 2.0       # kill switch diário
    max_drawdown_pct: float = 10.0        # kill switch global (pico -> vale)
    max_open_positions: int = 1
    max_consecutive_losses: int = 5
    max_lot: float = 5.0
    max_spread_points: float = 25.0       # não opera com spread alargado
    min_stop_points: float = 50.0
    trading_hours_utc: List[int] = field(default_factory=lambda: list(range(6, 21)))
    weekdays: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # seg-sex
    reduce_risk_after_loss: bool = True   # meio risco após perda (anti-tilt)


@dataclass
class StrategyConfig:
    name: str = "trend_atr"
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionConfig:
    slippage_points: float = 3.0
    fill_on_next_open: bool = True        # sinal no fecho -> execução na abertura seguinte
    partial_take_at_r: Optional[float] = 1.0   # realiza 50% em 1R
    breakeven_at_r: Optional[float] = 1.0      # move stop p/ entrada em 1R
    trail_atr_mult: Optional[float] = 2.5      # trailing stop por ATR


@dataclass
class BotConfig:
    symbol: SymbolSpec = field(default_factory=SymbolSpec)
    timeframe: str = "M15"
    initial_balance: float = 10_000.0
    magic: int = 990045
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    # Live / MT5
    mt5_login: Optional[int] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None       # ex.: "HantecMarkets-Demo"
    mt5_terminal_path: Optional[str] = None
    poll_seconds: int = 5
    # Mesa proprietária (opcional)
    prop: Optional[PropRules] = None
    guard: GuardConfig = field(default_factory=GuardConfig)

    # ---------------------------------------------------------------- loading
    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "BotConfig":
        d = dict(d or {})
        cfg = BotConfig()
        if "symbol" in d:
            cfg.symbol = SymbolSpec(**d["symbol"])
        if "strategy" in d:
            s = d["strategy"]
            cfg.strategy = StrategyConfig(name=s.get("name", "trend_atr"), params=s.get("params", {}))
        if "risk" in d:
            cfg.risk = RiskConfig(**d["risk"])
        if "execution" in d:
            cfg.execution = ExecutionConfig(**d["execution"])
        if d.get("prop"):
            cfg.prop = (PropRules(**d["prop"]) if isinstance(d["prop"], dict)
                        else load_prop_rules(str(d["prop"])))
        if "guard" in d:
            cfg.guard = GuardConfig(**d["guard"])
        for k in ("timeframe", "initial_balance", "magic", "mt5_login", "mt5_password",
                  "mt5_server", "mt5_terminal_path", "poll_seconds"):
            if k in d:
                setattr(cfg, k, d[k])
        cfg.resolve_env()
        cfg.apply_prop_rules()
        cfg.validate()
        return cfg

    @staticmethod
    def load(path: str) -> "BotConfig":
        if yaml is None:
            raise RuntimeError("PyYAML não instalado: pip install pyyaml")
        with open(path, "r", encoding="utf-8") as fh:
            return BotConfig.from_dict(yaml.safe_load(fh) or {})

    def resolve_env(self) -> None:
        """Credenciais nunca ficam no YAML: leia do ambiente."""
        self.mt5_login = int(os.getenv("HANTEC_LOGIN", self.mt5_login or 0)) or None
        self.mt5_password = os.getenv("HANTEC_PASSWORD", self.mt5_password)
        self.mt5_server = os.getenv("HANTEC_SERVER", self.mt5_server)
        self.mt5_terminal_path = os.getenv("MT5_PATH", self.mt5_terminal_path)

    def apply_prop_rules(self) -> None:
        """Aperta os limites internos para caber com folga nas regras da mesa.

        Nunca afrouxa: se a config do usuário já é mais conservadora, mantém.
        """
        if self.prop is None:
            return
        p, g, r = self.prop, self.guard, self.risk
        # risco por operação: fração do limite diário e da regra de risco máximo
        caps = [r.risk_per_trade_pct, g.max_risk_per_trade_pct,
                p.daily_loss_pct * g.safety_factor / max(1, g.max_trades_per_day) * 2]
        if p.max_risk_pct:
            caps.append(p.max_risk_pct * g.safety_factor)
        r.risk_per_trade_pct = max(0.05, min(caps))
        # kill switches internos sempre abaixo dos oficiais
        r.max_daily_loss_pct = min(r.max_daily_loss_pct, p.daily_loss_pct * g.safety_factor)
        r.max_drawdown_pct = min(r.max_drawdown_pct, p.total_loss_pct * g.total_safety_factor)
        r.max_open_positions = min(r.max_open_positions, 1)

    def validate(self) -> None:
        r = self.risk
        if not (0 < r.risk_per_trade_pct <= 5):
            raise ValueError("risk_per_trade_pct deve estar em (0, 5]. Acima disso é aposta, não trading.")
        if r.max_daily_loss_pct <= 0 or r.max_drawdown_pct <= 0:
            raise ValueError("limites de perda devem ser positivos")
        if r.max_open_positions < 1:
            raise ValueError("max_open_positions >= 1")
        if self.initial_balance <= 0:
            raise ValueError("initial_balance deve ser > 0")

    @property
    def prop_name(self) -> str:
        return self.prop.name if self.prop else "sem mesa"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("mt5_password", None)
        return d


def load_prop_rules(path: str) -> PropRules:
    """Carrega um preset de regras de mesa proprietária (YAML)."""
    if yaml is None:
        raise RuntimeError("PyYAML não instalado: pip install pyyaml")
    if not os.path.exists(path):
        alt = os.path.join("config", "fimathe", f"{path}.yaml")
        if os.path.exists(alt):
            path = alt
        else:
            raise FileNotFoundError(f"preset de regras não encontrado: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    known = set(PropRules().to_dict().keys())
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"campos desconhecidos no preset {path}: {sorted(unknown)}")
    return PropRules(**data)
