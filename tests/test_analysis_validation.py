import json

from api.database import SessionLocal
from api.models_db import AnalysisRun


def _project(client):
    response = client.post("/projects", json={"title": "QI", "description": "desc"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _upload_csv(client, project_id, content, filename="data.csv"):
    resp = client.post(
        f"/upload/{project_id}",
        files={
            "file": (filename, content, "text/csv"),
            "dictionary": ("dictionary.txt", b"value: measured outcome.", "text/plain"),
        },
    )
    from tests.helpers import advance_to_phase
    advance_to_phase(project_id, "plan")
    return resp


def _run(client, project_id, upload_id, template, parameters):
    return client.post(
        "/analyze/run",
        json={"project_id": project_id, "upload_id": upload_id, "template": template, "parameters": parameters},
    )


def test_analysis_rejects_missing_params_with_field_errors(auth_client):
    project_id = _project(auth_client)
    uploaded = _upload_csv(auth_client, project_id, b"date,value\n2024-01-01,1\n2024-02-01,2\n")
    assert uploaded.status_code == 200, uploaded.text

    response = _run(auth_client, project_id, uploaded.json()["upload_id"], "run_chart", {"date_col": "date"})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["message"] == "Invalid analysis parameters"
    assert "value_col" in error["field_errors"]


def test_analysis_rejects_unknown_columns_with_field_errors(auth_client):
    project_id = _project(auth_client)
    uploaded = _upload_csv(auth_client, project_id, b"date,value\n2024-01-01,1\n2024-02-01,2\n")
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "run_chart",
        {"date_col": "date", "value_col": "missing_value"},
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["message"] == "Invalid analysis parameters"
    assert error["field_errors"] == {"value_col": ["Column 'missing_value' does not exist in the uploaded dataset"]}


def test_descriptive_value_cols_comma_string_is_validated_and_persisted(auth_client):
    project_id = _project(auth_client)
    uploaded = _upload_csv(auth_client, project_id, b"site,a,b\nA,1,10\nA,2,20\nB,3,30\n")
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "descriptive_summary",
        {"group_col": "site", "value_cols": "a, b"},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        run = db.query(AnalysisRun).one()
        assert run.upload_id == uploaded.json()["upload_id"]
        assert run.created_at is not None
        assert json.loads(run.parameters) == {"group_col": "site", "value_cols": ["a", "b"]}
        assert "figure_base64" in json.loads(run.result_json)


def test_upload_project_mismatch_is_rejected(auth_client):
    first_project = _project(auth_client)
    second_project = _project(auth_client)
    uploaded = _upload_csv(auth_client, first_project, b"date,value\n2024-01-01,1\n2024-02-01,2\n")
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        second_project,
        uploaded.json()["upload_id"],
        "run_chart",
        {"date_col": "date", "value_col": "value"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Upload does not belong to project"


def test_p_chart_below_12_points_downgrades_to_run_chart(auth_client):
    project_id = _project(auth_client)
    rows = "date,outcome\n" + "".join(f"2024-{month:02d}-01,{month % 2}\n" for month in range(1, 7))
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "p_chart",
        {"date_col": "date", "numerator_col": "outcome", "freq": "MS"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["methods"].startswith(
        "A run chart was used rather than a control chart because six time points were available"
    )
    with SessionLocal() as db:
        run = db.query(AnalysisRun).filter(AnalysisRun.id == result["run_id"]).one()
        assert run.template == "run_chart"


def test_p_chart_with_12_or_more_points_has_no_downgrade(auth_client):
    project_id = _project(auth_client)
    rows = "date,outcome\n" + "".join(f"2024-{month:02d}-01,{month % 2}\n" for month in range(1, 13))
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "p_chart",
        {"date_col": "date", "numerator_col": "outcome", "freq": "MS"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert "run chart was used" not in result["methods"]
    with SessionLocal() as db:
        run = db.query(AnalysisRun).filter(AnalysisRun.id == result["run_id"]).one()
        assert run.template == "p_chart"


def test_denominator_columns_must_be_positive(auth_client):
    project_id = _project(auth_client)
    rows = "date,num,denom\n" + "".join(f"2024-{month:02d}-01,1,{0 if month == 3 else 10}\n" for month in range(1, 13))
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "p_chart",
        {"date_col": "date", "numerator_col": "num", "denominator_col": "denom", "freq": "MS"},
    )

    assert response.status_code == 400
    assert "Denominator column 'denom' must contain only positive values" in response.json()["error"]["message"]



def test_run_chart_rejects_unparseable_dates_before_template_execution(auth_client):
    project_id = _project(auth_client)
    uploaded = _upload_csv(
        auth_client,
        project_id,
        b"date,value\n2024-01-01,1\nnot-a-date,2\n2024-03-01,3\n",
    )
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "run_chart",
        {"date_col": "date", "value_col": "value", "freq": "MS"},
    )

    assert response.status_code == 400
    assert "Date column 'date' contains values that cannot be parsed as dates: not-a-date" in response.json()["error"]["message"]


def test_u_chart_rejects_non_numeric_count_before_template_execution(auth_client):
    project_id = _project(auth_client)
    rows = "date,count,denom\n" + "".join(
        f"2024-{month:02d}-01,{'bad' if month == 3 else 1},10\n" for month in range(1, 13)
    )
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "u_c_chart",
        {"date_col": "date", "count_col": "count", "denominator_col": "denom", "freq": "MS"},
    )

    assert response.status_code == 400
    assert "Count column 'count' contains non-numeric values: bad" in response.json()["error"]["message"]


def test_p_chart_rejects_non_binary_numerator_without_denominator(auth_client):
    project_id = _project(auth_client)
    rows = "date,outcome\n" + "".join(f"2024-{month:02d}-01,{2 if month == 3 else month % 2}\n" for month in range(1, 13))
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "p_chart",
        {"date_col": "date", "numerator_col": "outcome", "freq": "MS"},
    )

    assert response.status_code == 400
    assert "only 0/1 values when no denominator column is supplied" in response.json()["error"]["message"]


def test_p_chart_rejects_numerator_exceeding_denominator(auth_client):
    project_id = _project(auth_client)
    rows = "date,num,denom\n" + "".join(f"2024-{month:02d}-01,{15 if month == 3 else 1},10\n" for month in range(1, 13))
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "p_chart",
        {"date_col": "date", "numerator_col": "num", "denominator_col": "denom", "freq": "MS"},
    )

    assert response.status_code == 400
    assert "must not exceed the denominator column 'denom'" in response.json()["error"]["message"]


