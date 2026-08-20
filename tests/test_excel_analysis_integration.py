import io

import pandas as pd
import xlwt


def _xls_bytes(df: pd.DataFrame) -> bytes:
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Sheet1")
    for col_idx, column in enumerate(df.columns):
        sheet.write(0, col_idx, column)
    for row_idx, row in enumerate(df.itertuples(index=False), start=1):
        for col_idx, value in enumerate(row):
            sheet.write(row_idx, col_idx, value)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()



def _project(client):
    response = client.post("/projects", json={"title": "QI", "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_xlsx_and_xls_uploads_can_be_reloaded_for_analysis(auth_client):
    project_id = _project(auth_client)
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]),
            "value": [10, 12, 11, 15],
        }
    )
    workbook = io.BytesIO()
    df.to_excel(workbook, index=False)
    workbook.seek(0)

    cases = [
        (
            "measures.xlsx",
            workbook.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "measures.xls",
            _xls_bytes(pd.DataFrame({"date": ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"], "value": [10, 12, 11, 15]})),
            "application/vnd.ms-excel",
        ),
    ]

    for filename, raw, content_type in cases:
        upload = auth_client.post(
            f"/upload/{project_id}",
            files={
                "file": (filename, raw, content_type),
                "dictionary": ("dictionary.txt", b"date: measurement date. value: measured outcome.", "text/plain"),
            },
        )
        assert upload.status_code == 200, upload.text
        upload_id = upload.json()["upload_id"]

        analysis = auth_client.post(
            "/analyze/run",
            json={
                "project_id": project_id,
                "upload_id": upload_id,
                "template": "run_chart",
                "parameters": {"date_col": "date", "value_col": "value"},
            },
        )

        assert analysis.status_code == 200, analysis.text
        assert analysis.json()["run_id"]
