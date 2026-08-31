import os

from hantecbot.cli import main
from hantecbot.data import generate, load_csv, save_csv


def test_demo_data_and_backtest_cli(tmp_path, capsys):
    csv_path = tmp_path / "series.csv"
    assert main(["demo-data", "--out", str(csv_path), "--bars", "3000"]) == 0
    assert csv_path.exists()

    report = tmp_path / "r.html"
    assert main(["backtest", "-c", "config/default.yaml", "--csv", str(csv_path),
                 "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "Profit factor" in out and "risco" not in out.split("Profit factor")[0][:20]
    assert report.exists() and "<svg" in report.read_text(encoding="utf-8")


def test_csv_roundtrip(tmp_path):
    candles = generate(bars=500, seed=2)
    path = tmp_path / "c.csv"
    save_csv(str(path), candles)
    loaded = load_csv(str(path))
    assert len(loaded) == len(candles)
    assert abs(loaded[10].close - candles[10].close) < 1e-9
    assert loaded[0].time == candles[0].time


def test_walkforward_cli(tmp_path):
    csv_path = tmp_path / "series.csv"
    main(["demo-data", "--out", str(csv_path), "--bars", "6000"])
    code = main(["walkforward", "-c", "config/default.yaml", "--csv", str(csv_path),
                 "--folds", "2",
                 "--space", '{"atr_stop_mult":[1.5,2.5],"reward_r":[2.0,3.0]}'])
    assert code == 0


def test_paper_replay(tmp_path):
    csv_path = tmp_path / "series.csv"
    main(["demo-data", "--out", str(csv_path), "--bars", "4000"])
    code = main(["paper", "-c", "config/default.yaml", "--csv", str(csv_path),
                 "--out-dir", str(tmp_path / "runs")])
    assert code == 0
    runs = list((tmp_path / "runs").glob("*-trades.csv"))
    assert runs and runs[0].read_text(encoding="utf-8").startswith("symbol,side")


def test_live_requires_mt5_with_clear_message():
    import pytest
    from hantecbot.broker.mt5 import _import_mt5
    try:
        import MetaTrader5  # noqa: F401
    except Exception:
        with pytest.raises(RuntimeError) as exc:
            _import_mt5()
        assert "MetaTrader5 indisponível" in str(exc.value)
