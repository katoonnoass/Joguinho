# Regras da Fimathe Prop — transcrição verificada

**Fonte primária:** [Regras Oficiais da Fimathe Prop – Programas Fast, Double Stage e
Instant Lite](https://fimatheprop.com/wp-content/uploads/2026/04/Regras-Oficiais-da-Fimathe-Prop_Mar2026-2.pdf)
(PDF marcado como versão **Mar/2026**, publicado em abril/2026 no site da própria mesa).
**Verificado em:** 2026-08-31.
**Fonte secundária** (usada só para confirmar detalhes de FAQ, como consistência e buffer):
respostas públicas da empresa no Reclame Aqui.

> Esta página é uma transcrição de trabalho, não o contrato. Antes de qualquer
> homologação, confirme no painel e nos Termos da **sua** conta: mesa muda regra
> sem aviso e o documento pode estar desatualizado no momento em que você lê.

## Quadro comparativo (como está codificado em `config/fimathe/`)

| Regra | Fast | Double Stage | Conta Financiada | Instant Lite |
|---|---|---|---|---|
| Meta de lucro | 10% | Etapa 1: 10% / Etapa 2: 5% | não tem | não tem |
| **Perda diária máx.** | 5% do saldo do dia anterior | 5% | 5% | **3%** |
| **Perda total máx.** | **6% trailing** | **10% estático** | idem ao desafio de origem | **5% trailing** |
| Risco máximo (flutuante) | — | — | 3% | **1%** |
| Dias lucrativos mín. | nenhum | 3 dias (≥0,5%) | idem desafio | 5 dias (≥0,5%) |
| Consistência | — | — | — | 20% (melhor dia / lucro) |
| Buffer | — | — | — | 3% |
| Inatividade | 30 dias = violação grave | idem | idem | idem |
| Posição no fim de semana | permitido | permitido | permitido | permitido |
| Alavancagem | 50:1 FX · 5:1 ouro/prata/índices/petróleo · 2:1 cripto | idem | idem | idem |
| EA / automação | permitido | permitido | permitido | permitido |

## Onde a memória costuma falhar (diferenças que encontramos)

1. **"Perda total 10% estática" vale só para o Double Stage.** O Fast usa **6% trailing**
   e o Instant Lite **5% trailing** — os dois travam no saldo inicial quando o lucro
   fechado alcança o percentual do trailing.
2. **Instant Lite não tem perda diária de 5%: é 3%** — e ainda tem a regra de
   **Risco Máximo de 1%**, que olha o **prejuízo flutuante** (se o equity cair 1% abaixo
   do saldo, a conta é violada). Isso praticamente define o tamanho máximo de posição.
3. **A régua diária pode subir.** O piso do dia usa o **maior valor entre Saldo e Equity
   no fechamento do dia anterior**. Exemplo do PDF: virou o dia com saldo 100k e equity
   102k → piso do dia seguinte é **96,9k** (5% de 102k), não 95k.
4. **Lucro feito durante o dia não levanta o piso daquele dia.**
5. **Dias lucrativos têm piso de 0,5%** do saldo inicial — um dia de +0,2% não conta.
6. **Inatividade de 30 dias é violação grave** — risco real para EA de tendência, que
   pode passar semanas sem sinal (ver `guard.keepalive_after_days`).
7. **Scalping em massa (<30s) é violação subjetiva**; recomendação da mesa é não passar
   de ~10 operações ultracurtas por sessão.
8. **Após o primeiro saque, o piso de perda total trava no saldo inicial.**

## Como isso vira código

* `src/hantecbot/prop.py` — mecânica dos pisos, contadores e violações (`PropAccount`)
  e o filtro que autoriza ordens (`PropGuard`).
* `config/fimathe/*.yaml` — um preset por plano, com `fonte` e `verificado_em`.
* `tests/test_prop.py` — os exemplos numéricos do PDF viraram testes. Se a mesa mudar
  a regra e você atualizar o preset, o teste correspondente quebra e te obriga a olhar.

## Ritual de atualização (faça antes de cada homologação)

```bash
# 1. baixe o PDF/termos atuais e compare com config/fimathe/
# 2. atualize o preset e a data
sed -i 's/^verificado_em:.*/verificado_em: "AAAA-MM-DD"/' config/fimathe/<plano>.yaml
# 3. rode os testes: eles são a rede de segurança da transcrição
make test
# 4. re-simule a homologação
hantecbot challenge --plano <plano> --csv data/SEU_ATIVO.csv --montecarlo
```
