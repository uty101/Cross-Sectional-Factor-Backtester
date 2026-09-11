from backtester import cli


def test_every_subcommand_parses_and_reports_unimplemented(capsys) -> None:
    for argv in (["fetch"], ["build"], ["run", "--factor", "momentum"], ["report"]):
        assert cli.main(argv) == 2
        assert "not implemented" in capsys.readouterr().err
