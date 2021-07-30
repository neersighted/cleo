import ast
import inspect
import io
import keyword
import os
import re
import sys
import tokenize

from typing import List
from typing import Optional
from typing import Union

from crashtest.frame import Frame
from crashtest.frame_collection import FrameCollection
from crashtest.inspector import Inspector
from crashtest.solution_providers.solution_provider_repository import (
    SolutionProviderRepository,
)

from cleo.formatters.formatter import Formatter
from cleo.io.io import IO
from cleo.io.outputs.output import Output


class Highlighter:

    TOKEN_DEFAULT = "token_default"
    TOKEN_COMMENT = "token_comment"
    TOKEN_STRING = "token_string"
    TOKEN_NUMBER = "token_number"
    TOKEN_KEYWORD = "token_keyword"
    TOKEN_BUILTIN = "token_builtin"
    TOKEN_OP = "token_op"
    LINE_MARKER = "line_marker"
    LINE_NUMBER = "line_number"

    DEFAULT_THEME = {
        TOKEN_STRING: "fg=yellow;options=bold",
        TOKEN_NUMBER: "fg=blue;options=bold",
        TOKEN_COMMENT: "fg=default;options=dark,italic",
        TOKEN_KEYWORD: "fg=magenta;options=bold",
        TOKEN_BUILTIN: "fg=default;options=bold",
        TOKEN_DEFAULT: "fg=default",
        TOKEN_OP: "fg=default;options=dark",
        LINE_MARKER: "fg=red;options=bold",
        LINE_NUMBER: "fg=default;options=dark",
    }

    KEYWORDS = set(keyword.kwlist)
    BUILTINS = set(
        __builtins__.keys() if type(__builtins__) is dict else dir(__builtins__)
    )

    UI = {
        False: {"arrow": ">", "delimiter": "|"},
        True: {"arrow": "→", "delimiter": "│"},
    }

    def __init__(self, supports_utf8: bool = True) -> None:
        self._theme = self.DEFAULT_THEME.copy()
        self._ui = self.UI[supports_utf8]

    def code_snippet(
        self, source: str, line: int, lines_before: int = 2, lines_after: int = 2
    ) -> List[str]:
        token_lines = self.highlighted_lines(source)
        token_lines = self.line_numbers(token_lines, line)

        offset = line - lines_before - 1
        offset = max(offset, 0)
        length = lines_after + lines_before + 1
        token_lines = token_lines[offset : offset + length]

        return token_lines

    def highlighted_lines(self, source):
        source = source.replace("\r\n", "\n").replace("\r", "\n")

        return self.split_to_lines(source)

    def split_to_lines(self, source):
        lines = []
        current_line = 1
        current_col = 0
        buffer = ""
        current_type = None
        source_io = io.BytesIO(source.encode())
        formatter = Formatter()

        def readline():
            return formatter.format(
                formatter.escape(source_io.readline().decode())
            ).encode()

        tokens = tokenize.tokenize(readline)
        line = ""
        for token_info in tokens:
            token_type, token_string, start, end, _ = token_info
            lineno = start[0]
            if lineno == 0:
                # Encoding line
                continue

            if token_type == tokenize.ENDMARKER:
                # End of source
                if current_type is None:
                    current_type = self.TOKEN_DEFAULT

                line += "<{}>{}</>".format(self._theme[current_type], buffer)
                lines.append(line)
                break

            if lineno > current_line:
                if current_type is None:
                    current_type = self.TOKEN_DEFAULT

                diff = lineno - current_line
                if diff > 1:
                    lines += [""] * (diff - 1)

                line += "<{}>{}</>".format(
                    self._theme[current_type], buffer.rstrip("\n")
                )

                # New line
                lines.append(line)
                line = ""
                current_line = lineno
                current_col = 0
                buffer = ""

            if token_string in self.KEYWORDS:
                new_type = self.TOKEN_KEYWORD
            elif token_string in self.BUILTINS or token_string == "self":
                new_type = self.TOKEN_BUILTIN
            elif token_type == tokenize.STRING:
                new_type = self.TOKEN_STRING
            elif token_type == tokenize.NUMBER:
                new_type = self.TOKEN_NUMBER
            elif token_type == tokenize.COMMENT:
                new_type = self.TOKEN_COMMENT
            elif token_type == tokenize.OP:
                new_type = self.TOKEN_OP
            elif token_type == tokenize.NEWLINE:
                continue
            else:
                new_type = self.TOKEN_DEFAULT

            if current_type is None:
                current_type = new_type

            if start[1] > current_col:
                buffer += token_info.line[current_col : start[1]]

            if current_type != new_type:
                line += "<{}>{}</>".format(self._theme[current_type], buffer)
                buffer = ""
                current_type = new_type

            if lineno < end[0]:
                # The token spans multiple lines
                token_lines = token_string.split("\n")
                line += "<{}>{}</>".format(self._theme[current_type], token_lines[0])
                lines.append(line)
                for token_line in token_lines[1:-1]:
                    lines.append(
                        "<{}>{}</>".format(self._theme[current_type], token_line)
                    )

                current_line = end[0]
                buffer = token_lines[-1][: end[1]]
                line = ""
                continue

            buffer += token_string
            current_col = end[1]
            current_line = lineno

        return lines

    def line_numbers(
        self, lines: List[str], mark_line: Optional[int] = None
    ) -> List[str]:
        max_line_length = max(3, len(str(len(lines))))

        snippet_lines = []
        marker = "<{}>{}</> ".format(self._theme[self.LINE_MARKER], self._ui["arrow"])
        no_marker = "  "
        for i, line in enumerate(lines):
            if mark_line is not None:
                if mark_line == i + 1:
                    snippet = marker
                else:
                    snippet = no_marker

            line_number = "{:>{}}".format(i + 1, max_line_length)
            snippet += "<{}>{}</><{}>{}</> {}".format(
                "fg=default;options=bold"
                if mark_line == i + 1
                else self._theme[self.LINE_NUMBER],
                line_number,
                self._theme[self.LINE_NUMBER],
                self._ui["delimiter"],
                line,
            )
            snippet_lines.append(snippet)

        return snippet_lines


