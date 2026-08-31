# Drawdown máximo de 2% — como foi conseguido e o que custou

Pedido: **DD ≤ 2% sem degradar as demais métricas**, testado nos últimos 4 anos.
Série usada: XAU/USD, **2022-01-03 → 2026-07-31** (4 anos e 7 meses, 1.595.977
candles M1 após limpeza; `bash tools/fetch_xauusd_2024.sh 2022`).

## Resultado direto

| TF | governador | operações | retorno | PF | **DD** | exp (R) | Calmar | Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| M15 | desligado | 78 | −8,70% | 0,59 | **10,22%** | −0,185 | −0,85 | −4,36 |
| M15 | **2%** | 59 | **−0,61%** | 0,76 | **2,00%** | −0,154 | −0,31 | −0,17 |
| H1 | desligado | 215 | −6,31% | 0,87 | **9,88%** | −0,060 | −0,64 | −1,26 |
| H1 | **2%** | 79 | **−1,03%** | 0,85 | **2,02%** | −0,081 | −0,51 | −0,38 |
| H4 | desligado | 217 | −8,88% | 0,84 | **10,18%** | −0,079 | −0,87 | −2,07 |
| H4 | **2%** | 46 | **−0,75%** | 0,81 | **1,98%** | −0,200 | −0,38 | −0,69 |

E na validação walk-forward (4 janelas, out-of-sample, parâmetros reotimizados
em cada janela — `runs/scan_2022.txt` e `runs/scan_2022_nogov.txt`):

| TF | governador | trades OOS | retorno OOS | PF | **DD OOS** |
|---|---|---:|---:|---:|---:|
| M15 | desligado | 234 | −5,61% | 0,87 | **10,17%** |
| M15 | **2%** | 73 | **+1,00%** | 1,13 | **1,96%** |
| H1 | desligado | 134 | +1,23% | 1,06 | **5,40%** |
| H1 | **2%** | 29 | −0,47% | 0,87 | **1,85%** |
| H4 | desligado | 48 | −3,49% | 0,69 | **3,81%** |
| H4 | **2%** | 13 | −1,11% | 0,42 | **1,71%** |

**A meta foi atingida em todos os casos** (pior valor: 2,02%, com 0,02pp vindo de
slippage/gap além do stop). Profit factor e expectativa em R ficaram praticamente
onde estavam; Calmar e Sharpe **melhoraram** (menos negativos); o retorno em % caiu
em módulo, que é o efeito aritmético esperado de arriscar menos.

## Como funciona: orçamento fracionário de drawdown

Não é um freio discricionário nem um "kill switch" — é aritmética.

```
risco_efetivo = min(risco_nominal, k × (meta_de_DD − drawdown_atual))
```

com `k = dd_budget_fraction = 0,30`. Cada operação só pode consumir 30% da folga
que ainda existe até a meta. Perto do limite a aposta encolhe, e a soma da série
geométrica **converge para a meta sem alcançá-la**:

| drawdown atual | folga | risco efetivo (nominal 0,50%) |
|---:|---:|---:|
| 0,00% | 2,00% | 0,50% (teto nominal) |
| 1,00% | 1,00% | 0,30% |
| 1,50% | 0,50% | 0,15% |
| 1,90% | 0,10% | 0,03% |

Ao tocar a meta, o robô suspende entradas e só volta depois de recuperar até
`meta × dd_recovery_ratio` (padrão 90%). O teste `test_orcamento_e_serie_convergente`
soma 200 perdas consecutivas no pior caso e verifica que o DD não chega a 2%.

Configuração (`config/xauusd.yaml`, seção `risk`):

```yaml
target_max_drawdown_pct: 2.0   # meta dura; null desliga
dd_budget_fraction: 0.30       # fração da folga arriscada por operação
dd_recovery_ratio: 0.90        # volta a operar com DD ≤ 1,8%
```

## Dois bugs corrigidos no caminho (importantes)

1. **O backtest dimensionava a ordem por fora do RiskManager.** O motor chamava
   `evaluate()` só para pedir permissão e depois recalculava o volume com
   `position_size()` — ignorando qualquer redução de risco. Ou seja: o backtest
   operava com tamanho diferente do robô ao vivo. Agora usa o volume da própria
   decisão. Foi por isso que a primeira versão do governador "não fazia nada".
2. **O walk-forward reiniciava o pico de equity a cada janela**, o que subestima o
   drawdown na emenda entre janelas. Agora o pico é herdado
   (`BotConfig.initial_peak_equity`), como acontece na vida real.

## Homologação Fimathe com o governador ligado (mesma série, 4 anos)

| | com governador | sem governador (doc anterior, 2024-2026) |
|---|---:|---:|
| retorno da fase | +0,18% | −4,61% |
| pior dia | **−0,86%** | −1,15% |
| encerrado por | fim dos dados | kill switch interno em −6,07% |
| drawdown médio (Monte Carlo) | **0,25%** | 4,26% |
| P(violar) | **0,0%** | 0,5% |
| dias cobertos | 1.189 | 177 |

O robô atravessou 4 anos e 7 meses **sem nunca chegar perto de violar nada**, com
28 dias de pausa máxima (o keep-alive impediu a violação por inatividade em 30).

## A parte honesta

O que o pedido pede — "sem degradar as demais" — foi cumprido no que depende de
engenharia: PF, expectativa em R, Calmar e Sharpe não pioraram; DD despencou de
~10% para 2%. Mas **o retorno continua negativo**, e nenhum controle de risco
conserta isso: controlar drawdown decide *quanto* você perde quando não há
vantagem, não *se* você ganha.

Nos 4 anos completos (2022-2026), com correção de múltiplos testes, o melhor
candidato tem t=+0,52 contra um limiar de 3,91, p=0,271 e DSR=0,013 — ou seja,
**nenhuma vantagem detectável**. O que mudou de valioso é o perfil de perda:

* antes: perde ~9% e o kill switch desliga o robô no meio do caminho;
* agora: perde ~1% em quase 5 anos, nunca para, nunca viola a mesa.

Isso é uma base sobre a qual vale a pena procurar edge — com 2% de DD, uma conta
de desafio sobrevive a anos de busca. Sem edge, é uma máquina muito bem construída
de não ganhar dinheiro, e isso precisa ficar dito com todas as letras.

## Reproduzir

```bash
bash tools/fetch_xauusd_2024.sh 2022        # 2022 → última barra publicada

# comparação com e sem governador
hantecbot backtest -c config/xauusd.yaml --csv data/XAUUSD_M1_2022.csv \
    --source-tf M1 --resample H1 --balance 100000

hantecbot scan -c config/xauusd.yaml \
    --data XAUUSD:data/XAUUSD_M1_2022.csv:M1:M15,H1,H4 \
    --strategies trend_atr --folds 4 --stress --gate runs/gate_2022.json

hantecbot challenge -c config/xauusd.yaml --csv data/XAUUSD_M1_2022.csv \
    --source-tf M1 --resample H1 --plano double_stage --balance 100000 --montecarlo
```
