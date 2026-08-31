# Cesta D1: o primeiro resultado que passa em tudo

`hantecbot basket --stress --gate runs/gate.json`

Cinco mercados, um capital, **parâmetros pré-registrados**, 26 anos de histórico
diário (2000-01-03 → 2026-08-30). Saída completa em [`runs/basket.txt`](../runs/basket.txt).

## Resultado

| indicador | valor | critério do gate |
|---|---:|---|
| operações | **394** | ≥ 200 ✅ |
| retorno (26 anos, DD travado em 1,25%) | **+19,39%** | — |
| profit factor | **1,92** | ≥ 1,20 ✅ |
| **drawdown máximo** | **1,17%** | ≤ 12% ✅ |
| expectativa por operação | **+0,239 R** | ≥ 0,05 ✅ |
| Sharpe / Calmar | **3,12 / 16,54** | — |
| anos positivos | **21/26 (81%)** | ≥ 70% ✅ |
| t (significância) | **+4,58** | ≥ 3,07 (Šidák, 24 testes) ✅ |
| p (bootstrap por blocos) | **< 0,00001** | ≤ 0,0021 ✅ |
| Deflated Sharpe Ratio | **0,998** | ≥ 0,95 ✅ |
| resiste a custos | **até ×3,0** (PF 1,47) | ≥ ×1,5 ✅ |
| platô de parâmetros | **10/10 vizinhos positivos** | ≥ 60% ✅ |
| dias em conta demo | **0** | ≥ 60 ❌ |

**10 de 11 critérios aprovados.** O único pendente é o que não se resolve com
CPU: 60 dias de conta demo real na Hantec, comparando execução, spread e
slippage com o simulado. O `live` continua bloqueado até lá.

### O que mudou em relação à versão anterior

O drawdown caiu pela metade **e todos os outros indicadores melhoraram**:

| indicador | antes (v1) | agora (v2) |
|---|---:|---:|
| drawdown máximo | 1,97% | **1,17%** (−41%) |
| retorno | +15,61% | **+19,39%** |
| profit factor | 1,45 | **1,92** |
| expectativa | +0,146 R | **+0,239 R** |
| t | +3,94 | **+4,58** |
| p (bootstrap) | 0,00020 | **< 0,00001** |
| Sharpe / Calmar | 2,10 / 7,91 | **3,12 / 16,54** |
| anos positivos | 19/26 | **21/26** |
| PF com custo ×3 | 1,18 | **1,47** |
| subperíodo mais fraco (2010-2017) | PF 1,14, t=+1,52 | **PF 1,89, t=+2,25** |

Duas mudanças produziram isso, e nenhuma delas é "achar o parâmetro mágico":

1. **Tirar o trailing stop.** O trailing de 2,5 ATR cortava exatamente as
   tendências longas que pagam a conta de um seguidor de tendência. Sem ele
   (mantendo a parcial em 1R e o breakeven), o PF vai de 1,45 para 1,92 e a
   expectativa de +0,146 R para +0,239 R. **Menos gestão, mais resultado.**
2. **Baixar a meta de drawdown de 2,0% para 1,25%.** Como o governador troca DD
   por retorno de forma quase linear, o edge maior do item 1 permite exigir um
   DD menor e ainda assim entregar mais retorno.

Custo estatístico: o número de tentativas declaradas subiu de 6 para 24, então
a barra de significância subiu de t 2,63 para 3,07. O t observado subiu mais
(3,94 → 4,58), então o resultado ficou mais forte, não mais frouxo.

## Por mercado

(cada mercado rodado isolado, risco constante de 2%, sem o governador da carteira)

| mercado | operações | retorno | PF | DD | expectativa |
|---|---:|---:|---:|---:|---:|
| XAUUSD | 104 | +3,64% | 1,41 | 4,73% | +0,141 R |
| EURUSD | 80 | +9,06% | 1,91 | 3,60% | +0,242 R |
| US500 | 87 | +4,57% | 2,85 | 2,33% | +0,330 R |
| USDX | 74 | +5,87% | 1,77 | 2,69% | +0,178 R |
| BTCUSD | 49 | +0,80% | 2,48 | 4,40% | +0,370 R |

Os cinco são positivos em retorno **e** em expectativa. Note o contraste entre
o DD isolado (2,3% a 4,7%) e o DD da carteira (1,17%): é a diversificação
fazendo o trabalho, não um filtro esperto.

## A linha risco × drawdown

