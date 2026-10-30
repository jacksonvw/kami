"""Markdown preview rendering, styled after VS Code's preview.

Qt parses the Markdown (GitHub's dialect, so tables, task lists and
strikethrough work) straight into a QTextDocument, and this module restyles
the result block by block: heading sizes with a rule under the first two
levels, code in the fixed-width font with Pygments colours, quotes, tables
and links. No HTML and no web engine are involved, so opening the preview
costs next to nothing.

HTML tags in the Markdown are shown as typed. Qt's importer holds back all
the text after a tag until it sees that tag closed, so a <br>, or a
placeholder such as <work dir>, emptied the rest of the document.

Pygments comes from Fedora's python3-pygments, which most desktops already
have. Without it, code is shown in a single colour.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QImageReader,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
    QTextLength,
    QTextTable,
)

try:
    from pygments.lexers import get_lexer_by_name
    from pygments.token import Token
    from pygments.util import ClassNotFound
except ImportError:  # Only the code colours depend on it.
    get_lexer_by_name = None

# Line heights are given as a percentage of the font's height.
_PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
_FIXED = QTextBlockFormat.LineHeightTypes.FixedHeight.value

# Sizes relative to the body text, from VS Code's preview stylesheet.
HEADING_SCALE = {1: 2.0, 2: 1.5, 3: 1.25, 4: 1.0, 5: 0.875, 6: 0.85}

# VS Code's Dark+ and Light+ token colours.
_DARK_TOKENS = {
    "Comment": "#6a9955",
    "Keyword": "#569cd6",
    "Name.Builtin": "#4ec9b0",
    "Name.Class": "#4ec9b0",
    "Name.Function": "#dcdcaa",
    "Name.Decorator": "#dcdcaa",
    "Name.Tag": "#569cd6",
    "Name.Attribute": "#9cdcfe",
    "Name.Variable": "#9cdcfe",
    "Literal.String": "#ce9178",
    "Literal.Number": "#b5cea8",
    "Operator.Word": "#569cd6",
    "Generic.Heading": "#569cd6",
    "Generic.Inserted": "#b5cea8",
    "Generic.Deleted": "#ce9178",
}
_LIGHT_TOKENS = {
    "Comment": "#008000",
    "Keyword": "#0000ff",
    "Name.Builtin": "#267f99",
    "Name.Class": "#267f99",
    "Name.Function": "#795e26",
    "Name.Decorator": "#795e26",
    "Name.Tag": "#800000",
    "Name.Attribute": "#e50000",
    "Name.Variable": "#001080",
    "Literal.String": "#a31515",
    "Literal.Number": "#098658",
    "Operator.Word": "#0000ff",
    "Generic.Heading": "#000080",
    "Generic.Inserted": "#098658",
    "Generic.Deleted": "#a31515",
}


@dataclass(frozen=True)
class PreviewStyle:
    body_font: QFont
    code_font: QFont
    text: QColor
    muted: QColor
    rule: QColor
    code_bg: QColor
    link: QColor
    dark: bool


def _block_cursor(block: QTextBlock) -> QTextCursor:
    """A cursor selecting the whole of `block`'s text."""
    cur = QTextCursor(block)
    cur.movePosition(QTextCursor.StartOfBlock)
    cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
    return cur


def _is_code(block: QTextBlock) -> bool:
    return block.blockFormat().hasProperty(QTextFormat.BlockCodeLanguage)


def render_markdown(
    doc: QTextDocument,
    text: str,
    style: PreviewStyle,
    base_dir: str | None = None,
    max_image_width: int = 0,
) -> list[tuple[QTextBlock, int]]:
    """Render `text` into `doc`. Returns the quote blocks and their levels,
    for the preview to draw the bars beside them.
    """
    doc.clear()
    doc.setDefaultFont(style.body_font)
    doc.setDocumentMargin(20)
    # Relative links and images resolve against the file's own folder.
    doc.setBaseUrl(QUrl.fromLocalFile(base_dir.rstrip("/") + "/") if base_dir else QUrl())
    doc.setMarkdown(text, QTextDocument.MarkdownDialectGitHub | QTextDocument.MarkdownNoHTML)

    pt = style.body_font.pointSizeF()
    if pt <= 0:
        pt = 10.0
    quotes: list[tuple[QTextBlock, int]] = []

    block = doc.begin()
    while block.isValid():
        if _is_code(block):
            block = _style_code_run(block, style, pt)
            continue
        _style_block(block, style, pt, quotes)
        block = block.next()

    _style_inline(doc, style, pt, base_dir, max_image_width)
    for table in _tables(doc):
        _style_table(table, style)
    return quotes


