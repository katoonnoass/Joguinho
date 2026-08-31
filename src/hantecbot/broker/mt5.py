"""Adaptador MetaTrader 5 — ponte com a conta Hantec (demo ou real).

Requer Windows (ou Wine) com o terminal MT5 da Hantec instalado e a lib
`MetaTrader5` (`pip install MetaTrader5`). Em Linux puro o import falha de
propósito, com mensagem clara: use `paper`/`backtest` aqui.

Credenciais SEMPRE via variáveis de ambiente:
    HANTEC_LOGIN, HANTEC_PASSWORD, HANTEC_SERVER  (ex.: HantecMarkets-Demo)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence

from ..config import BotConfig
from ..models import AccountState, Candle, Position, Side, SymbolSpec, Trade
from .base import Broker, Quote

TIMEFRAME_MAP = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
                 "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
                 "D1": "TIMEFRAME_D1"}


def _import_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:  # pragma: no cover - depende do SO
        raise RuntimeError(
            "MetaTrader5 indisponível neste ambiente.\n"
            "  • Instale o terminal MT5 da Hantec (Windows/Wine) e `pip install MetaTrader5`.\n"
            "  • Enquanto isso use: hantecbot backtest / hantecbot paper."
        ) from exc
    return mt5


class MT5Broker(Broker):
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.mt5 = _import_mt5()
        self.symbol_name = cfg.symbol.symbol
        self.spec: SymbolSpec = cfg.symbol
        self._connect()
        self._sync_spec()

    # ----------------------------------------------------------------- conexão
    def _connect(self) -> None:
        mt5 = self.mt5
        kwargs = {}
        if self.cfg.mt5_terminal_path:
            kwargs["path"] = self.cfg.mt5_terminal_path
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"mt5.initialize falhou: {mt5.last_error()}")
        if self.cfg.mt5_login:
            ok = mt5.login(self.cfg.mt5_login, password=self.cfg.mt5_password,
                           server=self.cfg.mt5_server)
            if not ok:
                raise RuntimeError(f"login Hantec falhou: {mt5.last_error()}")
        if not mt5.symbol_select(self.symbol_name, True):
            raise RuntimeError(f"símbolo {self.symbol_name} indisponível na conta")

    def _sync_spec(self) -> None:
        info = self.mt5.symbol_info(self.symbol_name)
        if info is None:
            raise RuntimeError(f"symbol_info({self.symbol_name}) devolveu None")
        s = self.spec
        s.digits = info.digits
        s.point = info.point
        s.contract_size = info.trade_contract_size
        s.volume_min = info.volume_min
        s.volume_max = info.volume_max
        s.volume_step = info.volume_step
        s.spread_points = float(getattr(info, "spread", s.spread_points))

    def is_demo(self) -> bool:
        acc = self.mt5.account_info()
        if acc is None:
            return False
        return int(getattr(acc, "trade_mode", 0)) == int(
            getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))

    def shutdown(self) -> None:
        try:
            self.mt5.shutdown()
        except Exception:  # pragma: no cover
            pass

    # -------------------------------------------------------------- dados
    def history(self, count: int = 500) -> List[Candle]:
        mt5 = self.mt5
        tf = getattr(mt5, TIMEFRAME_MAP[self.cfg.timeframe.upper()])
        rates = mt5.copy_rates_from_pos(self.symbol_name, tf, 1, count)  # pula o candle em formação
        if rates is None:
            raise RuntimeError(f"copy_rates falhou: {mt5.last_error()}")
        return [Candle(time=datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
                       open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                       close=float(r["close"]), volume=float(r["tick_volume"]))
                for r in rates]

    def quote(self) -> Quote:
        t = self.mt5.symbol_info_tick(self.symbol_name)
        if t is None:
            raise RuntimeError("tick indisponível")
        return Quote(datetime.fromtimestamp(int(t.time), tz=timezone.utc),
                     bid=float(t.bid), ask=float(t.ask))

    def account(self) -> AccountState:
        a = self.mt5.account_info()
        if a is None:
            raise RuntimeError("account_info indisponível")
        return AccountState(balance=float(a.balance), equity=float(a.equity),
                            open_positions=1 if self.position() else 0,
                            extras={"margin_level": float(getattr(a, "margin_level", 0.0)),
                                    "currency": a.currency, "leverage": a.leverage})

    def _raw_position(self):
        positions = self.mt5.positions_get(symbol=self.symbol_name) or []
        for p in positions:
            if p.magic == self.cfg.magic:
                return p
        return None

    def position(self) -> Optional[Position]:
        p = self._raw_position()
        if p is None:
            return None
        return Position(symbol=p.symbol,
                        side=Side.BUY if p.type == self.mt5.POSITION_TYPE_BUY else Side.SELL,
                        volume=float(p.volume), entry_price=float(p.price_open),
                        stop=float(p.sl), take=float(p.tp) or None,
                        opened_at=datetime.fromtimestamp(int(p.time), tz=timezone.utc),
                        reason=p.comment, magic=p.magic)

    # ------------------------------------------------------------- execução
    def open(self, side: Side, volume: float, stop: float, take: Optional[float],
             reason: str = "") -> Optional[Position]:
        mt5 = self.mt5
        tick = mt5.symbol_info_tick(self.symbol_name)
        price = tick.ask if side is Side.BUY else tick.bid
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol_name,
            "volume": self.spec.normalize_volume(volume),
            "type": mt5.ORDER_TYPE_BUY if side is Side.BUY else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": self.spec.round_price(stop),
            "tp": self.spec.round_price(take) if take else 0.0,
            "deviation": int(self.cfg.execution.slippage_points),
            "magic": self.cfg.magic,
            "comment": (reason or "hantecbot")[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(),
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"ordem rejeitada: {getattr(res, 'retcode', None)} "
                               f"{getattr(res, 'comment', mt5.last_error())}")
        return self.position()

    def _filling_mode(self):
        mt5 = self.mt5
        info = mt5.symbol_info(self.symbol_name)
        modes = int(getattr(info, "filling_mode", 0))
        if modes & 1:
            return mt5.ORDER_FILLING_FOK
        if modes & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def modify(self, stop: Optional[float] = None, take: Optional[float] = None) -> bool:
        mt5 = self.mt5
        p = self._raw_position()
        if p is None:
            return False
        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": self.symbol_name,
               "position": p.ticket,
               "sl": self.spec.round_price(stop) if stop is not None else p.sl,
               "tp": self.spec.round_price(take) if take is not None else p.tp}
        res = mt5.order_send(req)
        return bool(res and res.retcode == mt5.TRADE_RETCODE_DONE)

    def close(self, reason: str = "", fraction: float = 1.0) -> Optional[Trade]:
        mt5 = self.mt5
        p = self._raw_position()
        if p is None:
            return None
        vol = self.spec.normalize_volume(float(p.volume) * max(0.0, min(1.0, fraction)))
        if vol <= 0:
            return None
        tick = mt5.symbol_info_tick(self.symbol_name)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol_name, "volume": vol,
               "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
               "position": p.ticket, "price": tick.bid if is_buy else tick.ask,
               "deviation": int(self.cfg.execution.slippage_points),
               "magic": self.cfg.magic, "comment": (reason or "close")[:31],
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling_mode()}
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"fechamento rejeitado: {getattr(res, 'comment', mt5.last_error())}")
        exit_price = float(getattr(res, "price", 0.0)) or float(tick.bid if is_buy else tick.ask)
        return Trade(symbol=self.symbol_name,
                     side=Side.BUY if is_buy else Side.SELL, volume=vol,
                     entry_time=datetime.fromtimestamp(int(p.time), tz=timezone.utc),
                     entry_price=float(p.price_open), exit_time=datetime.now(timezone.utc),
                     exit_price=exit_price, pnl=float(p.profit), reason_in=p.comment,
                     reason_out=reason)
