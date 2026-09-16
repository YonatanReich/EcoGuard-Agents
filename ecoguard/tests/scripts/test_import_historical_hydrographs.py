"""Explicit historical hydrograph import command behaviour."""

from pathlib import Path

from ecoguard.scripts import import_historical_hydrographs


def test_run_imports_files_before_rebuilding_baselines(monkeypatch):
    calls = []

    def load(paths):
        calls.append(("load", list(paths)))
        return {
            "files_imported": 2,
            "files_unchanged": 0,
            "rows_written": 1_567_498,
            "source_rows": 1_567_498,
            "stations_seen": 166,
        }

    def rebuild():
        calls.append(("baselines", None))
        return 540

    monkeypatch.setattr(
        import_historical_hydrographs,
        "load_historical_hydrograph_files",
        load,
    )
    monkeypatch.setattr(
        import_historical_hydrographs,
        "refresh_flood_station_baselines",
        rebuild,
    )

    result = import_historical_hydrographs.run(
        [Path("first.csv"), Path("second.csv")]
    )

    assert calls == [
        ("load", [Path("first.csv"), Path("second.csv")]),
        ("baselines", None),
    ]
    assert result["monthly_baselines"] == 540


def test_main_prints_a_short_import_summary(monkeypatch, capsys):
    monkeypatch.setattr(
        import_historical_hydrographs,
        "run",
        lambda paths: {
            "files_imported": 1,
            "files_unchanged": 1,
            "rows_written": 900,
            "source_rows": 1_000,
            "stations_seen": 25,
            "monthly_baselines": 120,
        },
    )

    import_historical_hydrographs.main(["first.csv", "second.csv"])

    output = capsys.readouterr().out
    assert "1 imported, 1 unchanged" in output
    assert "900 rows written" in output
    assert "25 source stations" in output
    assert "120 monthly rows" in output
