# Cesta D1: o primeiro resultado que passa em tudo

`hantecbot basket --stress --gate runs/gate.json`

Cinco mercados, um capital, **parâmetros pré-registrados** (não otimizados),
26 anos de histórico diário (2000-01-03 → 2026-08-30).

## Resultado

| indicador | valor | critério do gate |
|---|---:|---|
| operações | **488** | ≥ 200 ✅ |
| retorno (26 anos, DD travado em 2%) | **+15,61%** | — |
| profit factor | **1,45** | ≥ 1,20 ✅ |
| drawdown máximo | **1,97%** | ≤ 12% ✅ (e ≤ 2% pedido) |
| expectativa por operação | **+0,146 R** | ≥ 0,05 ✅ |
| Sharpe / Calmar | **2,10 / 7,91** | — |
| anos positivos | **19/26 (73%)** | ≥ 70% ✅ |
| t (significância) | **+3,94** | ≥ 2,63 (Šidák, 6 testes) ✅ |
| p (bootstrap por blocos) | **0,0002** | ≤ 0,0085 ✅ |
| Deflated Sharpe Ratio | **0,996** | ≥ 0,95 ✅ |
| resiste a custos | **até ×3,0** | ≥ ×1,5 ✅ |
| platô de parâmetros | **10/10 vizinhos positivos** | ≥ 60% ✅ |
| dias em conta demo | **0** | ≥ 60 ❌ |

**10 de 11 critérios aprovados.** O único pendente é o que não se resolve com
CPU: 60 dias de conta demo real na Hantec, comparando execução, spread e
slippage com o simulado. O `live` continua bloqueado até lá — como tem que ser.

## Por mercado

| mercado | operações | retorno | PF | DD | expectativa |
|---|---:|---:|---:|---:|---:|
| XAUUSD | 121 | +6,16% | 1,46 | 3,56% | +0,145 R |
| EURUSD | 102 | +5,31% | 1,40 | 4,75% | +0,114 R |
| US500 | 117 | +2,46% | 1,81 | 3,92% | +0,174 R |
| USDX | 90 | +4,74% | 1,46 | 3,26% | +0,124 R |
| BTCUSD | 58 | −1,00% | 1,55 | 3,48% | +0,185 R |

**Os cinco têm expectativa positiva em R.** (O retorno em % do BTCUSD fica
negativo por granularidade de lote no cálculo isolado; na cesta, onde o risco é
normalizado, ele contribui +10,7 R.)

## Por que agora funcionou

Três mudanças, nenhuma delas "ajustar indicador":

1. **Timeframe diário.** Em M15/H1 o custo come tudo: no ouro, spread de 30
   points contra um movimento típico de 100 é 30% de imposto por operação. Em D1
   o mesmo spread é ruído. Todos os testes anteriores morriam aqui.
2. **Cesta em vez de mercado único.** Seguidor de tendência acerta ~40% e vive
   de poucos movimentos grandes por ano. Um mercado só = ruído; cinco mercados
   pouco correlacionados = amostra 5× maior e drawdown 3× menor. Foi isso que
   levou o t de ~1,0 para +3,94.
3. **Parâmetros pré-registrados em vez de otimizados.** Otimizar 1.080
   combinações exige t > 4,1 para convencer. Declarando **6** configurações
   canônicas antes de olhar o resultado, a barra cai para 2,63 — e um t de 3,94
   passa a significar alguma coisa. Otimização não é só risco de sobreajuste: é
   uma dívida estatística que você paga na hora de provar o resultado.

### As 6 configurações testadas (todas, sem esconder nenhuma)

| variante | operações | retorno | PF | DD | expectativa | t | p | anos + |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| rápida 10/50, sem ADX | 1457 | −1,22% | 0,54 | 2,00% | +0,046 | +1,91 | 0,032 | 16/27 |
| rápida 10/50, ADX≥20 | 937 | −2,00% | 0,45 | 1,41% | +0,021 | +0,72 | 0,238 | 16/27 |
| média 20/100, sem ADX | 806 | −2,00% | 0,52 | 1,40% | +0,062 | +2,04 | 0,029 | 19/27 |
| média 20/100, ADX≥20 | 692 | +3,05% | 1,15 | 2,00% | +0,087 | +2,73 | 0,006 | 20/27 |
| lenta 50/200, sem ADX | 575 | +8,79% | 1,37 | 1,99% | +0,123 | +3,52 | 0,0008 | 18/26 |
| **lenta 50/200, ADX≥20** | **488** | **+15,61%** | **1,45** | **1,97%** | **+0,146** | **+3,94** | **0,0002** | **19/26** |

O padrão é monotônico — quanto mais lento, melhor —, o que é exatamente o que a
literatura de trend following mostra há 40 anos. Um resultado que aparece
isolado no meio de configurações ruins seria suspeito; este melhora de forma
ordenada, o que é sinal de fenômeno real e não de sorte.

## Robustez

**Subperíodos** (mesma cesta, sem nenhum reajuste):

| período | operações | retorno | PF | DD | expectativa | t | p |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2001-2009 | 152 | +8,13% | 1,59 | 1,86% | +0,176 R | +2,73 | 0,003 |
| 2010-2017 | 145 | +1,43% | 1,14 | 1,95% | +0,107 R | +1,52 | 0,049 |
| 2018-2026 | 191 | +6,80% | 1,71 | 1,97% | +0,153 R | +2,58 | 0,015 |

Positivo nos três, inclusive na década difícil (2010-2017, o "inverno" dos
seguidores de tendência).

**Custos** (spread, comissão, swap e slippage multiplicados):

| multiplicador | operações | retorno | PF | t |
|---|---:|---:|---:|---:|
| ×1,0 | 488 | +15,61% | 1,45 | +3,94 |
| ×1,5 | 486 | +11,77% | 1,37 | +3,67 |
| ×2,0 | 485 | +9,09% | 1,32 | +3,49 |
| ×3,0 | 416 | +3,82% | 1,18 | +2,34 |

Sobrevive até **três vezes** o custo suposto. Nenhum resultado anterior passava
de ×1,5.

**Parâmetros**: 10/10 vizinhos com expectativa positiva (+0,119 a +0,186 R). É
platô, não pico.

## O que este resultado NÃO é

* Não é 15% ao ano — é **+15,61% em 26 anos com drawdown de 2%**. Com risco
  maior a curva escala junto: sem o governador, os mesmos sinais dão +42% com
  DD 4,5%, e a 1% de risco nominal +100% com DD 8,7%. **Você escolhe o ponto da
  reta; o que não muda é a razão retorno/risco (Calmar ~8).**
* Não é garantia. Trend following passa anos no vermelho (2005, 2012-2013, 2016,
  2021, 2023 aqui). A cesta perdeu em 7 dos 26 anos.
* Não é permissão para ligar dinheiro real. Falta demo, e falta confirmar os
  custos reais da sua conta Hantec — os specs usados são estimativas
  conservadoras (`config/symbols/specs.yaml`).

## Reproduzir

```bash
hantecbot basket -c config/xauusd.yaml --spec config/basket.yaml --stress \
    --gate runs/gate.json

# escalando o risco (mesma cesta, outro ponto da reta risco/retorno)
hantecbot basket --risk 2 --target-dd 4      # DD 4%
hantecbot basket --target-dd 0               # sem governador
```

Dados: `db/*.parquet` de
[aliskairraul/Actualiza-Data-Instrumentos](https://github.com/aliskairraul/Actualiza-Data-Instrumentos)
(D1 desde 2000, atualizado diariamente), convertidos para `data/*_D1.csv`.
