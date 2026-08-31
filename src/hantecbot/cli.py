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
from .backtest.challenge import ChallengeReport, monte_carlo, run_challenge
from .backtest.engine import Backtester
from .backtest.optimizer import optimize, walk_forward
from .config import BotConfig, load_prop_rules
from .data import generate, load_csv, resample, save_csv
from .journal import Journal
from .research import (GateCriteria, GateResult, evaluate_gate, render_scan, scan)
from .validation import cost_stress, neighborhood_stability, portfolio
from .models import Candle
from .report import write_report

DISCLAIMER_PROP = (
    "\n⚠  As regras da mesa foram transcritas de um documento público em uma data\n"
    "   específica (campos `fonte` e `verificado_em` nos presets). Mesas mudam regra\n"
    "   sem aviso: confirme no painel/termos da sua conta ANTES de homologar.\n"
)

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


def _candles(args, cfg: Optional[BotConfig] = None) -> List[Candle]:
    if getattr(args, "csv", None):
        c = load_csv(args.csv, limit=getattr(args, "limit", None))
        if not c:
            raise SystemExit(f"nenhum candle lido de {args.csv}")
        tf = getattr(args, "resample", None)
        if tf:
            src = getattr(args, "source_tf", "M15")
            n0 = len(c)
            c = resample(c, src, tf)
            print(f"• reamostrado {src} → {tf}: {n0} → {len(c)} candles")
            if cfg is not None:
                cfg.timeframe = tf
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
    candles = _candles(args, cfg)
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


def _load_specs() -> dict:
    import yaml
    path = "config/symbols/specs.yaml"
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


SCAN_SPACES = {
    "trend_atr": {"fast": [13, 21, 34], "slow": [55, 89], "breakout": [20, 40],
                  "atr_stop_mult": [1.5, 2.5], "reward_r": [2.0, 3.0]},
    # mais frouxo que o padrão: com os filtros originais a estratégia quase não opera
    "mean_reversion": {"ma_period": [20, 50], "band_mult": [1.5, 2.0, 2.5],
                       "rsi_buy": [25.0, 32.0], "rsi_sell": [68.0, 75.0],
                       "atr_stop_mult": [1.0, 2.0], "adx_max": [22.0, 30.0],
                       "trend_filter": [100]},
    "session_breakout": {"range_end_hour": [6, 7, 8], "trade_until_hour": [12, 16],
                         "atr_stop_mult": [1.0, 1.5], "reward_r": [1.5, 2.0, 3.0],
                         "buffer_atr": [0.0, 0.10], "min_range_atr": [0.3, 0.6]},
}


def _cfg_for(cfg, specs: dict, row) -> "BotConfig":
    """Config equivalente à usada no scan para um (ativo, timeframe, estratégia)."""
    from .models import SymbolSpec

    c = deepcopy(cfg)
    c.timeframe = row.timeframe
    c.strategy.name = row.strategy
    c.strategy.params = {}
    if specs and row.symbol in specs:
        spec_cfg = dict(specs[row.symbol])
        overrides = spec_cfg.pop("risk_overrides", {}) or {}
        c.symbol = SymbolSpec(**spec_cfg)
        for k, v in overrides.items():
            setattr(c.risk, k, v)
    c.risk.trading_hours_utc = list(range(24))
    return c


