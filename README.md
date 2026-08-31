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
| `hantecbot/prop.py` | **conformidade com mesa proprietária**: pisos diário/total, risco máximo, dias lucrativos, consistência, inatividade |
| `hantecbot/backtest/challenge.py` | simula a homologação (fases encadeadas) e estima **P(aprovar)** por Monte Carlo |
| `hantecbot/research.py` | varredura multi-ativo, correção de múltiplos testes e **trava de liberação** para o vivo |
| `hantecbot/validation.py` | bootstrap por blocos, deflated sharpe, estresse de custos, platô de parâmetros e carteira |

Zero dependências além de `PyYAML` (e `MetaTrader5` apenas no modo live).

## Instalação

```bash
make install          # cria .venv e instala em modo editável
make test             # 91 testes
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

## Trava de liberação: o robô não vai ao vivo sem evidência

A perda mais cara não vem do mercado, vem de operar sem vantagem comprovada.
Por isso `hantecbot live` **recusa** rodar sem um veredito aprovado:

```bash
hantecbot scan --data XAUUSD:data/XAUUSD_M15.csv:M15:H1,H4 \
                     EURUSD:data/EURUSD_H1.csv:H1:H1,H4 \
    --strategies trend_atr,mean_reversion --folds 4 --stress --gate runs/gate.json
hantecbot gate            # ver o veredito
hantecbot live --plano double_stage   # bloqueado até o veredito ser aprovado
```

O scan roda walk-forward em cada (ativo, timeframe, estratégia) e aplica **cinco
filtros de autoengano** — quase nunca usados juntos em robôs de varejo:

1. **Correção de múltiplos testes (Šidák)** — testar 4.032 configurações produz
   "vencedoras" por puro acaso; o t exigido sobe junto com o número de testes.
2. **Bootstrap por blocos** — reamostra os R-múltiplos em blocos (preserva as
   sequências de perdas) e mede P(média ≤ 0), sem supor normalidade.
3. **Deflated Sharpe Ratio** (Bailey & López de Prado) — desconta o Sharpe que o
   *melhor de N tentativas* exibiria no ruído, corrigindo assimetria e caudas.
4. **Estresse de custos** (`--stress`) — repete tudo com spread, comissão, swap e
   slippage ×1,5 e ×2. Vantagem que morre com custo maior não é vantagem.
5. **Platô de parâmetros** (`--stress`) — testa os vizinhos do conjunto escolhido:
   pico isolado é sobreajuste, platô é robustez.

Além disso o scan monta uma **carteira** com as séries de expectativa positiva
(mesmo capital, risco por operação normalizado): diversificar não cria vantagem,
mas reduz a variância da que existir.

```
Combinações testadas no total: 4032
t crítico com correção de múltiplos testes (Šidák): 4.36
Melhor t observado: +2.23 → NÃO É EVIDÊNCIA: dentro do que a sorte explica

  [ ] amostra out-of-sample          32 trades (mín. 200)
  [x] profit factor OOS              2.46 (mín. 1.2)
  [ ] significância corrigida        t=+2.23 (mín. 4.36 após 4032 testes)
  [ ] bootstrap por blocos           p=0.0015 (máx. 0.00001 = alpha corrigido)
  [ ] deflated sharpe                DSR=0.307 (mín. 0.95)
  [x] resiste a custos maiores       sobrevive até ×2.0 (mín. ×1.5)
  [x] platô de parâmetros            100% dos vizinhos positivos (mín. 60%)
  [ ] dias em conta demo             não informado (mín. 60)
🚫 BLOQUEADO — não pague desafio nem ligue conta real ainda
```

Melhor candidato encontrado até agora: **XAU/USD H4** (PF 2,46, 4/4 janelas
positivas, DD 1,27%, sobrevive a 2× os custos, 6/6 vizinhos positivos) — ainda
assim **reprovado**: 32 trades não provam nada. Detalhes, tabela completa e o
caminho para virar o jogo em
[`docs/ganhar-e-nao-perder.md`](docs/ganhar-e-nao-perder.md).

## Mesa proprietária (Fimathe) — homologação do EA

O objetivo aqui **não é maximizar lucro, é ser aprovado**: o robô só usa uma fração
do limite oficial e prefere parar a arriscar a conta.

```bash
# simula a homologação nas regras do plano, com relatório e probabilidade de passar
hantecbot challenge --plano double_stage --csv data/EURUSD_M15.csv \
    --balance 100000 --montecarlo --report reports/homologacao.html

hantecbot challenge --plano fast          --csv data/EURUSD_M15.csv --montecarlo
hantecbot challenge --plano instant_lite  --csv data/EURUSD_M15.csv --montecarlo

