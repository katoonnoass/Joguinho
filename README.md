# hantecbot 🤖📈

Robô de trading algorítmico para contas **Hantec Markets** via **MetaTrader 5** — com
backtest honesto, validação walk-forward, gestão de risco com kill switch e execução
ao vivo (demo por padrão).

> ### ⚠️ Leia antes de tudo
> Forex e CFDs são produtos alavancados de alto risco — **a maioria das contas de
> varejo perde dinheiro**. Nenhum robô "ganha muito dinheiro" garantidamente; o que
> existe é **vantagem estatística pequena + gestão de risco rígida + tempo**.
> Este projeto é uma ferramenta de pesquisa e automação, **não** é recomendação de
> investimento e **não promete lucro**. As estratégias incluídas são pontos de partida:
> valide com os seus dados, em conta **demo**, antes de considerar dinheiro real.

---

## O que tem aqui

| Módulo | Papel |
|---|---|
| `hantecbot/strategies` | `trend_atr` (rompimento Donchian com filtro EMA+ADX) e `mean_reversion` (bandas + RSI em mercado lateral) |
| `hantecbot/risk.py` | tamanho de posição por % de equity, kill switch diário e de drawdown, filtros de spread/horário/stop mínimo |
| `hantecbot/management.py` | breakeven, realização parcial em 1R e trailing por ATR — **o mesmo código no backtest e ao vivo** |
| `hantecbot/backtest` | motor bar-a-bar com spread, slippage, comissão e swap; métricas (PF, expectativa em R, drawdown, Sharpe, Calmar) |
| `hantecbot/backtest/optimizer.py` | grid search **só no treino** + walk-forward out-of-sample |
| `hantecbot/broker/paper.py` | simulador realista (empate stop/alvo resolve a favor do stop) |
| `hantecbot/broker/mt5.py` | ponte com o terminal MT5 da Hantec (ordens, SL/TP, parciais) |
| `hantecbot/live/runner.py` | loop ao vivo, age só no fechamento de candle, diário JSONL/CSV |
| `hantecbot/report.py` | relatório HTML autocontido com curva de equity em SVG |

Zero dependências além de `PyYAML` (e `MetaTrader5` apenas no modo live).

## Instalação

```bash
make install          # cria .venv e instala em modo editável
make test             # 30 testes
```

## Uso em 4 passos

```bash
# 1. dados (sintéticos para experimentar, ou exporte um CSV do MT5)
.venv/bin/hantecbot demo-data --out data/synthetic_M15.csv --bars 30000

# 2. backtest com relatório HTML
.venv/bin/hantecbot backtest --csv data/synthetic_M15.csv --report reports/backtest.html

# 3. o teste que importa: walk-forward out-of-sample
.venv/bin/hantecbot walkforward --csv data/synthetic_M15.csv --folds 4 \
    --report reports/walkforward.html

# 4. replay em modo paper (gera diário de operações em runs/)
.venv/bin/hantecbot paper --csv data/synthetic_M15.csv
```

Ao vivo, na Hantec (Windows/Wine com o terminal MT5 instalado):

```bash
pip install MetaTrader5
export HANTEC_LOGIN=12345678
export HANTEC_PASSWORD='sua-senha'
export HANTEC_SERVER='HantecMarkets-Demo'
hantecbot live -c config/default.yaml          # demo
hantecbot live -c config/default.yaml --live   # conta real: exige confirmação digitada
```

Credenciais **nunca** vão para o YAML nem para o Git — só variáveis de ambiente.

## Como usar dados reais da Hantec

No terminal MT5: `Ferramentas → Centro de Cotações` (baixe o histórico do símbolo),
depois `Arquivo → Abrir gráfico offline`/exportação CSV. O loader aceita cabeçalhos
`time,open,high,low,close,volume` e também o formato tabulado `<DATE> <TIME> <OPEN>…`.

```bash
hantecbot backtest --csv data/EURUSD_M15.csv --report reports/eurusd.html
```

## A regra de risco padrão (config/default.yaml)

| Parâmetro | Valor | Porquê |
|---|---|---|
| `risk_per_trade_pct` | 0,5% | com 20 perdas seguidas você ainda tem ~90% do capital |
| `max_daily_loss_pct` | 2% | um dia ruim não vira um mês ruim |
| `max_drawdown_pct` | 10% | desliga o robô e força revisão do sistema |
| `max_consecutive_losses` | 5 | pausa até o próximo pregão |
| `max_spread_points` | 25 | não entra em spread alargado (notícia/rollover) |
| `partial_take_at_r` / `breakeven_at_r` | 1R | tira risco da mesa cedo |

O `RiskManager` é o **único** ponto que autoriza uma entrada: estratégia propõe,
risco dispõe. Sinal sem stop definido é recusado por construção.

## Honestidade sobre resultados

* Os dados sintéticos gerados por `demo-data` são um passeio aleatório: **não existe
  vantagem estatística real neles**. Servem para exercitar o motor, não para provar
  lucratividade. Números bonitos ali são sorte de semente.
* O backtest já cobra spread, slippage, comissão e swap, e resolve empate
  stop/alvo a favor do stop. Ainda assim, backtest é o **melhor caso**.
* Otimizar no histórico inteiro produz robôs que só ganham no passado. Use
  `walkforward`: ele otimiza no treino e mede no período seguinte, sem reajuste.
* Critério mínimo antes de pensar em dinheiro real: walk-forward positivo em várias
  janelas, > 200 operações, drawdown tolerável **e** 3 meses de conta demo com
  comportamento parecido com o simulado.

## Estrutura

```
src/hantecbot/
  models.py indicators.py stream.py risk.py management.py journal.py report.py cli.py
  strategies/{base,trend_atr,mean_reversion}.py
  broker/{base,paper,mt5}.py
  backtest/{engine,metrics,optimizer}.py
  live/runner.py
config/default.yaml   tests/   Makefile   ci/github-actions-ci.yml
```

## Roadmap

- [ ] múltiplos símbolos em paralelo com limite de risco por portfólio
- [ ] filtro de calendário econômico (não operar 15 min antes de NFP/CPI)
- [ ] otimização bayesiana no lugar do grid
- [ ] notificações via Telegram

Licença MIT. Use por sua conta e risco.
