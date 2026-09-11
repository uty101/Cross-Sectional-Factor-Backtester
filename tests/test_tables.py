from backtester.tables import parse_table

HTML = """
<html><body>
<table id="other"><tr><td>not this</td></tr></table>
<table class="wikitable" id="changes">
<tr><th rowspan="2">Date</th><th colspan="2">Added</th><th rowspan="2">Reason</th></tr>
<tr><th>Ticker</th><th>Security</th></tr>
<tr><td rowspan="2">June 1, 2020</td><td>AAA</td><td><a href="#">Alpha &amp; Co</a></td>
    <td>Alpha replaced Beta.<sup class="reference"><a href="#c1">[1]</a></sup></td></tr>
<tr><td>BBB</td><td>Beta
  Inc</td><td>ditto</td></tr>
</table></body></html>
"""


def test_rowspan_colspan_and_references() -> None:
    rows = parse_table(HTML, "changes")
    assert rows[0] == ["Date", "Added", "Added", "Reason"]
    assert rows[1] == ["Date", "Ticker", "Security", "Reason"]
    assert rows[2] == ["June 1, 2020", "AAA", "Alpha & Co", "Alpha replaced Beta."]
    assert rows[3] == ["June 1, 2020", "BBB", "Beta Inc", "ditto"]


def test_missing_table_is_an_error() -> None:
    import pytest

    with pytest.raises(ValueError):
        parse_table(HTML, "nope")
