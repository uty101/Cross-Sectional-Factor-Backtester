from datetime import date

from backtester import benchmarks

FIVE = """This file was created by CMPT_ME_BEME_OP_INV_RETS using the 202607 CRSP db.

,Mkt-RF,SMB,HML,RMW,CMA,RF
196307,  -0.39,  -0.41,  -0.97,   0.68,  -1.18,   0.27
196308,   5.07,  -0.80,   1.80,   0.36,  -0.35,   0.25

 Annual Factors: January-December

,Mkt-RF,SMB,HML,RMW,CMA,RF
1964,   16.82,   0.44,   4.35,   1.36,   6.71,   3.54
"""

MOM = """This file was created using the 202607 Bloomberg database.

,Mom
192701,   0.36
192702,  -2.14
"""


def test_french_monthly_block_is_parsed_as_decimals() -> None:
    df = benchmarks.parse_french_monthly(FIVE)
    assert df.columns == ["month", "mkt_rf", "smb", "hml", "rmw", "cma", "rf"]
    assert df["month"].to_list() == [date(1963, 7, 31), date(1963, 8, 31)]
    assert abs(df["mkt_rf"][1] - 0.0507) < 1e-12
    assert abs(df["rf"][0] - 0.0027) < 1e-12


def test_momentum_column_is_named_umd() -> None:
    df = benchmarks.parse_french_monthly(MOM)
    assert df.columns == ["month", "umd"]
    assert df["month"][0] == date(1927, 1, 31)
    assert abs(df["umd"][1] + 0.0214) < 1e-12


def test_fred_missing_values_are_dropped() -> None:
    df = benchmarks.parse_fred("DATE,DGS1MO\n2020-01-01,.\n2020-01-02,1.53\n")
    assert df["date"].to_list() == [date(2020, 1, 2)]
    assert df["rate_pct"][0] == 1.53
