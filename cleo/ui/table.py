import itertools
import math
import re

from copy import deepcopy

from typing import Dict
from typing import Generator
from typing import List
from typing import Optional
from typing import Union

from cleo.formatters.formatter import Formatter
from cleo.io.io import IO
from cleo.io.outputs.output import Output

from .table_cell import TableCell
from .table_cell_style import TableCellStyle
from .table_separator import TableSeparator
from .table_style import TableStyle


_Row = List[Union[str, TableCell]]
_Rows = List[Union[_Row, TableSeparator]]


class Table:

    SEPARATOR_TOP: int = 0
    SEPARATOR_TOP_BOTTOM: int = 1
    SEPARATOR_MID: int = 2
    SEPARATOR_BOTTOM: int = 3

    BORDER_OUTSIDE: int = 0
    BORDER_INSIDE: int = 1

    _styles: Optional[Dict[str, TableStyle]] = None

    def __init__(self, io: Union[IO, Output], style: str = None) -> None:
        self._io = io

        if style is None:
            style = "default"

        self._header_title = None
        self._footer_title = None

        self._headers = []

        self._rows = []
        self._horizontal = False

        self._effective_column_widths: Dict[int, int] = {}

        self._number_of_columns = None

        self._column_styles: Dict[int, TableStyle] = {}
        self._column_widths: Dict[int, int] = {}
        self._column_max_widths: Dict[int, int] = {}

        self._rendered = False

        self._style: Optional[TableStyle] = None
        self._init_styles()
        self.set_style(style)

    @property
    def style(self) -> TableStyle:
        return self._style

    def set_style(self, name: str) -> "Table":
        self._init_styles()

        self._style = self._resolve_style(name)

        return self

    def column_style(self, column_index: int) -> TableStyle:
        if column_index in self._column_styles:
            return self._column_styles[column_index]

        return self._style

    def set_column_style(
        self, column_index: int, style: Union[str, TableStyle]
    ) -> "Table":
        self._column_styles[column_index] = self._resolve_style(style)

        return self

    def set_column_width(self, column_index: int, width: int) -> "Table":
        self._column_widths[column_index] = width

        return self

    def set_column_widths(self, widths: List[int]) -> "Table":
        self._column_widths = {}

        for i, width in enumerate(widths):
            self._column_widths[i] = width

        return self

    def set_column_max_width(self, column_index: int, width: int) -> "Table":
        self._column_widths[column_index] = width

        return self

    def set_headers(self, headers: List[str]) -> "Table":
        if headers and not isinstance(headers[0], list):
            headers = [headers]

        self._headers = headers

        return self

    def set_rows(self, rows: _Rows) -> "Table":
        self._rows = []

        return self.add_rows(rows)

    def add_rows(self, rows: _Rows) -> "Table":
        for row in rows:
            self.add_row(row)

        return self

    def add_row(self, row: Union[_Row, TableSeparator]) -> "Table":
        if isinstance(row, TableSeparator):
            self._rows.append(row)

            return self

        self._rows.append(row)

        return self

    def set_header_title(self, header_title: str) -> "Table":
        self._header_title = header_title

        return self

    def set_footer_title(self, footer_title: str) -> "Table":
        self._footer_title = footer_title

        return self

    def horizontal(self, horizontal: bool = True) -> "Table":
        self._horizontal = horizontal

        return self

    def render(self) -> None:
        divider = TableSeparator()

        if self._horizontal:
            rows = []
            headers = self._headers[0] if self._headers else []
            for i, header in enumerate(headers):
                rows.append([header])
                for row in self._rows:
                    if isinstance(row, TableSeparator):
                        continue

                    if len(row) > i:
                        rows[i].append(row[i])
                    elif isinstance(rows[i][0], TableCell) and rows[i][0].colspan >= 2:
                        # There is a title
                        pass
                    else:
                        rows[i].append(None)
        else:
            rows = self._headers + [divider] + self._rows

        self._calculate_number_of_columns(rows)
        rows = list(self._build_table_rows(rows))
        self._calculate_column_widths(rows)

        is_header = not self._horizontal
        is_first_row = self._horizontal

        for row in rows:
            if row is divider:
                is_header = False
                is_first_row = True

                continue

            if isinstance(row, TableSeparator):
                self._render_row_separator()

                continue

            if not row:
                continue

            if is_header or is_first_row:
                if is_first_row:
                    self._render_row_separator(self.SEPARATOR_TOP_BOTTOM)
                    is_first_row = False
                else:
                    self._render_row_separator(
                        self.SEPARATOR_TOP,
                        self._header_title,
                        self._style.header_title_format,
                    )

            if self._horizontal:
                self._render_row(
                    row, self._style.cell_row_format, self._style.cell_header_format
                )
            else:
                self._render_row(
                    row,
                    self._style.cell_header_format
                    if is_header
                    else self._style.cell_row_format,
                )

        self._render_row_separator(
            self.SEPARATOR_BOTTOM,
            self._footer_title,
            self._style.footer_title_format,
        )

        self._cleanup()
        self._rendered = True

    def _render_row_separator(
        self,
        type: int = SEPARATOR_MID,
        title: Optional[str] = None,
        title_format: Optional[str] = None,
    ) -> None:
        """
        Renders horizontal header separator.

        Example:

            +-----+-----------+-------+
        """
        count = self._number_of_columns
        if not count:
            return

        borders = self._style.border_chars
        if not borders[0] and not borders[2] and not self._style.crossing_char:
            return

        crossings = self._style.crossing_chars
        if type == self.SEPARATOR_MID:
            horizontal, left_char, mid_char, right_char = (
                borders[2],
                crossings[8],
                crossings[0],
                crossings[4],
            )
        elif type == self.SEPARATOR_TOP:
            horizontal, left_char, mid_char, right_char = (
                borders[0],
                crossings[1],
                crossings[2],
                crossings[3],
            )
        elif type == self.SEPARATOR_TOP_BOTTOM:
            horizontal, left_char, mid_char, right_char = (
                borders[0],
                crossings[9],
                crossings[10],
                crossings[11],
            )
        else:
            horizontal, left_char, mid_char, right_char = (
                borders[0],
                crossings[7],
                crossings[6],
                crossings[5],
            )

        markup = left_char
        for column in range(count):
            markup += horizontal * self._effective_column_widths[column]
            markup += right_char if column == count - 1 else mid_char

        if title is not None:
            formatted_title = title_format.format(title)
            title_length = len(self._io.remove_format(formatted_title))
            markup_length = len(markup)
            limit = markup_length - 4

            if title_length > limit:
                title_length = limit
                format_length = len(self._io.remove_format(title_format.format("")))
                formatted_title = title_format.format(
                    title[: limit - format_length - 3] + "..."
                )

            title_start = (markup_length - title_length) // 2
            markup = (
                markup[:title_start]
                + formatted_title
                + markup[title_start + title_length :]
            )

        self._io.write_line(self._style.border_format.format(markup))

    def _render_column_separator(self, type: int = BORDER_OUTSIDE) -> str:
        """
        Renders vertical column separator.
        """
        borders = self._style.border_chars

        return self._style.border_format.format(
            borders[1] if type == self.BORDER_OUTSIDE else borders[3]
        )

    def _render_row(
        self, row: List[str], cell_format: str, first_cell_format: Optional[str] = None
    ) -> None:
        """
        Renders table row.

        Example:

            | 9971-5-0210-0 | A Tale of Two Cities  | Charles Dickens  |
        """
        row_content = self._render_column_separator(self.BORDER_OUTSIDE)
        columns = self._get_row_columns(row)
        last = len(columns) - 1
        for i, column in enumerate(columns):
            if first_cell_format and i == 0:
                row_content += self._render_cell(row, column, first_cell_format)
            else:
                row_content += self._render_cell(row, column, cell_format)

            row_content += self._render_column_separator(
                self.BORDER_OUTSIDE if i == last else self.BORDER_INSIDE
            )

        self._io.write_line(row_content)

    def _render_cell(self, row: _Row, column: int, cell_format: str) -> str:
        """
        Renders a table cell with padding.
        """
        try:
            cell = row[column]
        except IndexError:
            cell = ""

        width = self._effective_column_widths[column]
        if isinstance(cell, TableCell) and cell.colspan > 1:
            # add the width of the following columns(numbers of colspan).
            for next_column in range(column + 1, column + cell.colspan):
                width += (
                    self._get_column_separator_width()
                    + self._effective_column_widths[next_column]
                )

        style = self.column_style(column)

        if isinstance(cell, TableSeparator):
            return style.border_format.format(style.border_chars[2] * width)

        width += len(cell) - len(self._io.remove_format(cell))
        content = style.cell_row_content_format.format(cell)

        pad = style.pad
        if isinstance(cell, TableCell) and isinstance(cell.style, TableCellStyle):
            is_not_styled_by_tag = not re.match(
                r"^<(\w+|(\w+=[\w,]+;?)*)>.+</(\w+|(\w+=\w+;?)*)?>$", str(cell)
            )
            if is_not_styled_by_tag:
                cell_format = cell.style.cell_format
                if cell_format is None:
                    cell_format = f"<{cell.style.tag}>{{}}</>"

                if "</>" in content:
                    content = content.replace("</>", "")
                    width -= 3

                if "<fg=default;bg=default>" in content:
                    content = content.replace("<fg=default;bg=default>")
                    width -= len("<fg=default;bg=default>")

            pad = cell.style.pad

        return cell_format.format(pad(content, width, style.padding_char))

    def _calculate_number_of_columns(self, rows: _Rows) -> None:
        columns = [0]
        for row in rows:
            if isinstance(row, TableSeparator):
                continue

            columns.append(self._get_number_of_columns(row))

        self._number_of_columns = max(columns)

    def _build_table_rows(self, rows: _Rows) -> Generator:
        unmerged_rows = {}
        row_key = 0
        while row_key < len(rows):
            rows = self._fill_next_rows(rows, row_key)

            # Remove any new line breaks and replace it with a new line
            for column, cell in enumerate(rows[row_key]):
                colspan = cell.colspan if isinstance(cell, TableCell) else 1

                if column in self._column_max_widths and self._column_max_widths[
                    column
                ] < len(self._io.remove_format(cell)):
                    cell = self._io.formatter.format_and_wrap(
                        cell, self._column_max_widths[column] * colspan
                    )

                if "\n" not in cell:
                    continue

                escaped = "\n".join(
                    Formatter.escape_trailing_backslash(c) for c in cell.split("\n")
                )
                cell = (
                    TableCell(escaped, colspan=cell.colspan)
                    if isinstance(cell, TableCell)
                    else escaped
                )
                lines = cell.replace("\n", "<fg=default;bg=default>\n</>").split("\n")

                for line_key, line in enumerate(lines):
                    if colspan > 1:
                        line = TableCell(line, colspan=colspan)

                    if line_key == 0:
                        rows[row_key][column] = line
                    else:
                        if row_key not in unmerged_rows:
                            unmerged_rows[row_key] = {}

                        if line_key not in unmerged_rows[row_key]:
                            unmerged_rows[row_key][line_key] = self._copy_row(
                                rows, row_key
                            )

                        unmerged_rows[row_key][line_key][column] = line

            row_key += 1

        for row_key, row in enumerate(rows):
            yield self._fill_cells(row)

            if row_key in unmerged_rows:
                for unmerged_row in unmerged_rows[row_key].values():
                    yield self._fill_cells(unmerged_row)

    def _calculate_row_count(self) -> int:
        number_of_rows = len(
            list(
                self._build_table_rows(self._headers + [TableSeparator()] + self._rows)
            )
        )

        if self._headers:
            number_of_rows += 1

        if len(self._rows) > 0:
            number_of_rows += 1

        return number_of_rows

    def _fill_next_rows(self, rows: _Rows, line: int) -> _Rows:
        """
        Fill rows that contains rowspan > 1.
        """
        unmerged_rows = {}

        for column, cell in enumerate(rows[line]):
            if isinstance(cell, TableCell) and cell.rowspan > 1:
                nb_lines = cell.rowspan - 1
                lines = [cell]
                if "\n" in cell:
                    lines = cell.replace("\n", "<fg=default;bg=default>\n</>").split(
                        "\n"
                    )
                    if len(lines) > nb_lines:
                        nb_lines = cell.count("\n")

                    rows[line][column] = TableCell(
                        lines[0], colspan=cell.colspan, style=cell.style
                    )

                # Create a two dimensional dict (rowspan x colspan)
                placeholder = dict(
                    [(k, {}) for k in range(line + 1, line + 1 + nb_lines)]
                )
                for k, v in unmerged_rows.items():
                    if k in placeholder:
                        for l, m in unmerged_rows[k].items():
                            if l in placeholder[k]:
                                placeholder[k][l].update(m)
                            else:
                                placeholder[k][l] = m
                    else:
                        placeholder[k] = v

                unmerged_rows = placeholder

                for unmerged_row_key, _ in unmerged_rows.items():
                    value = ""
                    if unmerged_row_key - line < len(lines):
                        value = lines[unmerged_row_key - line]

                    unmerged_rows[unmerged_row_key][column] = TableCell(
                        value, colspan=cell.colspan, style=cell.style
                    )
                    if nb_lines == unmerged_row_key - line:
                        break

        for unmerged_row_key, unmerged_row in unmerged_rows.items():
            # we need to know if unmerged_row will be merged or inserted into rows
            if (
                unmerged_row_key < len(rows)
                and isinstance(rows[unmerged_row_key], list)
                and (
                    (
                        self._get_number_of_columns(rows[unmerged_row_key])
                        + self._get_number_of_columns(
                            list(unmerged_rows[unmerged_row_key].values())
                        )
                    )
                    <= self._number_of_columns
                )
            ):
                # insert cell into row at cell_key position
                for cell_key, cell in unmerged_row.items():
                    rows[unmerged_row_key].insert(cell_key, cell)
            else:
                row = self._copy_row(rows, unmerged_row_key - 1)
                for column, cell in unmerged_row.items():
                    if len(cell):
                        row[column] = unmerged_row[column]

                rows.insert(unmerged_row_key, row)

        return rows

    def _fill_cells(self, row: _Row) -> List[Union[str, TableCell]]:
        """
        Fills cells for a row that contains colspan > 1.
        """
        new_row = []

        for column, cell in enumerate(row):
            new_row.append(cell)

            if isinstance(cell, TableCell) and cell.colspan > 1:
                for _ in range(column + 1, column + cell.colspan):
                    # insert empty value at column position
                    new_row.append("")

        if new_row:
            return new_row

        return row

    def _copy_row(self, rows: _Rows, line: int) -> _Row:
        """
        Copies a row.
        """
        row = [x for x in rows[line]]

        for cell_key, cell_value in enumerate(row):
            row[cell_key] = ""
            if isinstance(cell_value, TableCell):
                row[cell_key] = TableCell("", colspan=cell_value.colspan)

        return row

    def _get_number_of_columns(self, row: _Row):
        """
        Gets number of columns by row.
        """
        columns = len(row)
        for column in row:
            if isinstance(column, TableCell):
                columns += column.colspan - 1

        return columns

    def _get_row_columns(self, row: _Row) -> List[int]:
        """
        Gets list of columns for the given row.
        """
        columns = list(range(0, self._number_of_columns))

        for cell_key, cell in enumerate(row):
            if isinstance(cell, TableCell) and cell.colspan > 1:
                # exclude grouped columns.
                columns = [
                    x
                    for x in columns
                    if x not in list(range(cell_key + 1, cell_key + cell.colspan))
                ]

        return columns

    def _calculate_column_widths(self, rows: _Rows) -> None:
        """
        Calculates column widths.
        """
        for column in range(0, self._number_of_columns):
            lengths = [0]
            for row in rows:
                if isinstance(row, TableSeparator):
                    continue

                row_ = row.copy()
                for i, cell in enumerate(row_):
                    if isinstance(cell, TableCell):
                        text_content = self._io.remove_format(cell)
                        text_length = len(text_content)
                        if text_length:
                            length = math.ceil(text_length / cell.colspan)
                            content_columns = [
                                text_content[i : i + length]
                                for i in range(0, text_length, length)
                            ]

                            for position, content in enumerate(content_columns):
                                try:
                                    row_[i + position] = content
                                except IndexError:
                                    row_.append(content)

                lengths.append(self._get_cell_width(row_, column))

            self._effective_column_widths[column] = (
                max(lengths) + len(self._style.cell_row_content_format) - 2
            )

    def _get_column_separator_width(self) -> int:
        return len(self._style.border_format.format(self._style.border_chars[3]))

    def _get_cell_width(self, row: _Row, column: int) -> int:
        """
        Gets cell width.
        """
        cell_width = 0

        try:
            cell = row[column]
            cell_width = len(self._io.remove_format(cell))
        except IndexError:
            pass

        column_width = (
            self._column_widths[column] if column in self._column_widths else 0
        )
        cell_width = max(cell_width, column_width)

        if column in self._column_max_widths:
            return min(self._column_max_widths[column], cell_width)

        return cell_width

    def _cleanup(self):
        self._column_widths = {}
        self._number_of_columns = None

    @classmethod
    def _init_styles(cls) -> None:
        if cls._styles is not None:
            return

        borderless = TableStyle()
        borderless.set_horizontal_border_chars("=")
        borderless.set_vertical_border_chars(" ")
        borderless.set_default_crossing_char(" ")

        compact = TableStyle()
        compact.set_horizontal_border_chars("")
        compact.set_vertical_border_chars(" ")
        compact.set_default_crossing_char("")
        compact.set_cell_row_content_format("{}")

        box = TableStyle()
        box.set_horizontal_border_chars("─")
        box.set_vertical_border_chars("│")
        box.set_crossing_chars("┼", "┌", "┬", "┐", "┤", "┘", "┴", "└", "├")

        box_double = TableStyle()
        box_double.set_horizontal_border_chars("═", "─")
        box_double.set_vertical_border_chars("║", "│")
        box_double.set_crossing_chars(
            "┼", "╔", "╤", "╗", "╢", "╝", "╧", "╚", "╟", "╠", "╪", "╣"
        )

        cls._styles = {
            "default": TableStyle(),
            "borderless": borderless,
            "compact": compact,
            "box": box,
            "box-double": box_double,
        }

    @classmethod
    def _resolve_style(cls, name: Union[str, TableStyle]) -> TableStyle:
        if isinstance(name, TableStyle):
            return name

        if name in cls._styles:
            return deepcopy(cls._styles[name])

        raise ValueError(f'Table style "{name}" is not defined.')
