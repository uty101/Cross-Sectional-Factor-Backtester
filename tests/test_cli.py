from backtester import cli


def test_unimplemented_subcommands_say_so(capsys) -> None:
    for argv in (["report"],):
        assert cli.main(argv) == 2
        assert "not implemented" in capsys.readouterr().err


def test_fetch_and_build_require_a_known_step() -> None:
    for argv in (["fetch", "--step", "nope"], ["build"]):
        try:
            cli.main(argv)
        except SystemExit as e:
            assert e.code == 2
        else:
            raise AssertionError("argparse should have rejected this")
