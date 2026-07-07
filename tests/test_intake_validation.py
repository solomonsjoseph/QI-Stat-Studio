from api.database import SessionLocal
from api.models_db import IntakeAnswer


def _register(client, email="owner@example.com"):
    response = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()


def _project(client):
    response = client.post("/projects", json={"title": "Intake", "description": ""})
    assert response.status_code == 200, response.text
    return response.json()


def test_intake_rejects_unknown_keys_and_invalid_options(client):
    _register(client)
    project = _project(client)

    unknown = client.post(f"/intake/{project['id']}", json={"answers": {"q99": "bad"}})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["field_errors"]["answers.q99"] == ["Unknown intake question"]

    invalid = client.post(f"/intake/{project['id']}", json={"answers": {"q2": "totally invalid"}})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["field_errors"]["answers.q2"] == ["Invalid option"]


def test_intake_validates_q6_q7_q10_and_sets_unsure(client):
    _register(client)
    project = _project(client)

    bad_number = client.post(f"/intake/{project['id']}", json={"answers": {"q6": -1}})
    assert bad_number.status_code == 422
    assert bad_number.json()["error"]["field_errors"]["answers.q6"] == ["Must be an integer greater than or equal to 0"]

    bad_q7 = client.post(f"/intake/{project['id']}", json={"answers": {"q7": {"date": "07/01/2026"}}})
    assert bad_q7.status_code == 422
    assert bad_q7.json()["error"]["field_errors"]["answers.q7"] == ["Must include optional description and YYYY-MM-DD date"]

    bad_q10 = client.post(f"/intake/{project['id']}", json={"answers": {"q10": {"email": "not-an-email"}}})
    assert bad_q10.status_code == 422
    assert bad_q10.json()["error"]["field_errors"]["answers.q10"] == ["Must include optional email and YYYY-MM-DD deadline"]

    saved = client.post(f"/intake/{project['id']}", json={"answers": {"q3": "I'm not sure", "q6": "0"}})
    assert saved.status_code == 200, saved.text

    with SessionLocal() as db:
        q3 = db.query(IntakeAnswer).filter_by(project_id=project["id"], question_key="q3").one()
        q6 = db.query(IntakeAnswer).filter_by(project_id=project["id"], question_key="q6").one()
        assert q3.is_unsure is True
        assert q6.is_unsure is False


def test_intake_normalizes_short_labels_and_enforces_skip_rule(client):
    _register(client)
    project = _project(client)

    response = client.post(
        f"/intake/{project['id']}",
        json={
            "answers": {
                "q2": "percent",
                "q3": "no",
                "q7": {"description": "Intervention", "date": "2026-01-01"},
                "q8": "Same unit pre vs. post",
            }
        },
    )
    assert response.status_code == 200, response.text

    answers = client.get(f"/intake/{project['id']}").json()["answers"]
    assert answers["q2"] == "A percentage or proportion (percent of patients screened)"
    assert answers["q3"] == "No — I'm just describing one time period"
    assert "q7" not in answers
    assert "q8" not in answers


def test_ai_intake_prefill_redacts_phi_and_normalizes_short_labels(client, monkeypatch):
    _register(client)
    project = _project(client)

    from api.config import settings
    import api.routers.ai as ai_router

    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"q2":"rate","q3":"before-after","q4":"Tracking over time (months, weeks, days)","q5":"Monthly","q6":"12","q7":{"description":"Started checklist","date":"2026-01-15"},"q8":"ignored"}'
                        }
                    }
                ]
            }

    monkeypatch.setattr(ai_router.httpx, "post", lambda *args, **kwargs: FakeResponse())

    response = client.post(
        "/ai/intake-prefill",
        json={"project_id": project["id"], "description": "Patient test@example.com needs monthly tracking."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["phi_redacted"] is True
    assert body["redaction_count"] >= 1
    assert body["answers"] == {
        "q2": "A rate of events over time (infections per 1,000 catheter-days)",
        "q3": "Yes — before and after an intervention",
        "q4": "Tracking over time (months, weeks, days)",
        "q5": "Monthly",
        "q6": 12,
        "q7": {"description": "Started checklist", "date": "2026-01-15"},
    }
