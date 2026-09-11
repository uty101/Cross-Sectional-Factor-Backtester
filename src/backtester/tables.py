"""Extract a Wikipedia HTML table into rows of cell text, stdlib only.

Handles ``rowspan``/``colspan`` (the changes table has used both over the
years), drops reference superscripts (``[12]``), and collapses whitespace.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_WS = re.compile(r"\s+")


class _TableParser(HTMLParser):
    def __init__(self, table_id: str) -> None:
        super().__init__()
        self.table_id = table_id
        self.rows: list[list[str]] = []
        self._in_table = False
        self._depth = 0
        self._row: list[tuple[str, int, int]] | None = None
        self._cell: list[str] | None = None
        self._span = (1, 1)
        self._sup = 0
        self._pending: dict[int, tuple[str, int]] = {}  # col -> (text, rows left)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            if self._in_table:
                self._depth += 1
            elif a.get("id") == self.table_id:
                self._in_table = True
            return
        if not self._in_table or self._depth:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._span = (int(a.get("rowspan") or 1), int(a.get("colspan") or 1))
        elif tag == "sup" and self._cell is not None:
            self._sup += 1
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            if self._depth:
                self._depth -= 1
            else:
                self._in_table = False
            return
        if not self._in_table or self._depth:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = _WS.sub(" ", "".join(self._cell)).strip()
            self._row.append((text, *self._span))
            self._cell = None
        elif tag == "sup" and self._sup:
            self._sup -= 1
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._expand(self._row))
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._sup:
            self._cell.append(data)

    def _expand(self, cells: list[tuple[str, int, int]]) -> list[str]:
        out: list[str] = []
        col = 0
        it = iter(cells)
        nxt = next(it, None)
        while nxt is not None or col in self._pending:
            if col in self._pending:
                text, left = self._pending.pop(col)
                out.append(text)
                if left > 1:
                    self._pending[col] = (text, left - 1)
                col += 1
                continue
            text, rs, cs = nxt
            for _ in range(cs):
                out.append(text)
                if rs > 1:
                    self._pending[col] = (text, rs - 1)
                col += 1
            nxt = next(it, None)
        return out


def parse_table(html: str, table_id: str) -> list[list[str]]:
    """Rows of the ``<table id=table_id>`` as lists of cell text, spans expanded."""
    p = _TableParser(table_id)  # convert_charrefs=True: entities arrive decoded
    p.feed(html)
    if not p.rows:
        raise ValueError(f"no table with id={table_id!r}")
    return p.rows