class ExceptionTrace:
    """
    Renders the trace of an exception.
    """

    THEME = {
        "comment": "<fg=black;options=bold>",
        "keyword": "<fg=yellow>",
        "builtin": "<fg=blue>",
        "literal": "<fg=magenta>",
    }

    AST_ELEMENTS = {
        "builtins": __builtins__.keys()
        if type(__builtins__) is dict
        else dir(__builtins__),
        "keywords": [
            getattr(ast, cls)
            for cls in dir(ast)
            if keyword.iskeyword(cls.lower())
            and inspect.isclass(getattr(ast, cls))
            and issubclass(getattr(ast, cls), ast.AST)
        ],
    }

    _FRAME_SNIPPET_CACHE = {}

    def __init__(
        self,
        exception: Exception,
        solution_provider_repository: Optional[SolutionProviderRepository] = None,
    ) -> None:
        self._exception = exception
        self._solution_provider_repository = solution_provider_repository
        self._exc_info = sys.exc_info()
        self._ignore = None

    def ignore_files_in(self, ignore: str) -> "ExceptionTrace":
        self._ignore = ignore

        return self

    def render(self, io: Union[IO, Output], simple: bool = False) -> None:
        if simple:
            io.write_line("")
            io.write_line("<error>{}</error>".format(str(self._exception)))
            return

        return self._render_exception(io, self._exception)

    def _render_exception(self, io: Union[IO, Output], exception: Exception) -> None:
        from crashtest.inspector import Inspector

        inspector = Inspector(exception)
        if not inspector.frames:
            return

        if inspector.has_previous_exception():
            self._render_exception(io, inspector.previous_exception)
            io.write_line("")
            io.write_line(
                "The following error occurred when trying to handle this error:"
            )
            io.write_line("")

        self._render_trace(io, inspector.frames)

        self._render_line(
            io, "<error>{}</error>".format(inspector.exception_name), True
        )
        io.write_line("")
        exception_message = (
            Formatter().format(inspector.exception_message).replace("\n", "\n  ")
        )
        self._render_line(io, "<b>{}</b>".format(exception_message))

        current_frame = inspector.frames[-1]
        self._render_snippet(io, current_frame)

        self._render_solution(io, inspector)

    def _render_snippet(self, io: Union[IO, Output], frame: Frame):
        self._render_line(
            io,
            "at <fg=green>{}</>:<b>{}</b> in <fg=cyan>{}</>".format(
                self._get_relative_file_path(frame.filename),
                frame.lineno,
                frame.function,
            ),
            True,
        )

        code_lines = Highlighter(supports_utf8=io.supports_utf8()).code_snippet(
            frame.file_content, frame.lineno, 4, 4
        )

        for code_line in code_lines:
            self._render_line(io, code_line, indent=4)

    def _render_solution(self, io: Union[IO, Output], inspector: Inspector):
        if self._solution_provider_repository is None:
            return

        solutions = self._solution_provider_repository.get_solutions_for_exception(
            inspector.exception
        )
        symbol = "•"
        if not io.supports_utf8():
            symbol = "*"

        for solution in solutions:
            title = solution.solution_title
            description = solution.solution_description
            links = solution.documentation_links

            description = description.replace("\n", "\n    ").strip(" ")

            self._render_line(
                io,
                "<fg=blue;options=bold>{} </><fg=default;options=bold>{}</>: {}{}".format(
                    symbol,
                    title.rstrip("."),
                    description,
                    ",".join("\n    <fg=blue>{}</>".format(link) for link in links),
                ),
                True,
            )

    def _render_trace(self, io: Union[IO, Output], frames: FrameCollection) -> None:
        stack_frames = FrameCollection()
        for frame in frames:
            if (
                self._ignore
                and re.match(self._ignore, frame.filename)
                and not io.is_debug()
            ):
                continue

            stack_frames.append(frame)

        remaining_frames_length = len(stack_frames) - 1
        if io.is_verbose() and remaining_frames_length:
            self._render_line(io, "<fg=yellow>Stack trace</>:", True)
            max_frame_length = len(str(remaining_frames_length))
            frame_collections = stack_frames.compact()
            i = remaining_frames_length
            for collection in frame_collections:
                if collection.is_repeated():
                    if len(collection) > 1:
                        frames_message = "<fg=yellow>{}</> frames".format(
                            len(collection)
                        )
                    else:
                        frames_message = "frame"

                    self._render_line(
                        io,
                        "<fg=blue>{:>{}}</>  Previous {} repeated <fg=blue>{}</> times".format(
                            "...",
                            max_frame_length,
                            frames_message,
                            collection.repetitions + 1,
                        ),
                        True,
                    )

                    i -= len(collection) * (collection.repetitions + 1)

                for frame in collection:
                    relative_file_path = self._get_relative_file_path(frame.filename)
                    relative_file_path_parts = relative_file_path.split(os.path.sep)
                    relative_file_path = "{}".format(
                        "<fg=default;options=dark>{}</>".format(
                            Formatter.escape(os.sep)
                        ).join(
                            relative_file_path_parts[:-1]
                            + [
                                "<fg=default;options=bold>{}</>".format(
                                    relative_file_path_parts[-1]
                                )
                            ]
                        ),
                    )

                    self._render_line(
                        io,
                        "<fg=yellow>{:>{}}</>  {}<fg=default;options=dark>:</><b>{}</b> in <fg=cyan>{}</>".format(
                            i,
                            max_frame_length,
                            relative_file_path,
                            frame.lineno,
                            frame.function,
                        ),
                        True,
                    )

                    if io.is_debug():
                        if (frame, 2, 2) not in self._FRAME_SNIPPET_CACHE:
                            code_lines = Highlighter(
                                supports_utf8=io.supports_utf8()
                            ).code_snippet(
                                frame.file_content,
                                frame.lineno,
                            )

                            self._FRAME_SNIPPET_CACHE[(frame, 2, 2)] = code_lines

                        code_lines = self._FRAME_SNIPPET_CACHE[(frame, 2, 2)]

                        for code_line in code_lines:
                            self._render_line(
                                io,
                                "{:>{}}{}".format(" ", max_frame_length, code_line),
                                indent=3,
                            )
                    else:
                        highlighter = Highlighter(supports_utf8=io.supports_utf8())
                        try:
                            code_line = highlighter.highlighted_lines(
                                frame.line.strip()
                            )[0]
                        except tokenize.TokenError:
                            code_line = frame.line.strip()

                        self._render_line(
                            io,
                            "{:>{}}    {}".format(
                                " ",
                                max_frame_length,
                                code_line,
                            ),
                        )

                    i -= 1

    def _render_line(
        self, io: Union[IO, Output], line: str, new_line: bool = False, indent: int = 2
    ) -> None:
        if new_line:
            io.write_line("")

        io.write_line("{}{}".format(indent * " ", line))

    def _get_relative_file_path(self, filepath: str) -> str:
        cwd = os.getcwd()

        if cwd:
            filepath = filepath.replace(cwd + os.path.sep, "")

        home = os.path.expanduser("~")
        if home:
            filepath = filepath.replace(home + os.path.sep, "~" + os.path.sep)

        return filepath
