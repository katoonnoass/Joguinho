# "Quero ganhar e não perder" — o que dá e o que não dá para garantir

Este documento existe porque essa frase é a mais honesta que um trader pode dizer, e
merece uma resposta igualmente honesta.

## A separação que muda tudo

| | dá para garantir? | como |
|---|---|---|
| **Não perder o controle** (perda diária, drawdown, violar a mesa) | **Sim, por engenharia** | limites duros no código, testados |
| **Não perder dinheiro em desafio sem vantagem** | **Sim** | trava de liberação (`hantecbot gate`) |
| **Não perder por erro operacional** (spread, gap, inatividade, scalping) | **Sim, quase todo** | filtros e keep-alive já implementados |
| **Ganhar** | **Não** | depende de existir vantagem estatística no mercado |

Nenhum robô ganha por decreto. O que existe é vantagem pequena, repetida muitas vezes,
sobrevivendo aos custos. Se ela não existe, **a decisão que mais economiza dinheiro é
não operar** — e é isso que o sistema agora impõe.

## A trava de liberação

`hantecbot live` **recusa** operar sem um veredito aprovado em `runs/gate.json`:

```
🚫 Operação ao vivo bloqueada: não há veredito de liberação aprovado.
Gere evidência primeiro:
  hantecbot scan --data SIMBOLO:arquivo.csv:TF --gate runs/gate.json
```

Critérios (todos obrigatórios, em `GateCriteria`):

| critério | mínimo | por quê |
|---|---|---|
| operações out-of-sample | 200 | 30 trades bonitos são sorte |
| profit factor OOS | 1,20 | margem acima dos custos |
| drawdown OOS | ≤ 12% | precisa caber no limite da mesa |
| expectativa | ≥ +0,05 R | vantagem por operação, não por acaso |
| janelas positivas | ≥ 70% | consistência, não um fold salvador |
| **t corrigido por múltiplos testes** | Šidák | ver abaixo |
| dias em conta demo | ≥ 60 | comportamento real ≠ simulado |
| P(aprovar) na mesa | ≥ 50% | específico para desafio |

### O critério que quase ninguém aplica

Se você testa **3.456 combinações** e escolhe a melhor, ela parece ótima **mesmo que
todas sejam ruído** — é o problema de múltiplas comparações. Por isso o scan conta
quantas combinações foram testadas e sobe a barra de significância:

```
Combinações testadas no total: 3456
t crítico com correção de Šidák (alpha=0,05): 4,32
Melhor t observado: +1,02 → NÃO É EVIDÊNCIA: dentro do que a sorte explica
```

## Resultado da varredura (dados reais)

3 ativos × 3 timeframes × 2 estratégias, walk-forward de 4 janelas:

| ativo | TF | estratégia | trades OOS | retorno OOS | PF | DD | janelas + | t |
|---|---|---|---:|---:|---:|---:|---:|---:|
| **XAUUSD** | **H4** | trend_atr | 32 | **+5,74%** | **2,46** | 1,27% | **4/4** | **+2,23** |
| EURUSD | H1 | mean_reversion | 8 | +1,46% | 2,83 | 1,23% | 2/4 | +1,02 |
| EURUSD | H4 | trend_atr | 175 | +4,05% | 1,13 | 5,96% | 2/4 | +0,82 |
| USDCHF | H4 | trend_atr | 130 | +0,71% | 1,04 | 9,47% | 3/4 | +0,18 |
| XAUUSD | H1 | trend_atr | 134 | +1,43% | 1,06 | 5,64% | 2/4 | +0,31 |
| EURUSD | H1 | trend_atr | 531 | -6,55% | 0,94 | 9,98% | 2/4 | -0,63 |
| XAUUSD | M15 | trend_atr | 422 | -16,34% | 0,82 | 17,39% | 1/4 | -1,82 |
| USDCHF | H1 | trend_atr | 370 | -22,80% | 0,70 | 25,16% | 0/4 | -2,97 |

**Ouro em H4 é o único candidato interessante**: positivo nas 4 janelas, PF 2,46,
drawdown de 1,27%. E mesmo assim está **reprovado**: 32 operações é amostra pequena
e t=2,23 não vence o limiar corrigido de 4,17.

Note também o padrão: **quanto menor o timeframe, pior o resultado.** M15 e H1 pagam
spread demais. Isso não é opinião, é a conta aparecendo em três ativos diferentes.

## O caminho que realmente aumenta a chance de ganhar

1. **Mais dados de ouro.** A série cobre só 2017-2020. Com 10+ anos de XAUUSD H4, as
   32 operações viram ~150 e o t passa a ser informativo. Se a vantagem for real, ela
   sobrevive; se não, você economizou o desafio.
2. **Reduzir custo por operação** — conta com spread menor pesa mais que qualquer
   ajuste de indicador. Em H1 no EUR/USD, o prejuízo era 100% custo.
3. **Menos combinações testadas.** Contraintuitivo, mas testar menos hipóteses (e
   escolhidas por razão econômica, não por grid) baixa o limiar de significância.
4. **60+ dias de demo** antes de qualquer desafio pago, comparando execução real com o
   simulado (slippage, spread, horários).
5. **Só então** pagar o desafio, com `safety_factor` baixo: o objetivo é passar, não
   bater a meta rápido.

## Enquanto isso, o que já está garantido

Nos 8 anos de EUR/USD testados, com regras da Fimathe aplicadas:
pior dia **-1,05%** contra limite de -5%, freio interno agindo em -6,15% contra piso de
-10%, **zero violações** em 265 dias operados. O robô perde dinheiro do jeito lento e
controlado — nunca do jeito que estoura a conta.

É pouco? É. Mas é a única metade da frase "ganhar e não perder" que alguém pode
honestamente te entregar.