def cmd_scan(args) -> int:
    """Procura vantagem estatística em vários ativos/timeframes — e desconta o viés."""
    from .data import load_csv, resample

    cfg = _load_cfg(args.config)
    specs = _load_specs()
    datasets = {}
    for item in args.data:
        # formato: SIMBOLO:arquivo.csv:TF_ORIGEM[:TF1,TF2,...]
        parts = item.split(":")
        if len(parts) < 3:
            raise SystemExit(f"--data espera SIMBOLO:arquivo:TF_ORIGEM[:TFs], recebi {item!r}")
        symbol, path, src_tf = parts[0], parts[1], parts[2]
        targets = parts[3].split(",") if len(parts) > 3 else [src_tf]
        base = load_csv(path)
        if not base:
            raise SystemExit(f"nenhum candle em {path}")
        for tf in targets:
            candles = base if tf == src_tf else resample(base, src_tf, tf)
            datasets[(symbol, tf)] = candles
            print(f"• {symbol} {tf}: {len(candles)} candles "
                  f"({candles[0].time:%Y-%m-%d} → {candles[-1].time:%Y-%m-%d})")

    strategies = args.strategies.split(",")
    spaces = json.loads(args.space) if args.space else SCAN_SPACES
    if spaces and not isinstance(next(iter(spaces.values())), dict):
        spaces = {st: spaces for st in strategies}    # um espaço único para todas
    print(f"\nRodando walk-forward ({args.folds} janelas) em {len(datasets)} séries × "
          f"{len(strategies)} estratégias...\n")
    if not args.with_governor and cfg.risk.target_max_drawdown_pct:
        print(f"• governador de DD ({cfg.risk.target_max_drawdown_pct:.1f}%) DESLIGADO na "
              "pesquisa: risco constante mede o edge sem censurar a amostra "
              "(use --with-governor para incluí-lo)")
    rows = scan(datasets, cfg, strategies, spaces, folds=args.folds, specs=specs,
                dd_governor=args.with_governor)
    print(render_scan(rows))

    # --- carteira: séries com expectativa positiva compartilhando o mesmo capital
    positivas = [r for r in rows if r.oos_expectancy_r > 0 and r.oos_trades >= 20]
    if len(positivas) >= 2:
        pf = portfolio([(f"{r.symbol} {r.timeframe} {r.strategy}", r.trades_oos)
                        for r in positivas],
                       initial_balance=cfg.initial_balance,
                       risk_per_trade_pct=cfg.risk.risk_per_trade_pct)
        print("\n" + pf.render())
        print("  (diversificar não cria vantagem: só reduz a variância da que existir)")

    stress = stability = None
    if rows and args.stress:
        best = rows[0]
        candles = datasets[(best.symbol, best.timeframe)]
        cbest = _cfg_for(cfg, specs, best)
        if not args.with_governor:
            cbest.risk.target_max_drawdown_pct = None   # mesmo regime da varredura
        params = best.params_por_janela[-1] if best.params_por_janela else {}
        print(f"\nEstressando o melhor candidato ({best.symbol} {best.timeframe} "
              f"{best.strategy}, params {params}) — série completa, referência:")
        stress = cost_stress(cbest, candles, params)
        print(stress.render())
        stability = neighborhood_stability(cbest, candles, params,
                                           spaces.get(best.strategy, {}))
        print(stability.render())

    if rows and args.gate:
        gate = evaluate_gate(rows[0], GateCriteria(),
                             demo_days=args.demo_days,
                             combos_tested=sum(r.combos_tested for r in rows),
                             cost_survival=stress.survives_at if stress else None,
                             stability_pct=stability.positive_pct if stability else None)
        print("\n" + gate.render())
        path = gate.save(args.gate)
        print(f"\n✓ veredito salvo em {path} (o comando `live` exige este arquivo)")
    print(DISCLAIMER)
    return 0


def cmd_gate(args) -> int:
    """Mostra o veredito de liberação salvo."""
    g = GateResult.load(args.arquivo)
    if g is None:
        print(f"nenhum veredito em {args.arquivo}. Rode `hantecbot scan --gate {args.arquivo}`.")
        return 1
    print(g.render())
    print(f"\ngerado em: {g.gerado_em}")
    print(f"contexto : {json.dumps(g.contexto.get('symbol', ''))} "
          f"{g.contexto.get('timeframe', '')} {g.contexto.get('strategy', '')}")
    return 0 if g.aprovado else 1


PLANOS = {
    "fast": ["config/fimathe/fast.yaml"],
    "double_stage": ["config/fimathe/double_stage_e1.yaml",
                     "config/fimathe/double_stage_e2.yaml"],
    "instant_lite": ["config/fimathe/instant_lite.yaml"],
    "financiada": ["config/fimathe/conta_financiada.yaml"],
}


