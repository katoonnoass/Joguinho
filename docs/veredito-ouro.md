# Veredito do ouro: 10 anos, 3 estratégias, nenhuma vantagem

Este documento fecha a linha de pesquisa em XAU/USD. Ele registra um resultado
**negativo** — e resultado negativo, escrito com números, vale mais que um
backtest bonito, porque impede que o mesmo dinheiro seja perdido duas vezes.

Série: **2016-01-04 → 2026-07-31**, 3.677.939 candles M1 (dump cTrader, 0
duplicatas, 0 timestamps fora de ordem, 0 violações de OHLC).
Custos: spread 30 points (≈ p98 do spread real medido), comissão US$ 5/lote,
slippage 3 points.

## O que foi testado

| estratégia | ideia | resultado |
|---|---|---|
| `trend_atr` | rompimento Donchian com filtro de EMA + ADX | PF 1,12 no melhor caso, sem significância |
| `mean_reversion` | banda + RSI em mercado lateral | quase não opera; inconclusiva |
| `session_breakout` | **nova**: rompimento da faixa da madrugada na abertura de Londres | **rejeitada** (PF 0,68-0,85 em todos os cortes) |

A `session_breakout` foi criada nesta rodada exatamente para testar uma hipótese
*econômica*, não um ajuste de indicador: "o ouro sai da faixa asiática quando
Londres abre". Ela mede a faixa entre `range_start_hour` e `range_end_hour`,
exige que a faixa tenha tamanho normal em ATR, entra no primeiro fechamento além
dela, faz **uma operação por dia** e sai no fim da sessão. A implementação está
coberta por 10 testes. O mercado respondeu: **não**.

## Descoberta (2016-2021) — risco constante

| TF | estratégia | trades OOS | ret OOS | PF | janelas + | t | p |
|---|---|---:|---:|---:|---:|---:|---:|
| H1 | trend_atr | 251 | −0,86% | 0,99 | 2/4 | +0,02 | 0,490 |
| M15 | trend_atr | 121 | −7,47% | 0,72 | 0/4 | −1,39 | 0,868 |
| H1 | session_breakout | 157 | −9,15% | 0,74 | 0/4 | −1,71 | 0,942 |
| M15 | session_breakout | 138 | −10,21% | 0,68 | 0/4 | −2,10 | 0,978 |

## Período completo (2016-2026, 5 janelas walk-forward)

| TF | estratégia | trades OOS | ret OOS | PF | DD | janelas + | t | p | DSR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **H1** | **trend_atr** | 397 | **+8,62%** | 1,12 | 8,37% | 3/5 | +1,01 | 0,180 | 0,033 |
| M15 | trend_atr | 229 | −3,85% | 0,92 | 10,17% | 0/5 | −0,78 | 0,744 | 0,000 |
| M15 | session_breakout | 259 | −8,99% | 0,85 | 10,17% | 0/5 | −1,15 | 0,907 | 0,000 |
| H1 | session_breakout | 127 | −7,91% | 0,75 | 10,00% | 0/5 | −1,45 | 0,932 | 0,000 |

1.920 combinações testadas → t crítico 4,19. O melhor tem **t=+1,01**. Não é edge.

E o teste que mata a dúvida: pegando os parâmetros vencedores da descoberta
(`fast 34, slow 55, breakout 40, atr_stop 2.5, reward 3.0`) e rodando-os fixos:

| corte | operações | retorno | PF | expectativa |
|---|---:|---:|---:|---:|
| 2016-2026 completo | 360 | **−7,33%** | 0,91 | −0,037 R |
| holdout 2022-2026 | 180 | **−7,43%** | 0,83 | −0,079 R |
| vizinhos de parâmetros | — | 0/5 positivos | — | — |

**Conclusão: não há vantagem detectável em ouro com as estratégias atuais.**

## Correção metodológica desta rodada (importa mais que os números)

A varredura vinha rodando com o **governador de drawdown ligado**, e isso
falseava a pesquisa: ao tocar a meta de 2% o robô suspende entradas, ou seja, a
amostra é **censurada exatamente nos períodos ruins**. O resultado parecia melhor
do que era (o mesmo conjunto de parâmetros "sobrevivia a custo ×2" com governador
e virava −7,3% sem ele).

Agora `hantecbot scan` desliga o governador por padrão e avisa:

```
• governador de DD (2.0%) DESLIGADO na pesquisa: risco constante mede o edge
  sem censurar a amostra (use --with-governor para incluí-lo)
```

Separação correta: **pesquisa** mede o edge com risco constante; **operação**
aplica o governador para limitar o estrago. Misturar as duas coisas é uma forma
elegante de mentir para si mesmo.

## O que continua valendo

* O governador de 2% funciona e é aritmético (ver [`drawdown-2pct.md`](drawdown-2pct.md)).
  No holdout 2022-2026 ele transformou −7,43% com DD 10,16% em −1,14% com DD 1,99%.
* A trava de liberação continua bloqueando tudo — corretamente.
* O framework agora testa uma hipótese nova ponta a ponta (dados → estratégia →
  walk-forward → estresse → veredito) em cerca de 5 minutos. Esse é o ativo real
  construído aqui: **velocidade de rejeitar ideias ruins**.

## Para onde ir (em ordem de retorno esperado)

1. **Outro mercado, não outro indicador.** Ouro foi esgotado. Índices (US500,
   NAS100) e cruzamentos de FX têm microestrutura diferente; o mesmo pipeline
   roda neles trocando um YAML.
2. **Outra fonte de retorno.** Tendência e reversão são as duas ideias mais
   competidas do mercado. Sazonalidade de rollover, carry (swap positivo) e
   comportamento em torno de dados macro são menos disputados.
3. **Nunca pagar desafio antes do gate.** Cada rodada destas custa ~5 minutos de
   CPU; um desafio reprovado custa dinheiro de verdade.
