from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QFont, QImage, QTextDocument, QTextFormat, QTextTable

from kami.ui.markdown import PreviewStyle, render_markdown

CODE_BG = QColor(1, 2, 3)
LINK = QColor("#3794ff")


@pytest.fixture
def style(qapp) -> PreviewStyle:
    body = QFont("Sans")
    body.setPointSizeF(10)
    code = QFont("Monospace")
    code.setPointSizeF(10)
    return PreviewStyle(
        body_font=body, code_font=code, text=QColor("white"), muted=QColor("gray"),
        rule=QColor("gray"), code_bg=CODE_BG, link=LINK, dark=True,
    )


def fragments(doc: QTextDocument):
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            yield it.fragment(), block
            it += 1
        block = block.next()


def by_text(doc: QTextDocument) -> dict:
    return {frag.text(): (frag.charFormat(), block) for frag, block in fragments(doc)}


def test_text_after_something_tag_like_is_kept(style):
    doc = QTextDocument()
    render_markdown(
        doc, "- into <work dir>/backup/\n- next\n\n## After\n\none<br>two, List<String>\n", style
    )
    shown = doc.toPlainText()
    for text in ("into <work dir>/backup/", "next", "After", "one<br>two, List<String>"):
        assert text in shown


def test_headings_are_scaled_and_ruled(style):
    doc = QTextDocument()
    render_markdown(doc, "# One\n\n## Two\n\n### Three\n", style)
    found = by_text(doc)
    assert found["One"][0].font().pointSizeF() == pytest.approx(20.0)
    assert found["Two"][0].font().pointSizeF() == pytest.approx(15.0)
    assert found["Three"][0].font().pointSizeF() == pytest.approx(12.5)
    ruled = {
        text: block.blockFormat().hasProperty(QTextFormat.BlockTrailingHorizontalRulerWidth)
        for text, (_, block) in found.items()
    }
    assert ruled == {"One": True, "Two": True, "Three": False}


def test_code_block_sits_in_a_shaded_frame(style):
    doc = QTextDocument()
    render_markdown(doc, "Before\n\n```\nline one\nline two\n```\n\nAfter\n", style)
    frames = [f for f in doc.rootFrame().childFrames() if not isinstance(f, QTextTable)]
    assert len(frames) == 1
    assert frames[0].frameFormat().background().color() == CODE_BG
    found = by_text(doc)
    assert found["line one"][0].fontFixedPitch()
    # No inline-code box inside the block itself.
    assert found["line one"][0].background().color() != CODE_BG


def test_code_is_coloured_by_language(style):
    pytest.importorskip("pygments")
    doc = QTextDocument()
    render_markdown(doc, "```python\ndef f():\n    return 1\n```\n", style)
    colours = {frag.text(): frag.charFormat().foreground().color().name() for frag, _ in fragments(doc)}
    assert colours["def"] == "#569cd6"
    assert colours["f"] == "#dcdcaa"


def test_unknown_language_is_left_plain(style):
    doc = QTextDocument()
    render_markdown(doc, "```nosuchlanguage\nx = 1\n```\n", style)
    assert "x = 1" in doc.toPlainText()


def test_inline_code_and_links(style):
    doc = QTextDocument()
    render_markdown(doc, "Use `kami` and [the site](https://jacksonv.com).\n", style)
    found = by_text(doc)
    code_fmt = found["kami"][0]
    assert code_fmt.background().color() == CODE_BG
    link_fmt = found["the site"][0]
    assert link_fmt.isAnchor()
    assert link_fmt.foreground().color() == LINK


def test_table_header_row(style):
    doc = QTextDocument()
    render_markdown(doc, "| Client | Plan |\n|---|---|\n| Team110 | SEO |\n", style)
    [table] = [f for f in doc.rootFrame().childFrames() if isinstance(f, QTextTable)]
    cell = table.cellAt(0, 0)
    # Qt's importer opens the first cell with an empty paragraph.
    assert cell.firstCursorPosition().block() == cell.lastCursorPosition().block()
    assert cell.firstCursorPosition().block().text() == "Client"
    assert by_text(doc)["Client"][0].fontWeight() >= QFont.DemiBold


def test_quotes_are_reported_for_their_bars(style):
    doc = QTextDocument()
    quotes = render_markdown(doc, "> outer\n>\n> > inner\n", style)
    assert sorted(level for _, level in quotes) == [1, 2]


def test_wide_images_are_fitted(style, tmp_path):
    img = QImage(400, 100, QImage.Format_RGB32)
    img.fill(QColor("red"))
    img.save(str(tmp_path / "wide.png"))
    doc = QTextDocument()
    render_markdown(doc, "![wide](wide.png)\n", style, base_dir=str(tmp_path), max_image_width=200)
    [image] = [f.charFormat().toImageFormat() for f, _ in fragments(doc) if f.charFormat().isImageFormat()]
    assert image.width() == pytest.approx(200)
    assert image.height() == pytest.approx(50)