def cmd_challenge(args) -> int:
    """Simula a homologação do EA nas regras da mesa proprietária."""
    cfg = _load_cfg(args.config)
    if args.strategy:
        cfg.strategy.name = args.strategy
    if args.balance:
        cfg.initial_balance = args.balance
    if args.safety:
        cfg.guard.safety_factor = args.safety
    if args.max_risk:
        cfg.guard.max_risk_per_trade_pct = args.max_risk

    paths = PLANOS.get(args.plano, [args.plano])
    rules = [load_prop_rules(p) for p in paths]
    candles = _candles(args, cfg)

    print(f"\nPlano: {args.plano}  |  {len(rules)} fase(s)  |  saldo inicial "
          f"{cfg.initial_balance:,.2f}")
    for r in rules:
        alvo = f"{r.profit_target_pct}%" if r.profit_target_pct is not None else "sem meta"
        total = f"{r.total_loss_pct}% {r.total_loss_mode}"
        print(f"  • {r.name}: meta {alvo} | perda diária {r.daily_loss_pct}% "
              f"| perda total {total} | dias lucrativos {r.min_profit_days}"
              + (f" | risco máx {r.max_risk_pct}%" if r.max_risk_pct else ""))
        print(f"    fonte: {r.fonte or '(sem fonte registrada)'} "
              f"| verificado em: {r.verificado_em or '?'}")

    report = run_challenge(cfg, candles, rules)
    print()
    print(report.render())

    ultima = report.fases[-1] if report.fases else None
    if ultima is not None and ultima.resultado is not None:
        res = ultima.resultado
        if res.rejections:
            top = sorted(res.rejections.items(), key=lambda kv: -kv[1])[:6]
            print("\n  Entradas barradas: " + ", ".join(f"{k} x{v}" for k, v in top))
        if args.montecarlo and res.daily_log:
            dailies = [100.0 * d[1] / cfg.initial_balance for d in res.daily_log]
            mc = monte_carlo(dailies, rules[0], cfg.initial_balance,
                             scenarios=args.scenarios, max_days=args.max_days)
            print(f"\nMonte Carlo ({rules[0].name}, bootstrap de {len(dailies)} dias reais):")
            print(mc.render())
        if args.report:
            path = write_report(args.report, res.metrics, res.trades, res.equity_curve,
                                title=f"Homologação {args.plano} — {cfg.symbol.symbol}",
                                meta={"plano": args.plano,
                                      "fonte das regras": rules[0].fonte,
                                      "verificado em": rules[0].verificado_em,
                                      "veredito": "APROVADO" if report.aprovado else "REPROVADO",
                                      "risco por trade": f"{cfg.risk.risk_per_trade_pct:.2f}%",
                                      "safety factor": cfg.guard.safety_factor})
            print(f"\n✓ relatório HTML: {path}")
    print(DISCLAIMER_PROP)
    return 0 if report.aprovado else 1


DEFAULT_SPACES = {
    "trend_atr": {"fast": [13, 21, 34], "slow": [55, 89], "breakout": [20, 40],
                  "atr_stop_mult": [1.5, 2.0, 3.0], "reward_r": [2.0, 3.0, 4.0],
                  "adx_min": [18.0, 25.0]},
    "mean_reversion": {"ma_period": [20, 30], "band_mult": [2.0, 2.5],
                       "rsi_buy": [20.0, 25.0, 30.0], "atr_stop_mult": [1.0, 1.5, 2.0],
                       "adx_max": [18.0, 22.0]},
    "session_breakout": {"range_end_hour": [6, 7, 8], "trade_until_hour": [12, 16],
                         "atr_stop_mult": [1.0, 1.5], "reward_r": [1.5, 2.0, 3.0],
                         "buffer_atr": [0.0, 0.10], "min_range_atr": [0.3, 0.6]},
}


def _space(args, cfg) -> dict:
    if args.space:
        return json.loads(args.space)
    return DEFAULT_SPACES.get(cfg.strategy.name, DEFAULT_SPACES["trend_atr"])


