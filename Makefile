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

clean:
	rm -rf .pytest_cache **/__pycache__ reports runs
