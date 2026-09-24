from daily_report.cli import main


def test_cli_run_and_gen_demo(tmp_path, capsys):
    assert main(["gen-demo", "-o", str(tmp_path / "csv"), "-n", "8", "-d", "2026-09-24"]) == 0
    assert (tmp_path / "csv" / "all.csv").exists()
    assert main(["run", "-s", "csv", "--csv-dir", str(tmp_path / "csv"), "-o", str(tmp_path / "out"), "-f", "md", "-d", "2026-09-24", "--top-n", "3"]) == 0
    out = capsys.readouterr().out
    assert "[md]" in out
    assert (tmp_path / "out" / "2026-09-24.md").exists()
    assert not (tmp_path / "out" / "2026-09-24.html").exists()
