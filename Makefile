.PHONY: install test backtest walkforward report clean

install:
	python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest

data:
	.venv/bin/hantecbot demo-data --out data/synthetic_M15.csv --bars 30000

backtest:
	.venv/bin/hantecbot backtest --csv data/synthetic_M15.csv --report reports/backtest.html

walkforward:
	.venv/bin/hantecbot walkforward --csv data/synthetic_M15.csv --folds 4 --report reports/walkforward.html

challenge:
	.venv/bin/hantecbot challenge --plano double_stage --csv data/synthetic_M15.csv \
		--balance 100000 --montecarlo --report reports/homologacao.html

import-real:
	.venv/bin/python tools/import_csv.py data/EURUSD_M15_raw.csv data/EURUSD_M15.csv --timeframe M15

scan:
	.venv/bin/hantecbot scan --data EURUSD:data/EURUSD_H1.csv:H1:H1,H4 \
		XAUUSD:data/XAUUSD_M15.csv:M15:H1,H4 \
		--strategies trend_atr,mean_reversion --folds 4 --gate runs/gate.json

clean:
	rm -rf .pytest_cache **/__pycache__ reports runs
