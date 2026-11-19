"""📘 1단계 파싱: PDF를 Unstructured '요소(Element)' 목록으로 바꿉니다.

요소 = Title, NarrativeText, ListItem, Table, Header, Footer … 처럼 '종류(category)'가 붙은 글 조각.
파싱 방법(strategy)
- fast     : PDF 안의 글자 층을 읽음. 01·09 정책 PDF는 표 칸 좌표로 행 관계를 추가 복원함
- hi_res   : 레이아웃 모델로 페이지를 봄. 표 구조(text_as_html)를 얻을 수 있음. 느리고 첫 실행 때 모델을 내려받음
- ocr_only : 이미지에서 글자를 인식 (스캔본용, Tesseract 필요)
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from html import escape
from pathlib import Path

from ..config import settings


def iter_pdfs(root: str | Path | None = None):
    for p in sorted(Path(root or settings.kb_pdf_dir).glob("*.pdf")):
        yield p


def parse_pdf(path: str | Path, strategy: str | None = None) -> list:
    """PDF 하나를 요소 목록으로."""
    from unstructured.partition.auto import partition

    strategy = strategy or settings.parse_strategy
    elements = partition(
        filename=str(path),
        strategy=strategy,
        languages=["kor", "eng"],
        infer_table_structure=True,
    )
    if strategy == "fast" and not any((element.text or "").strip() for element in elements):
        logging.getLogger(__name__).warning(
            "fast parsing returned no text; retrying with OCR: %s", Path(path).name
        )
        strategy = "ocr_only"
        elements = partition(
            filename=str(path),
            strategy=strategy,
            languages=["kor", "eng"],
            infer_table_structure=True,
        )
    pdf = Path(path)
    if strategy == "fast" and pdf.name.startswith(("01_", "09_")):
        return _restore_policy_tables(pdf, elements)
    return elements


def _cell_text(value: str | None) -> str:
    # In these PDFs, a newline inside a narrow cell usually splits one word.
    return re.sub(r"\s+", " ", (value or "").replace("\n", "")).strip()


def _edges(values: list[float]) -> list[float]:
    edges: list[float] = []
    for value in sorted(values):
        if not edges or value - edges[-1] > 1:
            edges.append(value)
    return edges


def _table_grid(page, table) -> tuple[list[list[str]], list[float]]:
    """Expand merged PDF cells into a rectangular grid using their bounding boxes."""
    cells = {}
    for row, values in zip(table.rows, table.extract()):
        for box, value in zip(row.cells, values):
            if box is not None:
                cells[box] = _cell_text(value)

    xs = _edges([x for box in cells for x in (box[0], box[2])])
    ys = _edges([y for box in cells for y in (box[1], box[3])])
    grid: list[list[str]] = []
    for top, bottom in zip(ys, ys[1:]):
        row = []
        for left, right in zip(xs, xs[1:]):
            cx, cy = (left + right) / 2, (top + bottom) / 2
            value = next(
                (text for (x0, y0, x1, y1), text in cells.items() if x0 < cx < x1 and y0 < cy < y1),
                None,
            )
            if value is None:
                # A cell at a page boundary may contain text without a closed box.
                value = _cell_text(page.crop((left + 1, top + 1, right - 1, bottom - 1)).extract_text())
            row.append(value)
        grid.append(row)
    return grid, ys


def _row_element(fields: list[tuple[str, str]], page_number: int):
    from unstructured.documents.elements import ElementMetadata, Table

    text = " | ".join(f"{key}: {value}" for key, value in fields)
    html = "<table><tbody>" + "".join(
        f"<tr><th>{escape(key)}</th><td>{escape(value)}</td></tr>" for key, value in fields
    ) + "</tbody></table>"
    return Table(text=text, metadata=ElementMetadata(page_number=page_number, text_as_html=html))


def _borderless_rate_rows(page, page_number: int):
    """Read the fixed-width, borderless false-positive table on policy PDF 09 p.3."""
    columns = (67, 119, 277, 338, 399, 460, 545)
    headers = ("룰ID", "룰 이름", "8월", "9월", "10월", "3개월 평균")
    words = page.extract_words()
    anchors = [
        word for word in words
        if re.fullmatch(r"R\d{3}", word["text"])
        or (word["text"] == "전체" and 119 < word["x0"] < 277)
    ]
    rows = []
    for word in sorted(anchors, key=lambda item: item["top"]):
        top, bottom = word["top"] - 4, word["bottom"] + 5
        values = [
            _cell_text(page.crop((left, top, right, bottom)).extract_text())
            for left, right in zip(columns, columns[1:])
        ]
        rows.append((top, _row_element(list(zip(headers, values)), page_number)))
    return rows


def _restore_policy_tables(path: Path, elements: list) -> list:
    """Replace scattered fast text with source-text rows for the two policy PDFs."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError("표 복원을 위해 'pip install pdfplumber>=0.11,<0.12'가 필요합니다") from exc

    replacements: list[tuple[int, float, object]] = []
    table_boxes: dict[int, list[tuple[float, float, float, float]]] = defaultdict(list)
    previous_contact: list[str] | None = None
    footnotes = {}
    for element in elements:
        if not element.text.startswith("※"):
            continue
        for marker, note in re.findall(r"(※\d)\s*(.*?)(?=※\d|$)", element.text, re.DOTALL):
            footnotes[marker] = _cell_text(note)

    def with_notes(fields: list[tuple[str, str]]) -> list[tuple[str, str]]:
        markers = {marker for _, value in fields for marker in re.findall(r"※\d", value)}
        return fields + [("각주", f"{marker} {footnotes[marker]}") for marker in sorted(markers) if marker in footnotes]

    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            for table in page.find_tables():
                grid, tops = _table_grid(page, table)
                if len(grid) < 2:
                    continue
                table_boxes[page_number].append(table.bbox)

                if path.name.startswith("01_"):
                    headers = grid[0]
                    for index, values in enumerate(grid[1:], 1):
                        replacements.append((page_number, tops[index], _row_element(with_notes(list(zip(headers, values))), page_number)))
                elif grid[0][0] == "자산 등급":
                    for index, values in enumerate(grid[2:], 2):
                        for column in range(2, len(values)):
                            fields = [
                                ("자산 등급", values[0]), ("조치", values[1]),
                                ("심각도", grid[0][column]), ("시간대", grid[1][column]),
                                ("승인권자", values[column]),
                            ]
                            replacements.append((page_number, tops[index], _row_element(with_notes(fields), page_number)))
                elif grid[0][0] == "심각도":
                    for index, current in enumerate(grid[1:], 1):
                        values = current[:]
                        if not values[0] and previous_contact:
                            values[0] = previous_contact[0]
                        for column in range(2, len(values)):
                            if values[column] == "〃" and previous_contact:
                                values[column] = previous_contact[column]
                        replacements.append((page_number, tops[index], _row_element(with_notes(list(zip(grid[0], values))), page_number)))
                        previous_contact = values
                else:
                    headers = grid[0]
                    for index, values in enumerate(grid[1:], 1):
                        replacements.append((page_number, tops[index], _row_element(with_notes(list(zip(headers, values))), page_number)))

            if path.name.startswith("09_") and page_number == 3:
                borderless = _borderless_rate_rows(page, page_number)
                if borderless:
                    table_boxes[page_number].append((67, 110, 545, 258))
                    replacements.extend((page_number, top, element) for top, element in borderless)

    ordered = []
    for element in elements:
        page_number = element.metadata.page_number
        points = getattr(getattr(element.metadata, "coordinates", None), "points", None)
        if points:
            cx = (min(x for x, _ in points) + max(x for x, _ in points)) / 2
            cy = (min(y for _, y in points) + max(y for _, y in points)) / 2
            if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in table_boxes[page_number]):
                continue
            top = min(y for _, y in points)
        else:
            top = float("inf")
        ordered.append((page_number, top, element))
    ordered.extend(replacements)
    return [element for _, _, element in sorted(ordered, key=lambda item: (item[0], item[1]))]


def drop_header_footer(elements: list) -> list:
    """페이지마다 반복되는 머리말·꼬리말("대외비" 등)을 걸러냅니다. 03번 PDF로 확인하세요."""
    pages_by_text: dict[tuple[str, str], set[int | None]] = defaultdict(set)
    for element in elements:
        if element.category in {"Header", "Footer"}:
            key = (element.category, (element.text or "").strip())
            pages_by_text[key].add(element.metadata.page_number)

    repeated = {key for key, pages in pages_by_text.items() if len(pages) > 1}
    return [
        element
        for element in elements
        if (element.category, (element.text or "").strip()) not in repeated
    ]