def cmd_optimize(args) -> int:
    cfg = _load_cfg(args.config)
    if args.strategy:
        cfg.strategy.name = args.strategy
    candles = _candles(args, cfg)
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
    candles = _candles(args, cfg)
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
    gate = GateResult.load(args.gate_file)
    if gate is None or not gate.aprovado:
        print("🚫 Operação ao vivo bloqueada: não há veredito de liberação aprovado em "
              f"{args.gate_file}.")
        if gate is not None:
            print()
            print(gate.render())
        print("\nGere evidência primeiro:\n"
              "  hantecbot scan --data SIMBOLO:arquivo.csv:TF --gate runs/gate.json\n"
              "Rodar sem vantagem comprovada é a forma mais cara de descobrir que ela não existe.")
        if not args.force:
            return 2
        print("\n⚠  --force usado: seguindo mesmo sem liberação. A responsabilidade é sua.")
    if getattr(args, "plano", None):
        paths = PLANOS.get(args.plano, [args.plano])
        cfg.prop = load_prop_rules(paths[0])
        cfg.apply_prop_rules()
        print(f"• regras da mesa aplicadas: {cfg.prop.name} "
              f"(verificado em {cfg.prop.verificado_em}) | risco por trade "
              f"ajustado para {cfg.risk.risk_per_trade_pct:.2f}%")
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
        sp.add_argument("--strategy",
                        choices=["trend_atr", "mean_reversion", "session_breakout"])
        sp.add_argument("--resample", help="agregar para outro timeframe (H1, H4, D1...)")
        sp.add_argument("--source-tf", default="M15", help="timeframe do CSV de origem")

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

    sc = sub.add_parser("scan", help="procurar vantagem em vários ativos (walk-forward)")
    sc.add_argument("-c", "--config", default="config/default.yaml")
    sc.add_argument("--data", nargs="+", required=True,
                    metavar="SIMBOLO:arquivo.csv:TF[:TFs]",
                    help="ex.: EURUSD:data/EURUSD_H1.csv:H1:H1,H4")
    sc.add_argument("--strategies", default="trend_atr,mean_reversion")
    sc.add_argument("--space", help="JSON do espaço de busca")
    sc.add_argument("--folds", type=int, default=4)
    sc.add_argument("--gate", help="salvar veredito de liberação neste arquivo")
    sc.add_argument("--demo-days", type=int, help="dias já rodados em conta demo")
    sc.add_argument("--with-governor", action="store_true",
                    help="manter o governador de drawdown ligado durante a pesquisa")
    sc.add_argument("--stress", action="store_true",
                    help="testar o melhor candidato com custos maiores e parâmetros vizinhos")
    sc.set_defaults(func=cmd_scan)

    g = sub.add_parser("gate", help="ver o veredito de liberação para o vivo")
    g.add_argument("arquivo", nargs="?", default="runs/gate.json")
    g.set_defaults(func=cmd_gate)

    ch = sub.add_parser("challenge", help="simular a homologação numa mesa proprietária")
    common(ch)
    ch.add_argument("--plano", default="double_stage",
                    help="fast | double_stage | instant_lite | financiada | caminho de YAML")
    ch.add_argument("--balance", type=float, help="saldo inicial da conta do desafio")
    ch.add_argument("--safety", type=float, help="fração do limite diário usada (0-1)")
    ch.add_argument("--max-risk", type=float, help="teto de risco por operação (%%)")
    ch.add_argument("--montecarlo", action="store_true", help="estimar P(aprovar)")
    ch.add_argument("--scenarios", type=int, default=5000)
    ch.add_argument("--max-days", type=int, default=60)
    ch.add_argument("--report")
    ch.set_defaults(func=cmd_challenge)

    l = sub.add_parser("live", help="operar via MT5 (demo por padrão)")
    l.add_argument("-c", "--config", default="config/default.yaml")
    l.add_argument("--live", action="store_true", help="autorizar conta REAL")
    l.add_argument("--out-dir", default="runs")
    l.add_argument("--plano", help="aplicar regras de mesa ao vivo (ex.: double_stage)")
    l.add_argument("--gate-file", default="runs/gate.json",
                   help="veredito de liberação exigido para operar")
    l.add_argument("--force", action="store_true",
                   help="ignorar a trava de liberação (não recomendado)")
    l.set_defaults(func=cmd_live)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