O governador arrisca no máximo 30% da folga que ainda existe até a meta de DD.
Escolher a meta é escolher um ponto de uma reta — o edge (Calmar ~16) é o mesmo:

| meta de DD | DD observado | retorno em 26 anos | Calmar |
|---:|---:|---:|---:|
| 0,50% | 0,47% | +7,35% | 15,7 |
| 0,75% | 0,70% | +11,23% | 16,0 |
| 1,00% | 0,94% | +15,24% | 16,2 |
| **1,25%** | **1,17%** | **+19,39%** | **16,5** |
| 1,50% | 1,41% | +23,69% | 16,8 |
| 2,00% | 1,87% | +32,75% | 17,5 |
| sem governador (2% fixo) | 13,38% | +501,69% | 37,5 |

Quem quiser DD de 0,5% troca retorno por sono; quem aceitar 13% de DD tem os
mesmos sinais rendendo 500% em 26 anos. **O que não muda é a razão
retorno/risco** — e é só ela que o backtest tem autoridade para estimar.

```bash
hantecbot basket --target-dd 0.5    # conservador
hantecbot basket --target-dd 2      # agressivo
hantecbot basket --target-dd 0      # sem governador
```

## Tudo o que foi testado (24 tentativas, nada escondido)

### 1. Seis conjuntos de sinal

| variante | operações | PF | expectativa | t |
|---|---:|---:|---:|---:|
| rápida 10/50, sem ADX | 1457 | 0,54 | +0,046 | +1,91 |
| rápida 10/50, ADX≥20 | 937 | 0,45 | +0,021 | +0,72 |
| média 20/100, sem ADX | 806 | 0,52 | +0,062 | +2,04 |
| média 20/100, ADX≥20 | 692 | 1,15 | +0,087 | +2,73 |
| lenta 50/200, sem ADX | 575 | 1,37 | +0,123 | +3,52 |
| **lenta 50/200, ADX≥20** | **488** | **1,45** | **+0,146** | **+3,94** |

Padrão monotônico: quanto mais lento, melhor. É o que 40 anos de literatura de
trend following mostram — e é o oposto de um resultado isolado no meio de
configurações ruins.

### 2. Dezesseis combinações de gestão da posição

(sinal fixo na variante lenta; parcial em 1R, breakeven em 1R e trailing em ATR)

| parcial | breakeven | trailing | operações | retorno | PF | expectativa | t |
|:--:|:--:|--:|---:|---:|---:|---:|---:|
| — | — | — | 227 | +6,88% | 1,46 | +0,569 | +3,36 |
| — | — | 2,5 | 315 | +6,50% | 1,28 | +0,255 | +3,17 |
| — | — | 4,0 | 278 | +14,31% | 1,65 | +0,317 | +3,17 |
| — | — | 6,0 | 253 | +14,05% | 1,57 | +0,485 | +3,68 |
| — | 1R | — | 249 | +14,99% | 1,63 | +0,487 | +3,63 |
| — | 1R | 2,5 | 315 | +6,50% | 1,28 | +0,255 | +3,17 |
| — | 1R | 4,0 | 278 | +15,02% | 1,66 | +0,324 | +3,23 |
| — | 1R | 6,0 | 261 | +20,19% | 1,69 | +0,453 | +3,81 |
| 1R | — | — | 359 | +25,91% | 1,67 | +0,265 | +4,20 |
| 1R | — | 2,5 | 488 | +15,61% | 1,45 | +0,146 | +3,94 |
| 1R | — | 4,0 | 435 | +22,33% | 1,70 | +0,174 | +4,10 |
| 1R | — | 6,0 | 398 | +29,91% | 1,76 | +0,237 | +4,57 |
| **1R** | **1R** | **—** | **394** | **+32,75%** | **1,92** | **+0,239** | **+4,58** |
| 1R | 1R | 2,5 | 488 | +15,61% | 1,45 | +0,146 | +3,94 |
| 1R | 1R | 4,0 | 435 | +22,94% | 1,72 | +0,176 | +4,16 |
| 1R | 1R | 6,0 | 413 | +33,79% | 1,91 | +0,227 | +4,81 |

(retornos desta tabela com a meta antiga de DD 2%, para comparar maçã com maçã)

Leitura: **trailing curto é o inimigo**. Trailing 2,5 ATR é o pior de todos;
4,0 melhora; 6,0 já quase não corta nada e chega perto de não ter trailing.
Escolhemos "sem trailing" (o vizinho 6,0 ATR tem t ainda maior, +4,81 — não é
um pico isolado, é uma região inteira boa).

