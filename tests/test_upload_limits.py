"""Upload hardening (OWASP File Upload Cheat Sheet): size after decompression, row and page caps."""
import io
import os
import zipfile

os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

import pytest
from fastapi import HTTPException

from api import upload_utils


def _zip_with(name: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def test_a_zip_that_expands_far_beyond_its_size_is_refused():
    bomb = _zip_with("xl/worksheets/sheet1.xml", b"0" * (30 * 1024 * 1024))  # 30 MB of zeros, a few KB zipped
    with pytest.raises(HTTPException) as err:
        upload_utils.check_zip_container(bomb, "The spreadsheet")
    assert err.value.status_code == 400 and "unsafe size" in err.value.detail


def test_an_ordinary_small_zip_passes():
    upload_utils.check_zip_container(_zip_with("word/document.xml", b"<w:p>hello</w:p>" * 100), "The data dictionary")


def test_a_file_that_is_not_a_zip_is_refused_as_xlsx():
    with pytest.raises(HTTPException) as err:
        upload_utils._read_dataframe(b"this is not an xlsx", "xlsx")
    assert err.value.status_code == 400


def test_too_many_rows_or_columns_are_refused(monkeypatch):
    monkeypatch.setattr(upload_utils, "MAX_ROWS", 5)
    with pytest.raises(HTTPException) as err:
        upload_utils._read_dataframe(b"a\n" + b"1\n" * 10, "csv")
    assert "more than 5 rows" in err.value.detail
    monkeypatch.setattr(upload_utils, "MAX_COLUMNS", 2)
    with pytest.raises(HTTPException) as err:
        upload_utils._read_dataframe(b"a,b,c\n1,2,3\n", "csv")
    assert "more than 2 columns" in err.value.detail


def test_the_reader_stops_at_the_limit_instead_of_loading_everything():
    import asyncio

    class Chunked:
        def __init__(self, total):
            self.left, self.served = total, 0

        async def read(self, n):
            take = min(n, self.left)
            self.left -= take
            self.served += take
            return b"x" * take

    src = Chunked(10 * 1024 * 1024)
    with pytest.raises(HTTPException):
        asyncio.run(upload_utils.read_capped(src, 2 * 1024 * 1024, "The file"))
    assert src.served <= 3 * 1024 * 1024  # stopped near the limit, did not read the full 10 MB


def test_a_dictionary_pdf_with_too_many_pages_is_refused(monkeypatch):
    import pypdf

    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    monkeypatch.setattr(upload_utils, "MAX_PDF_PAGES", 2)
    with pytest.raises(HTTPException) as err:
        upload_utils.extract_dictionary_text("dictionary.pdf", buf.getvalue())
    assert "more than 2 pages" in err.value.detail
