#!/usr/bin/env bash
# Baixa e monta a série XAU/USD M1 de 2024 até o último mês disponível.
#
# Procedência: repositório público kk-at-5/xauusd-raw-data — dump mensal de M1
# feito por um bot cTrader (arquivo ctrader_m1/dump_summary.txt do próprio
# repositório: 4.854.436 barras, 0 duplicatas, 0 timestamps fora de ordem,
# 0 violações de OHLC, primeira barra 2012-10-14, última 2026-07-31).
#
# NÃO é o feed da Hantec. Serve para pesquisa; antes de operar, exporte o
# histórico e a especificação do símbolo do SEU terminal MT5 e refaça o teste
# (os resultados mudam com spread, swap e horário do servidor da corretora).
#
# Uso:  bash tools/fetch_xauusd_2024.sh [ano_inicial]   (padrão: 2024)
set -euo pipefail

ANO_INI="${1:-2024}"
TMP="$(mktemp -d)"
DEST="data/XAUUSD_M1_${ANO_INI}.csv"

echo "• clonando o dump M1 (sparse, só as pastas necessárias)..."
git clone -q --depth 1 --filter=blob:none --sparse \
    https://github.com/kk-at-5/xauusd-raw-data.git "$TMP/xau"
git -C "$TMP/xau" sparse-checkout set ctrader_m1 spread >/dev/null

echo "• concatenando meses a partir de $ANO_INI..."
python3 - "$TMP/xau" "$ANO_INI" <<'PY'
import csv, glob, os, sys
base, ano_ini = sys.argv[1], int(sys.argv[2])
files = sorted(f for f in glob.glob(os.path.join(base, "ctrader_m1", "xauusd_m1_*.csv"))
               if int(os.path.basename(f).split("_")[-1][:4]) >= ano_ini)
with open("/tmp/xauusd_m1_concat.csv", "w", newline="") as out:
    w = csv.writer(out)
    w.writerow(["time", "open", "high", "low", "close", "volume"])
    n = 0
    for f in files:
        with open(f, newline="") as fh:
            for r in csv.DictReader(fh):
                w.writerow([r["datetime_utc"], r["open"], r["high"], r["low"], r["close"], 0])
                n += 1
print(f"  {len(files)} arquivos, {n} candles M1")
PY

echo "• normalizando e auditando..."
python3 tools/import_csv.py /tmp/xauusd_m1_concat.csv "$DEST" --timeframe M1

echo "• spread real medido no feed (bid/ask, mercado aberto):"
python3 - "$TMP/xau" <<'PY'
import csv, glob, os, sys
vals = []
for f in glob.glob(os.path.join(sys.argv[1], "spread", "spread_*.csv")):
    with open(f, newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("market_open") == "1":
                try:
                    vals.append(float(r["spread_pips"]))
                except ValueError:
                    pass
vals.sort()
if vals:
    q = lambda p: vals[int(p * len(vals))]
    print(f"  {len(vals)} amostras | mediana {q(.5):.0f} | p90 {q(.9):.0f} "
          f"| p99 {q(.99):.0f} | máx {vals[-1]:.0f} points (1 point = US$ 0,01/oz)")
PY

rm -rf "$TMP"
echo "✓ pronto: $DEST"
echo "  backtest:  hantecbot backtest -c config/xauusd.yaml --csv $DEST --source-tf M1 --resample H1"
