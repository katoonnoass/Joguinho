"""CLI do hantecbot.

    hantecbot demo-data     gera dados sintéticos para experimentar offline
    hantecbot backtest      simula a estratégia sobre um CSV
    hantecbot optimize      grid search (apenas na janela de treino)
    hantecbot walkforward   validação out-of-sample (o teste que importa)
    hantecbot paper         execução simulada em tempo real sobre um CSV/feed
    hantecbot live          execução no MT5 da Hantec (demo por padrão)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from typing import List, Optional, Sequence

from . import __version__
from .backtest.engine import Backtester
from .backtest.optimizer import optimize, walk_forward
from .config import BotConfig
from .data import generate, load_csv, save_csv
from .journal import Journal
from .models import Candle
from .report import write_report

DISCLAIMER = (
    "\n⚠  Trading de forex/CFD é alavancado e de alto risco: a maioria das contas de\n"
    "   varejo perde dinheiro. Este software é ferramenta de pesquisa e automação,\n"
    "   não conselho financeiro nem promessa de lucro. Use conta DEMO primeiro.\n"
)


def _load_cfg(path: Optional[str]) -> BotConfig:
    if path and os.path.exists(path):
        return BotConfig.load(path)
    if path:
        raise SystemExit(f"config não encontrada: {path}")
    return BotConfig()


def _candles(args) -> List[Candle]:
    if getattr(args, "csv", None):
        c = load_csv(args.csv, limit=getattr(args, "limit", None))
        if not c:
            raise SystemExit(f"nenhum candle lido de {args.csv}")
        return c
    print("• nenhum CSV informado — usando série sintética (apenas demonstração)")
    return generate(bars=getattr(args, "bars", 20000), timeframe="M15",
                    seed=getattr(args, "seed", 42))


# --------------------------------------------------------------------- comandos
def cmd_demo_data(args) -> int:
    candles = generate(bars=args.bars, timeframe=args.timeframe, seed=args.seed)
    n = save_csv(args.out, candles)
    print(f"✓ {n} candles {args.timeframe} sintéticos → {args.out}")
    return 0


def cmd_backtest(args) -> int:
    cfg = _load_cfg(args.config)
    if args.strategy:
        cfg.strategy.name = args.strategy
    if args.params:
        cfg.strategy.params.update(json.loads(args.params))
    if args.balance:
        cfg.initial_balance = args.balance
    candles = _candles(args)
    res = Backtester(cfg).run(candles)

    print(f"\nEstratégia: {cfg.strategy.name}  |  {cfg.symbol.symbol} {cfg.timeframe}  "
          f"|  {len(candles)} candles  ({candles[0].time:%Y-%m-%d} → {candles[-1].time:%Y-%m-%d})")
    print(res.summary())
    if res.rejections:
        top = sorted(res.rejections.items(), key=lambda kv: -kv[1])[:5]
        print("\n  Sinais recusados pelo risco: " +
              ", ".join(f"{k} x{v}" for k, v in top))
    if args.report:
        path = write_report(args.report, res.metrics, res.trades, res.equity_curve,
                            title=f"Backtest {cfg.strategy.name} — {cfg.symbol.symbol}",
                            meta={"timeframe": cfg.timeframe,
                                  "parâmetros": res.config["params"],
                                  "risco por trade": f"{cfg.risk.risk_per_trade_pct}%",
                                  "candles": len(candles)})
        print(f"\n✓ relatório HTML: {path}")
    print(DISCLAIMER)
    return 0


DEFAULT_SPACES = {
    "trend_atr": {"fast": [13, 21, 34], "slow": [55, 89], "breakout": [20, 40],
                  "atr_stop_mult": [1.5, 2.0, 3.0], "reward_r": [2.0, 3.0, 4.0],
                  "adx_min": [18.0, 25.0]},
    "mean_reversion": {"ma_period": [20, 30], "band_mult": [2.0, 2.5],
                       "rsi_buy": [20.0, 25.0, 30.0], "atr_stop_mult": [1.0, 1.5, 2.0],
                       "adx_max": [18.0, 22.0]},
}


def _space(args, cfg) -> dict:
    if args.space:
        return json.loads(args.space)
    return DEFAULT_SPACES.get(cfg.strategy.name, DEFAULT_SPACES["trend_atr"])


def cmd_optimize(args) -> int:
    cfg = _load_cfg(args.config)
    if args.strategy:
        cfg.strategy.name = args.strategy
    candles = _candles(args)
    cut = int(len(candles) * 0.7)
    train = candles[:cut]
    space = _space(args, cfg)
    print(f"• grid: {space}\n• treino: {len(train)} candles (30% finais reservados)")
    results = optimize(cfg, train, space)
    print(f"\nTop {min(args.top, len(results))} conjuntos (in-sample, treino):")
    for r in results[:args.top]:
        m = r.metrics
        print(f"  score {r.score:8.2f} | ret {m.return_pct:+7.2f}% | DD {m.max_drawdown_pct:5.2f}% "
              f"| PF {m.profit_factor:4.2f} | {m.trades:4d} trades | {r.params}")
    best = results[0]
    print("\nValidação no período reservado (out-of-sample):")
    c2 = deepcopy(cfg)
    c2.strategy.params = {**cfg.strategy.params, **best.params}
    res = Backtester(c2).run(candles[cut:])
    print(res.summary())
    print("\n⚠ Se o desempenho out-of-sample despencar, o conjunto está sobreajustado.")
    print(DISCLAIMER)
    return 0


def cmd_walkforward(args) -> int:
    cfg = _load_cfg(args.config)
    if args.strategy:
        cfg.strategy.name = args.strategy
    candles = _candles(args)
    wf = walk_forward(cfg, candles, _space(args, cfg), folds=args.folds)
    print(wf.render())
    if args.report:
        path = write_report(args.report, wf.oos_metrics, wf.oos_trades, wf.equity_curve,
                            title=f"Walk-forward {cfg.strategy.name} — {cfg.symbol.symbol}",
                            meta={"janelas": args.folds, "timeframe": cfg.timeframe})
        print(f"\n✓ relatório HTML: {path}")
    print(DISCLAIMER)
    return 0


def cmd_paper(args) -> int:
    """Replay em tempo acelerado usando o broker simulado (sem MT5)."""
    from .broker.paper import PaperBroker
    from .live.runner import LiveRunner

    cfg = _load_cfg(args.config)
    candles = _candles(args)
    broker = PaperBroker(cfg.symbol, cfg.initial_balance, cfg.execution.slippage_points)

    class ReplayBroker(PaperBroker):
        def is_demo(self) -> bool:
            return True

    broker.__class__ = ReplayBroker
    cfg.poll_seconds = 0
    journal = Journal(directory=args.out_dir)
    runner = LiveRunner(cfg, broker, allow_live=False, journal=journal)
    runner.preflight()
    for c in candles:
        broker.feed(c)
        broker.check_stops(c)
        if len(broker.history()) >= runner.strategy.warmup:
            try:
                runner.tick()
            except Exception as exc:
                journal.event("error", message=str(exc))
    if broker.position():
        broker.close("fim do replay")
    from .backtest.metrics import compute_metrics
    m = compute_metrics(broker.closed_trades(), broker.equity_curve, cfg.initial_balance)
    print(m.render())
    print(f"\n✓ diário: {journal.trades_path}")
    print(DISCLAIMER)
    return 0


def cmd_live(args) -> int:
    cfg = _load_cfg(args.config)
    from .broker.mt5 import MT5Broker
    from .live.runner import LiveRunner

    broker = MT5Broker(cfg)
    demo = broker.is_demo()
    print(f"• conectado ao MT5 | conta {'DEMO' if demo else 'REAL'} "
          f"| servidor {cfg.mt5_server} | {cfg.symbol.symbol} {cfg.timeframe}")
    if not demo and not args.live:
        print("✋ conta real sem --live: abortando por segurança.")
        return 2
    if not demo:
        confirm = input("Digite EU ACEITO O RISCO para operar dinheiro real: ")
        if confirm.strip().upper() != "EU ACEITO O RISCO":
            print("abortado.")
            return 2
    runner = LiveRunner(cfg, broker, allow_live=args.live, journal=Journal(args.out_dir))
    try:
        runner.run()
    finally:
        broker.shutdown()
    return 0


# ------------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hantecbot",
                                description="Robô de trading algorítmico para contas Hantec (MT5).")
    p.add_argument("--version", action="version", version=f"hantecbot {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-c", "--config", default="config/default.yaml")
        sp.add_argument("--csv", help="arquivo de candles (export MT5)")
        sp.add_argument("--bars", type=int, default=20000, help="candles sintéticos se não houver CSV")
        sp.add_argument("--limit", type=int, help="usar apenas os N candles finais")
        sp.add_argument("--seed", type=int, default=42)
        sp.add_argument("--strategy", choices=["trend_atr", "mean_reversion"])

    d = sub.add_parser("demo-data", help="gerar CSV sintético")
    d.add_argument("--out", default="data/synthetic_M15.csv")
    d.add_argument("--bars", type=int, default=30000)
    d.add_argument("--timeframe", default="M15")
    d.add_argument("--seed", type=int, default=42)
    d.set_defaults(func=cmd_demo_data)

    b = sub.add_parser("backtest", help="simular a estratégia")
    common(b)
    b.add_argument("--params", help='JSON com overrides, ex: \'{"fast":13}\'')
    b.add_argument("--balance", type=float)
    b.add_argument("--report", help="caminho do relatório HTML")
    b.set_defaults(func=cmd_backtest)

    o = sub.add_parser("optimize", help="grid search no treino + validação")
    common(o)
    o.add_argument("--space", help="JSON do espaço de busca")
    o.add_argument("--top", type=int, default=10)
    o.set_defaults(func=cmd_optimize)

    w = sub.add_parser("walkforward", help="validação out-of-sample em janelas")
    common(w)
    w.add_argument("--space", help="JSON do espaço de busca")
    w.add_argument("--folds", type=int, default=4)
    w.add_argument("--report")
    w.set_defaults(func=cmd_walkforward)

    pa = sub.add_parser("paper", help="replay realista sem corretora")
    common(pa)
    pa.add_argument("--out-dir", default="runs")
    pa.set_defaults(func=cmd_paper)

    l = sub.add_parser("live", help="operar via MT5 (demo por padrão)")
    l.add_argument("-c", "--config", default="config/default.yaml")
    l.add_argument("--live", action="store_true", help="autorizar conta REAL")
    l.add_argument("--out-dir", default="runs")
    l.set_defaults(func=cmd_live)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