# ao vivo, aplicando as regras da mesa como trava dura
hantecbot live -c config/default.yaml --plano double_stage
```

As regras ficam em presets versionados com **fonte e data de verificação**
(`config/fimathe/*.yaml`) — nada de número mágico no código:

| | Fast | Double Stage | Financiada | Instant Lite |
|---|---|---|---|---|
| Meta | 10% | 10% → 5% | — | — |
| Perda diária | 5% | 5% | 5% | **3%** |
| Perda total | **6% trailing** | **10% estático** | idem desafio | **5% trailing** |
| Risco máx. (flutuante) | — | — | 3% | **1%** |
| Dias lucrativos | — | 3 (≥0,5%) | 3 | 5 (≥0,5%) |
| Consistência | — | — | — | 20% |

Transcrito do PDF oficial "Regras Oficiais da Fimathe Prop – Fast, Double Stage e
Instant Lite" (Mar/2026), verificado em 2026-08-31 — detalhes, exemplos numéricos e
ritual de atualização em [`docs/regras-fimathe.md`](docs/regras-fimathe.md).
**Confirme sempre no painel da sua conta antes de homologar.**

### O que o guard faz na prática

* **piso diário** calculado como a mesa calcula: maior valor entre saldo e equity no
  fechamento do dia anterior (virar o dia no lucro *sobe* a régua);
* **corte de tamanho**: cada ordem é limitada pela folga que ainda existe até o piso
  diário, até o piso total e até a regra de risco máximo — o que for menor;
* **`safety_factor`** (padrão 0,5): o robô só gasta metade do limite oficial do dia;
* **trava do dia** por perda *e* por lucro (encerrar no verde ajuda a consistência);
* **zera posição antes do rollover**, para não deixar flutuante mexer na régua do dia;
* **keep-alive**: 30 dias sem operar é violação grave; após 25 dias parado o robô abre
  uma posição de volume mínimo só para zerar o contador (`guard.keepalive_after_days`,
  pode desligar e receber só o alerta);
* **para de operar ao bater a meta** da fase — desafio aprovado não se arrisca mais.

Exemplo de saída:

```
⏳ NÃO CONCLUÍDO  —  fimathe_double_stage_e1
    retorno            : -0.39%
    dias operados      : 99 (24 lucrativos)
    pior dia           : -1.70%          <- limite oficial: -5%
    maior pausa        : 4 dias sem operar (violação em 30)
    consistência       : 4.3% (melhor dia / lucro)
    encerrado por      : kill switch interno: drawdown máximo atingido (-6.33%)

Monte Carlo (bootstrap de 99 dias reais):
  P(aprovar)  :   4.1%      P(violar)  :   5.4%
```

Leia assim: o EA **não violou a mesa** (o kill switch interno de 6% agiu antes do piso
de 10%), mas com esta estratégia/dados a chance de aprovação é baixa — o que significa
"melhore a vantagem estatística antes de pagar o desafio", não "aumente o risco".

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

## Resultado com dados reais (leia antes de sonhar)

Rodamos 8 anos de EUR/USD M15 real (195.576 candles, 2012-2020):

| TF | trades | retorno | PF | custos pagos | **bruto antes de custos** |
|---:|---:|---:|---:|---:|---:|
| M15 | 4.285 | -94,2% | 0,72 | 3.491 | -5.933 |
| H1 | 1.238 | -14,4% | 0,94 | 1.462 | **+22** |
| H4 | 391 | -8,4% | 0,89 | 230 | -612 |
| D1 | 59 | +1,8% | 1,19 | 12 | +188 |

Walk-forward out-of-sample: **-11,9% em H1 e -1,8% em H4**. Homologação Double Stage:
pior dia -1,05% (limite -5%), nenhuma violação, mas **P(aprovar) = 0%**.

Ou seja: a infraestrutura de risco funciona, a **vantagem estatística não existe** na
configuração padrão — em H1 o prejuízo é literalmente só custo de transação. Relatório
completo, diagnóstico e próximos passos em [`docs/backtest-eurusd.md`](docs/backtest-eurusd.md).

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
* Para mesa proprietária, some a isto: `P(aprovar)` do Monte Carlo acima de ~60% e
  `P(violar)` abaixo de ~10% **com dados reais do ativo** — abaixo disso, o desafio é
  uma loteria paga.

## Estrutura

```
src/hantecbot/
  models.py indicators.py stream.py risk.py management.py prop.py journal.py report.py cli.py
  strategies/{base,trend_atr,mean_reversion}.py
  broker/{base,paper,mt5}.py
  backtest/{engine,metrics,optimizer,challenge}.py
  live/runner.py
config/default.yaml   config/fimathe/*.yaml   docs/regras-fimathe.md
tests/   Makefile   ci/github-actions-ci.yml
```

## Roadmap

- [ ] múltiplos símbolos em paralelo com limite de risco por portfólio
- [ ] filtro de calendário econômico (não operar 15 min antes de NFP/CPI)
- [ ] otimização bayesiana no lugar do grid
- [ ] notificações via Telegram

Licença MIT. Use por sua conta e risco.