def _style_block(block: QTextBlock, style: PreviewStyle, pt: float, quotes: list) -> None:
    bf = QTextBlockFormat(block.blockFormat())
    cur = _block_cursor(block)
    level = bf.headingLevel()
    quote = bf.intProperty(QTextFormat.BlockQuoteLevel)

    if level:
        # VS Code greys out the smallest heading.
        _size_heading(block, pt * HEADING_SCALE.get(level, 1.0), style.muted if level == 6 else None)
        bf.setTopMargin(pt * (1.5 if block.previous().isValid() else 0.2))
        bf.setBottomMargin(pt * 0.6)
        if level <= 2:
            # A rule under the heading, drawn below the line; the extra
            # line height keeps it off the descenders.
            bf.setProperty(
                QTextFormat.BlockTrailingHorizontalRulerWidth,
                QTextLength(QTextLength.PercentageLength, 100),
            )
            bf.setLineHeight(125, _PROPORTIONAL)
            bf.setBottomMargin(pt * 0.9)
    elif QTextCursor(block).currentTable() is not None:
        bf.setTopMargin(0)
        bf.setBottomMargin(0)
        bf.setLineHeight(120, _PROPORTIONAL)
    elif not bf.hasProperty(QTextFormat.BlockTrailingHorizontalRulerWidth):
        if block.textList() is None:
            bf.setLineHeight(150, _PROPORTIONAL)
            bf.setTopMargin(0)
            bf.setBottomMargin(pt * 0.9)
        else:
            bf.setLineHeight(140, _PROPORTIONAL)
            bf.setTopMargin(pt * 0.1)
            bf.setBottomMargin(pt * 0.1)

    if quote:
        cf = QTextCharFormat()
        cf.setForeground(style.muted)
        cur.mergeCharFormat(cf)
        bf.setLeftMargin(pt * 1.6 * quote)
        quotes.append((block, quote))

    cur.setBlockFormat(bf)


def _size_heading(block: QTextBlock, size: float, colour: QColor | None) -> None:
    """Set a heading's size, fragment by fragment.

    Qt's importer sizes headings with FontSizeAdjustment, which Qt applies
    after any point size, so the property has to go rather than be zeroed
    (zero means "normal size"). mergeCharFormat can't remove a property,
    hence a setCharFormat per fragment, which also keeps inline code and
    emphasis inside the heading.
    """
    edits = []
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        fmt = frag.charFormat()
        fmt.clearProperty(QTextFormat.FontSizeAdjustment)
        fmt.setFontPointSize(size)
        fmt.setFontWeight(QFont.DemiBold)
        if colour is not None:
            fmt.setForeground(colour)
        edits.append((frag.position(), frag.length(), fmt))
        it += 1
    cur = QTextCursor(block)
    for pos, length, fmt in edits:
        cur.setPosition(pos)
        cur.setPosition(pos + length, QTextCursor.KeepAnchor)
        cur.setCharFormat(fmt)


def _style_code_run(first: QTextBlock, style: PreviewStyle, pt: float) -> QTextBlock:
    """Style one code block (a run of code lines). Returns the block after it.

    The lines move into a frame, which gives the block one continuous
    background with padding around the code; a background on each line
    leaves stripes between them.
    """
    language = str(first.blockFormat().property(QTextFormat.BlockCodeLanguage) or "")
    last = first
    while last.next().isValid() and _is_code(last.next()):
        last = last.next()

    frame_fmt = QTextFrameFormat()
    frame_fmt.setBackground(style.code_bg)
    frame_fmt.setBorder(0)
    frame_fmt.setPadding(pt * 0.9)
    frame_fmt.setTopMargin(pt * 0.2)
    frame_fmt.setBottomMargin(pt * 1.0)
    cur = QTextCursor(first)
    cur.setPosition(last.position() + last.length() - 1, QTextCursor.KeepAnchor)
    frame = cur.insertFrame(frame_fmt)

    blocks = []
    block = frame.firstCursorPosition().block()
    end = frame.lastCursorPosition().block()
    while block.isValid():
        blocks.append(block)
        if block == end:
            break
        block = block.next()

    for b in blocks:
        bf = QTextBlockFormat(b.blockFormat())
        # The frame's first line comes out of insertFrame without the
        # code marker, and the inline-code pass would then box its tokens.
        bf.setProperty(QTextFormat.BlockCodeLanguage, language)
        bf.setLeftMargin(0)
        bf.setTopMargin(0)
        bf.setBottomMargin(0)
        bf.setLineHeight(125, _PROPORTIONAL)
        bf.setNonBreakableLines(True)
        cur = _block_cursor(b)
        cur.setBlockFormat(bf)
        cf = QTextCharFormat()
        cf.setFontFamilies(style.code_font.families())
        cf.setFontFixedPitch(True)
        cf.setFontPointSize(pt * 0.92)
        cf.setForeground(style.text)
        cur.mergeCharFormat(cf)

    _highlight(blocks, language, style)

    # insertFrame leaves an empty paragraph on each side of the frame,
    # each a line tall. Squash them; the frame's margins do the spacing.
    before = blocks[0].previous()
    after = blocks[-1].next()
    for spacer in (before, after):
        if spacer.isValid() and spacer.length() == 1:
            _collapse(spacer)
    return after.next() if after.isValid() and after.length() == 1 else after


