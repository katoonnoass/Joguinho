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
| **p do bootstrap por blocos** | ≤ alpha corrigido | sem supor normalidade |
| **Deflated Sharpe Ratio** | ≥ 0,95 | desconta o "melhor de N" |
| **resiste a custos maiores** | PF ≥ 1,05 com custo ×1,5 | corretora pior que o suposto |
| **platô de parâmetros** | ≥ 60% dos vizinhos positivos | pico isolado é sobreajuste |
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

### Os outros quatro filtros de autoengano

O t corrigido supõe normalidade e mede só a média. Os outros quatro atacam ângulos
diferentes do mesmo problema:

| filtro | pergunta que responde | onde |
|---|---|---|
| **bootstrap por blocos** | reembaralhando as operações em blocos (preservando sequências de perdas), com que frequência a média fica ≤ 0? | `validation.bootstrap_mean` |
| **Deflated Sharpe Ratio** | descontando o Sharpe que o *melhor de N tentativas* teria só por sorte, sobra alguma coisa? | `validation.deflated_sharpe` |
| **estresse de custos** | e se o spread real for 1,5× ou 2× o suposto? | `validation.cost_stress` |
| **platô de parâmetros** | os vizinhos do conjunto escolhido também ganham, ou é um pico isolado? | `validation.neighborhood_stability` |

Os dois últimos rodam com `hantecbot scan --stress`.

## Resultado da varredura (dados reais)

3 ativos × 3 timeframes × 2 estratégias, walk-forward de 4 janelas
(saída completa em `runs/scan.txt`, reproduzível com `make scan`):

| ativo | TF | estratégia | trades OOS | retorno OOS | PF | DD | janelas + | t | p (bootstrap) | DSR |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **XAUUSD** | **H4** | trend_atr | 32 | **+5,74%** | **2,46** | 1,27% | **4/4** | **+2,23** | 0,0015 | 0,307 |
| XAUUSD | H1 | trend_atr | 134 | +1,43% | 1,06 | 5,64% | 2/4 | +0,31 | 0,366 | 0,007 |
| USDCHF | H4 | trend_atr | 130 | +0,71% | 1,04 | 9,47% | 3/4 | +0,18 | 0,428 | 0,005 |
| EURUSD | H1 | trend_atr | 400 | −4,79% | 0,94 | 13,36% | 1/4 | −0,52 | 0,685 | 0,001 |
| EURUSD | H4 | trend_atr | 123 | −4,08% | 0,84 | 9,44% | 1/4 | −0,91 | 0,752 | 0,000 |
| XAUUSD | M15 | trend_atr | 422 | −16,34% | 0,82 | 17,39% | 1/4 | −1,82 | 0,950 | 0,000 |
| USDCHF | H1 | trend_atr | 370 | −22,80% | 0,70 | 25,16% | 0/4 | −2,97 | 0,999 | 0,000 |

(`mean_reversion` fez de 0 a 2 operações por série: com os filtros atuais ela é
inoperante e seus números não são interpretáveis.)

### Carteira das séries positivas

As três séries de expectativa positiva compartilhando o mesmo capital, com risco
normalizado em 0,50% por operação:

```
  XAUUSD H4 trend_atr    32 trades | soma +11,31 R
  XAUUSD H1 trend_atr   134 trades | soma  +3,57 R
  USDCHF H4 trend_atr   130 trades | soma  +1,88 R

  Operações: 296 | Retorno: +8,38% | PF 1,14 | DD 5,66% | +0,057 R | t=+1,03
```

Diversificar **não cria** vantagem — mas transforma 32 operações em 296 e derruba o
drawdown. É o único almoço quase grátis do mercado, e mesmo ele não basta: t=+1,03.

### O que sobreviveu ao estresse (novidade importante)

O melhor candidato foi submetido aos dois testes de robustez:

```
  custos ×1.0   158 trades | ret +8,02% | PF 1,27 | DD 6,03%
  custos ×1.5   157 trades | ret +6,77% | PF 1,23 | DD 6,29%
  custos ×2.0   157 trades | ret +4,59% | PF 1,17 | DD 6,83%
  → sobrevive até ×2,0

  Estabilidade: 6/6 vizinhos de parâmetros positivos (100%), mediana +6,86%
```

Isso é um sinal **bom** e novo: o ouro em H4 não depende de spread otimista nem de um
ajuste fino de parâmetros. Ele reprova apenas onde mais importa — **amostra**
(32 operações), p do bootstrap (0,0015 contra 0,00001 exigido após 4.032 testes) e
DSR (0,307 contra 0,95).

**Ouro em H4 é o único candidato interessante**: positivo nas 4 janelas, PF 2,46,
drawdown de 1,27%. E mesmo assim está **reprovado**: 32 operações é amostra pequena
e t=2,23 não vence o limiar corrigido de 4,36.

Note também o padrão: **quanto menor o timeframe, pior o resultado.** M15 e H1 pagam
spread demais. Isso não é opinião, é a conta aparecendo em três ativos diferentes.

## O caminho que realmente aumenta a chance de ganhar

1. **Mais dados de ouro.** A série cobre só 2017-2020. Com 10+ anos de XAUUSD H4, as
   32 operações viram ~150 e o t passa a ser informativo. Se a vantagem for real, ela
   sobrevive; se não, você economizou o desafio. É o passo de maior retorno: hoje a
   hipótese já passou nos dois testes de robustez, falta amostra para testar a média.
2. **Reduzir custo por operação** — conta com spread menor pesa mais que qualquer
   ajuste de indicador. Em H1 no EUR/USD, o prejuízo era 100% custo.
3. **Mais séries na carteira.** Cada mercado descorrelacionado somado multiplica a
   amostra sem exigir edge maior — o caminho estatístico mais barato que existe.
4. **Menos combinações testadas.** Contraintuitivo, mas testar menos hipóteses (e
   escolhidas por razão econômica, não por grid) baixa o limiar de significância.
5. **60+ dias de demo** antes de qualquer desafio pago, comparando execução real com o
   simulado (slippage, spread, horários).
6. **Só então** pagar o desafio, com `safety_factor` baixo: o objetivo é passar, não
   bater a meta rápido.

## Enquanto isso, o que já está garantido

Nos 8 anos de EUR/USD testados, com regras da Fimathe aplicadas:
pior dia **-1,05%** contra limite de -5%, freio interno agindo em -6,15% contra piso de
-10%, **zero violações** em 265 dias operados. O robô perde dinheiro do jeito lento e
controlado — nunca do jeito que estoura a conta.

É pouco? É. Mas é a única metade da frase "ganhar e não perder" que alguém pode
honestamente te entregar.