def test_p_chart_rejects_negative_numerator(auth_client):
    project_id = _project(auth_client)
    rows = "date,num,denom\n" + "".join(f"2024-{month:02d}-01,{-1 if month == 3 else 1},10\n" for month in range(1, 13))
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "p_chart",
        {"date_col": "date", "numerator_col": "num", "denominator_col": "denom", "freq": "MS"},
    )

    assert response.status_code == 400
    assert "Numerator column 'num' must not contain negative values" in response.json()["error"]["message"]


def test_u_c_chart_rejects_negative_count(auth_client):
    project_id = _project(auth_client)
    rows = "date,count\n" + "".join(f"2024-{month:02d}-01,{-2 if month == 3 else 1}\n" for month in range(1, 13))
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "u_c_chart",
        {"date_col": "date", "count_col": "count", "freq": "MS"},
    )

    assert response.status_code == 400
    assert "Count column 'count' must not contain negative values" in response.json()["error"]["message"]

def test_before_after_mean_requires_both_groups_with_two_values(auth_client):
    project_id = _project(auth_client)
    uploaded = _upload_csv(auth_client, project_id, b"period,value\npre,1\npre,2\npre,3\npost,4\n")
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "before_after_mean",
        {"group_col": "period", "value_col": "value", "pre_val": "pre", "post_val": "post"},
    )

    assert response.status_code == 400
    assert "at least 2 non-null values" in response.json()["error"]["message"]


def test_run_chart_returns_trend_and_median_tie_fields(auth_client):
    project_id = _project(auth_client)
    rows = "date,value\n" + "".join(
        [
            "2024-01-01,1\n",
            "2024-02-01,2\n",
            "2024-03-01,3\n",
            "2024-04-01,4\n",
            "2024-05-01,5\n",
            "2024-06-01,6\n",
            "2024-07-01,6\n",
        ]
    )
    uploaded = _upload_csv(auth_client, project_id, rows.encode())
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "run_chart",
        {"date_col": "date", "value_col": "value", "freq": "MS"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trend_signal_detected"] is True
    assert body["max_trend"] == 6
    assert body["median_tie_count"] == 1
    with SessionLocal() as db:
        persisted = json.loads(db.query(AnalysisRun).one().result_json)
        assert persisted["figure_base64"]
        assert persisted["trend_signal_detected"] is True


def test_before_after_pct_rejects_identical_pre_and_post_group(auth_client):
    project_id = _project(auth_client)
    uploaded = _upload_csv(
        auth_client,
        project_id,
        b"period,outcome\nbaseline,1\nbaseline,0\nbaseline,1\nbaseline,0\n",
    )
    assert uploaded.status_code == 200, uploaded.text

    response = _run(
        auth_client,
        project_id,
        uploaded.json()["upload_id"],
        "before_after_pct",
        {"group_col": "period", "outcome_col": "outcome", "pre_val": "baseline", "post_val": "baseline"},
    )

    assert response.status_code == 400, response.text
    assert "Pre group and post group must be different (both were 'baseline')" in response.json()["error"]["message"]