def _collapse(block: QTextBlock) -> None:
    """Shrink an empty paragraph to a couple of pixels."""
    bf = QTextBlockFormat()
    bf.setLineHeight(0, _FIXED)
    cur = QTextCursor(block)
    cur.setBlockFormat(bf)
    cf = QTextCharFormat()
    cf.setFontPointSize(1)
    cur.setBlockCharFormat(cf)


def _highlight(blocks: list[QTextBlock], language: str, style: PreviewStyle) -> None:
    if get_lexer_by_name is None or not language or not blocks:
        return
    try:
        # stripnl/ensurenl off, so token offsets line up with the document.
        lexer = get_lexer_by_name(language.split()[0], stripnl=False, ensurenl=False)
    except ClassNotFound:
        return
    colours = _DARK_TOKENS if style.dark else _LIGHT_TOKENS
    code = "\n".join(b.text() for b in blocks)
    start = blocks[0].position()
    cur = QTextCursor(blocks[0].document())
    offset = 0
    for token, value in lexer.get_tokens(code):
        colour = _token_colour(token, colours)
        if colour is not None and value.strip():
            cf = QTextCharFormat()
            cf.setForeground(QColor(colour))
            if token in Token.Comment:
                cf.setFontItalic(True)
            cur.setPosition(start + offset)
            cur.setPosition(start + offset + len(value), QTextCursor.KeepAnchor)
            cur.mergeCharFormat(cf)
        offset += len(value)


def _token_colour(token, colours: dict[str, str]) -> str | None:
    """The colour for `token`, falling back through its parent types."""
    while token is not None:
        name = ".".join(token)
        if name in colours:
            return colours[name]
        token = token.parent
    return None


def _style_inline(
    doc: QTextDocument, style: PreviewStyle, pt: float, base_dir: str | None, max_image_width: int
) -> None:
    """Inline code, links and oversized images, fragment by fragment."""
    edits: list[tuple[int, int, QTextCharFormat, bool]] = []
    block = doc.begin()
    while block.isValid():
        if not _is_code(block):
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isImageFormat():
                    img = _fitted_image(fmt.toImageFormat(), base_dir, max_image_width)
                    if img is not None:
                        edits.append((frag.position(), frag.length(), img, True))
                elif fmt.isAnchor():
                    cf = QTextCharFormat()
                    cf.setForeground(style.link)
                    cf.setFontUnderline(False)
                    edits.append((frag.position(), frag.length(), cf, False))
                elif fmt.fontFixedPitch():
                    cf = QTextCharFormat()
                    cf.setFontFamilies(style.code_font.families())
                    cf.setFontPointSize(max(1.0, (fmt.fontPointSize() or pt) * 0.92))
                    cf.setBackground(style.code_bg)
                    edits.append((frag.position(), frag.length(), cf, False))
                it += 1
        block = block.next()

    # Applied after the walk: changing formats splits fragments, which
    # would upset an iterator still walking them.
    cur = QTextCursor(doc)
    for pos, length, fmt, replace in edits:
        cur.setPosition(pos)
        cur.setPosition(pos + length, QTextCursor.KeepAnchor)
        if replace:
            cur.setCharFormat(fmt)
        else:
            cur.mergeCharFormat(fmt)


def _fitted_image(fmt, base_dir: str | None, max_width: int):
    """A copy of image format `fmt` scaled to fit `max_width`, or None if it fits."""
    if max_width <= 0:
        return None
    url = QUrl(fmt.name())
    if url.isRelative() and base_dir:
        path = os.path.join(base_dir, url.path())
    elif url.isLocalFile():
        path = url.toLocalFile()
    else:
        return None
    size = QImageReader(path).size()
    width = fmt.width() or size.width()
    if not size.isValid() or width <= max_width:
        return None
    fitted = type(fmt)(fmt)
    height = fmt.height() or size.height() * width / size.width()
    fitted.setWidth(max_width)
    fitted.setHeight(height * max_width / width)
    return fitted


def _tables(doc: QTextDocument) -> list[QTextTable]:
    found = []
    stack = [doc.rootFrame()]
    while stack:
        frame = stack.pop()
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                found.append(child)
            stack.append(child)
    return found


def _style_table(table: QTextTable, style: PreviewStyle) -> None:
    fmt = table.format()
    fmt.setBorder(1)
    fmt.setBorderBrush(style.rule)
    fmt.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
    fmt.setBorderCollapse(True)
    fmt.setCellSpacing(0)
    fmt.setCellPadding(6)
    fmt.setBottomMargin(12)
    table.setFormat(fmt)

    # Qt's importer opens the first cell with an empty paragraph, which
    # doubles the header row's height. Join it to the cell's text.
    first = table.cellAt(0, 0)
    head = first.firstCursorPosition().block()
    if head.length() == 1 and head != first.lastCursorPosition().block():
        QTextCursor(head).deleteChar()

    bold = QTextCharFormat()
    bold.setFontWeight(QFont.DemiBold)
    for col in range(table.columns()):
        cell = table.cellAt(0, col)
        cur = cell.firstCursorPosition()
        cur.setPosition(cell.lastCursorPosition().position(), QTextCursor.KeepAnchor)
        cur.mergeCharFormat(bold)
