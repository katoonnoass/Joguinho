# Backtest XAU/USD 2024 → agosto/2026 (dados novos, fora da amostra antiga)

Teste pedido: **de 2024 até o momento**. Os dados vão de **2024-01-01 a 2026-07-31**
(última barra disponível no dump público; agosto/2026 ainda não foi publicado).

## Os dados

| | |
|---|---|
| série | XAU/USD M1, 900.976 candles após limpeza (13.092 barras de fim de semana descartadas) |
| período | 2024-01-01 → 2026-07-31 |
| origem | dump mensal do feed cTrader ([kk-at-5/xauusd-raw-data](https://github.com/kk-at-5/xauusd-raw-data)) — 0 duplicatas, 0 timestamps fora de ordem, 0 violações de OHLC |
| como refazer | `bash tools/fetch_xauusd_2024.sh` |

⚠ **Não é o feed da Hantec.** Preço de ouro entre brokers difere pouco, mas spread,
swap e horário do servidor diferem muito. Antes de operar, exporte o histórico do
**seu** terminal MT5 e repita este documento inteiro.

### Spread real medido (isto é novo e importante)

O mesmo repositório publica log de bid/ask do feed ao vivo (78.157 amostras com
mercado aberto, julho/2026):

| mediana | p90 | p99 | máximo |
|---:|---:|---:|---:|
| 8 points | 12 | 40 | 81 |

(1 point = US$ 0,01/onça.) Todos os testes abaixo usam **30 points** — cerca do
percentil 98. Ou seja: os resultados são **pessimistas de propósito**. Se a
vantagem só aparecesse com spread ideal, ela não existiria.

## 1. O candidato de 2017-2020 não sobreviveu

O documento anterior elegeu **XAU/USD H4 com `trend_atr`** (32 operações, PF 2,46,
4/4 janelas positivas) e o bloqueou por amostra pequena. Aplicando **os mesmos
parâmetros, sem reajuste**, aos dados de 2024-2026 — que ele nunca viu:

| timeframe | operações | retorno | PF | expectativa | DD |
|---|---:|---:|---:|---:|---:|
| **H4** (o candidato) | 124 | **−1,10%** | 0,96 | −0,030 R | 8,79% |
| H1 | 534 | +15,72% | 1,16 | +0,081 R | 7,95% |
| M15 | 83 | −5,66% | 0,76 | −0,136 R | 11,58% |

**O candidato virou pó.** É exatamente o desfecho que a trava de liberação existe
para evitar: se o dinheiro tivesse entrado com base naquelas 32 operações, o
resultado teria sido perda. O gate custou paciência; teria economizado o desafio.

## 2. Varredura walk-forward só com os dados novos

`hantecbot scan -c config/xauusd.yaml --data XAUUSD:data/XAUUSD_M1_2024.csv:M1:M15,H1,H4
--strategies trend_atr --folds 4 --stress` (saída completa em `runs/scan_2024.txt`):

| TF | trades OOS | retorno OOS | PF | DD | janelas + | t | p (bootstrap) | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **H1** | 115 | **+7,79%** | **1,43** | 2,88% | **4/4** | +1,89 | 0,011 | 0,190 |
| M15 | 449 | +0,23% | 1,00 | 6,78% | 2/4 | +0,06 | 0,461 | 0,004 |
| H4 | 26 | −2,84% | 0,57 | 3,75% | 1/4 | −1,46 | 0,980 | 0,000 |

Só 576 combinações foram testadas (uma estratégia, três timeframes), então o limiar
de significância caiu de 4,36 para **3,91** — testar menos hipóteses barateia a prova.
Mesmo assim: **t=+1,89 não é evidência.**

### Robustez do novo líder (H1)

```
custos ×1.0   466 trades | ret +20,30% | PF 1,25 | DD  7,78%
custos ×1.5   461 trades | ret +16,77% | PF 1,21 | DD  9,18%
custos ×2.0   115 trades | ret  −9,04% | PF 0,67 | DD 10,09%
→ sobrevive até ×1,5 (o limite exigido, no fio)

Estabilidade: 5/5 vizinhos de parâmetros positivos (100%), mediana +15,78%
```

Platô de parâmetros: bom. Custos: **frágil** — com spread 2× (60 points, acima do p99
medido) a estratégia inverte o sinal. Traduzindo: essa vantagem é feita de margem
pequena; conta com spread ruim a destrói.

### Veredito (`runs/gate_2024.json`)

```
  [ ] amostra out-of-sample          115 trades (mín. 200)
  [x] profit factor OOS              1.43
  [x] drawdown OOS                   2.88%
  [x] expectativa por trade          +0.188 R
  [x] consistência entre janelas     4/4 positivas
  [ ] significância corrigida        t=+1.89 (mín. 3.91 após 576 testes)
  [ ] bootstrap por blocos           p=0.0110 (máx. 0.00009)
  [ ] deflated sharpe                DSR=0.190 (mín. 0.95)
  [x] resiste a custos maiores       sobrevive até ×1.5
  [x] platô de parâmetros            100% dos vizinhos positivos
  [ ] dias em conta demo             não informado
🚫 BLOQUEADO
```

## 3. E a parte que continua garantida: não estourar a conta

Homologação Fimathe Double Stage sobre a mesma série (H1, saldo 100.000):

| | valor | limite oficial |
|---|---:|---:|
| pior dia | **−1,15%** | −5,00% |
| encerrado por | kill switch **interno** em −6,07% | piso da mesa: −10% |
| dias operados | 177 (16 lucrativos) | — |
| maior pausa | 13 dias | violação em 30 |
| consistência | 8,1% | — |
| **violações da mesa** | **zero** | — |

Resultado da fase: −4,61%, não homologado (P(aprovar) no Monte Carlo: 0,0%).
Sem vantagem, o robô perde devagar e para sozinho — nunca estoura. É metade da
frase "ganhar e não perder", e é a metade que a engenharia entrega.

## 4. Leitura honesta de tudo isso

1. **A hipótese do ouro em H4 morreu.** Foi testada em dados novos e reprovada. Não
   insista nela.
2. **Surgiu uma hipótese nova em H1** (4/4 janelas positivas, PF 1,43, DD 2,88%), com
   a mesma cara de "promissora mas não provada" que a anterior tinha. A diferença é
   que agora sabemos o que isso costuma valer: pouco, até passar em dados novos.
3. **O caminho é o mesmo, na ordem:** (a) validar a hipótese H1 em 2012-2023 — os
   dados existem no mesmo dump e são território virgem para ela; (b) se aguentar,
   60+ dias de demo na Hantec comparando spread e slippage reais; (c) só então
   desafio, com `safety_factor` baixo.
4. **Custo é o inimigo número um.** A H1 morre com spread 2×. Conta com spread e
   comissão ruins transforma a melhor hipótese disponível em perda garantida.

## Como reproduzir

```bash
bash tools/fetch_xauusd_2024.sh          # baixa e audita a série

hantecbot backtest -c config/xauusd.yaml --csv data/XAUUSD_M1_2024.csv \
    --source-tf M1 --resample H1

hantecbot scan -c config/xauusd.yaml \
    --data XAUUSD:data/XAUUSD_M1_2024.csv:M1:M15,H1,H4 \
    --strategies trend_atr --folds 4 --stress --gate runs/gate_2024.json

hantecbot challenge -c config/xauusd.yaml --csv data/XAUUSD_M1_2024.csv \
    --source-tf M1 --resample H1 --plano double_stage --balance 100000 --montecarlo
```
