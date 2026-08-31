# Backtest EUR/USD M15 — 2012-08 a 2020-08 (dados reais)

**Data da execução:** 2026-08-31 · **Commit:** ver `git log` · **Reprodução:** comandos ao final.

## Dados

| item | valor |
|---|---|
| Ativo / timeframe base | EUR/USD, M15 |
| Período | 2012-08-01 → 2020-08-11 (8 anos) |
| Candles após limpeza | 195.576 (4.424 barras de fim de semana descartadas) |
| Duplicatas / barras inconsistentes | 0 / 0 |
| Buracos intradiários | 15 (0,008%) |
| Origem | CSV público no GitHub (`ananiasdave/bus_tickets`), normalizado por `tools/import_csv.py` |

Custos aplicados no motor: spread 8 points, comissão US$ 3,50/lote (round-turn),
slippage 3 points, swap diário. Empate stop/alvo resolvido a favor do stop.

## 1. Configuração padrão, por timeframe

Freio interno desligado para enxergar a série completa (`risk_per_trade_pct` 0,5%, saldo US$ 10.000):

| TF | trades | retorno | PF | DD máx | expectativa | custos pagos | resultado **bruto** |
|---:|---:|---:|---:|---:|---:|---:|---:|
| M15 | 4.285 | **-94,24%** | 0,72 | 94,4% | -0,136 R | 3.491 | -5.933 |
| H1 | 1.238 | -14,40% | 0,94 | 18,7% | -0,021 R | 1.462 | **+22** |
| H4 | 391 | -8,42% | 0,89 | 12,5% | -0,040 R | 230 | -612 |
| D1 | 59 | +1,75% | 1,19 | 3,6% | +0,066 R | 12 | +188 |

Leituras:

* **Em M15 a estratégia é uma máquina de pagar custo.** O bruto já é negativo (-5.933) e
  ainda por cima paga 3.491 de spread+comissão.
* **Em H1 o resultado bruto é zero** (+22 em 8 anos): o prejuízo de -14,4% é **inteiramente**
  custo de transação. Sem vantagem estatística, operar mais é só doar spread.
* **D1 fica positivo, mas com 59 operações em 8 anos** — amostra pequena demais para
  qualquer conclusão (um único trade muda o sinal do resultado).
* `mean_reversion` disparou **7 operações em 8 anos** com os filtros padrão: na prática
  a estratégia não existe nesse timeframe — os filtros precisam ser recalibrados.

## 2. Walk-forward (a pergunta que importa)

144 combinações por janela, otimizadas **só no treino** e medidas na janela seguinte:

| TF | janela 1 | janela 2 | janela 3 | janela 4 | agregado OOS |
|---|---|---|---|---|---|
| H1 | -4,40% | -4,53% | +3,08% | -6,38% | **-11,92%** (PF 0,84) |
| H4 | -3,40% | -2,61% | +0,59% | +3,79% | **-1,77%** (PF 0,92) |

Os parâmetros vencedores **mudam completamente a cada janela** (`fast` pula de 13 para 34,
`breakout` de 20 para 40). Isso é a assinatura clássica de sobreajuste: o grid está
encontrando ruído, não estrutura de mercado.

## 3. Homologação Fimathe (Double Stage, H1, conta de US$ 100k)

```
⏳ NÃO CONCLUÍDO — fimathe_double_stage_e1
    retorno       : -4,99%
    dias operados : 265 (14 lucrativos)
    pior dia      : -1,05%     <- limite oficial: -5,00%
    maior pausa   : 13 dias sem operar (violação em 30)
    consistência  : 6,9%
    encerrado por : kill switch interno (drawdown -6,15%, piso oficial -10%)

Monte Carlo (5.000 cenários): P(aprovar) 0,0% · P(violar) 0,0%
```

**A camada de risco funcionou como projetada**: em 265 dias de operação real o pior dia
foi -1,05% contra um limite de -5%, e o freio interno desligou o robô em -6,15% antes do
piso de -10% da mesa. Nenhuma violação. O que não funcionou foi a **estratégia**:
P(aprovar) = 0%.

## 4. Conclusão

> A infraestrutura está correta e conservadora. A vantagem estatística **não existe** na
> configuração atual. Pagar um desafio com este EA hoje seria comprar um bilhete com
> probabilidade medida de 0% de aprovação.

O que **não** resolve: aumentar risco por operação, aumentar alavancagem, remover o freio
de drawdown — tudo isso só acelera o resultado negativo.

O que pode resolver (em ordem de custo/benefício):

1. **Reduzir custo por operação**: ativo/conta com spread menor, ou timeframe maior. Em H1
   o bruto é zero — qualquer vantagem pequena já viraria lucro líquido.
2. **Testar outros ativos**: índices e ouro têm comportamento de tendência mais persistente
   que EUR/USD, que é notoriamente lateral.
3. **Filtros de contexto**: sessão (só Londres/NY), volatilidade relativa, dia da semana.
4. **Recalibrar `mean_reversion`** — 7 trades em 8 anos significa filtros quebrados.
5. Só depois de um walk-forward positivo em ≥3 janelas: demo por 3 meses, depois desafio.

## Reprodução

```bash
python tools/import_csv.py data/EURUSD_M15_raw.csv data/EURUSD_M15.csv --timeframe M15

hantecbot backtest    --csv data/EURUSD_M15.csv --report reports/eurusd_backtest.html
hantecbot backtest    --csv data/EURUSD_M15.csv --resample H4
hantecbot walkforward --csv data/EURUSD_M15.csv --resample H4 --folds 4 \
    --report reports/eurusd_walkforward_H4.html
hantecbot challenge   --plano double_stage --csv data/EURUSD_M15.csv --resample H1 \
    --balance 100000 --montecarlo --report reports/eurusd_homologacao.html
```

Os CSVs e os HTML ficam fora do Git (`.gitignore`); os comandos acima os regeneram.