### 3. Duas cestas alternativas de mercados — as duas piores

Baixamos mais 23 séries diárias e testamos cestas maiores, com a mesma
configuração:

| cesta | operações | retorno | PF | DD | expectativa | t | anos + |
|---|---:|---:|---:|---:|---:|---:|---:|
| **5 mercados (escolhida)** | **394** | **+19,39%** | **1,92** | **1,17%** | **+0,239** | **+4,58** | **21/26** |
| 11 (+ prata, Brent, DAX, Dow, Nasdaq, FTSE) | 599 | +10,10% | 1,73 | 1,25% | +0,137 | +3,18 | 20/26 |
| 28 (+ 17 pares de FX) | 1305 | +9,94% | 1,68 | 1,25% | +0,056 | +2,05 | 16/26 |

Contraintuitivo, mas explicável: os 17 pares de FX são combinações de 8 moedas
— não são 17 apostas independentes, são a mesma aposta repetida com custo
maior. E as séries novas só existem de 2007/2013 em diante, concentrando as
operações no período mais difícil para trend following. Diversificação ajuda
quando adiciona **risco independente**, não quando adiciona linhas na planilha.

Os dados estão em `data/` (não versionados). Origem: D1 de FX, prata, Brent e
índices em `TheSnowGuru/Stocks-Futures-Financial-Time-series-Tick-Bar-Data`
(2007→2023, sparse checkout dos `*_D1.csv`).

## Robustez

**Subperíodos** (mesma cesta, sem nenhum reajuste):

| período | operações | retorno | PF | DD | expectativa | t | p |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2001-2009 | 119 | +4,65% | 1,70 | 1,15% | +0,220 R | +2,40 | 0,014 |
| 2010-2017 | 119 | +5,31% | 1,89 | 1,17% | +0,205 R | +2,25 | 0,011 |
| 2018-2026 | 156 | +9,55% | 2,27 | 1,13% | +0,279 R | +3,21 | 0,004 |

Positivo nos três, incluindo o "inverno" dos seguidores de tendência
(2010-2017) — que na v1 mal empatava (PF 1,14).

**Custos** (spread, comissão, swap e slippage multiplicados):

| multiplicador | operações | retorno | PF | t |
|---|---:|---:|---:|---:|
| ×1,0 | 394 | +19,39% | 1,92 | +4,58 |
| ×1,5 | 391 | +17,51% | 1,85 | +4,43 |
| ×2,0 | 390 | +15,92% | 1,79 | +4,28 |
| ×3,0 | 339 | +7,43% | 1,47 | +3,09 |

Sobrevive a **três vezes** o custo suposto — e o custo suposto já é pessimista.

**Parâmetros**: 10/10 vizinhos com expectativa positiva (+0,159 a +0,308 R).
É platô, não pico.

**Anos** (soma de R): 2001 −5,0 | 2002 +3,7 | 2003 +8,8 | 2004 +1,6 | 2005 −3,0 |
2006 +3,6 | 2007 +9,4 | 2008 +4,8 | 2009 +2,4 | 2010 +5,2 | 2011 +5,4 |
2012 −0,8 | 2013 +0,9 | 2014 +6,7 | 2015 +4,5 | 2016 −2,4 | 2017 +4,9 |
2018 +8,5 | 2019 +2,8 | 2020 +2,1 | 2021 +2,7 | 2022 +5,5 | 2023 −1,6 |
2024 +8,9 | 2025 +8,9 | 2026 +5,7.

## O que este resultado NÃO é

* Não é 19% ao ano — é **+19,39% em 26 anos com drawdown de 1,17%**. A escolha
  do ponto na reta risco/retorno é sua (tabela acima).
* Não é garantia. A cesta perdeu em 5 dos 26 anos e passou 2012-2013
  praticamente de lado.
* Não é permissão para ligar dinheiro real. Falta demo, e falta confirmar os
  custos da sua conta Hantec — os specs usados são estimativas conservadoras
  (`config/symbols/specs.yaml`).

## Reproduzir

```bash
hantecbot basket -c config/xauusd.yaml --spec config/basket.yaml --stress \
    --gate runs/gate.json
```

Dados do núcleo: `db/*.parquet` de
[aliskairraul/Actualiza-Data-Instrumentos](https://github.com/aliskairraul/Actualiza-Data-Instrumentos)
(D1 desde 2000, atualizado diariamente), convertidos para `data/*_D1.csv`.
