import json
from datetime import datetime

from api.database import SessionLocal
from api.models_db import Project, Upload, WarningGroup


def test_upload_handoff_defaults_and_warning_group_roundtrip():
    with SessionLocal() as db:
        project = Project(title="p")
        db.add(project)
        db.flush()
        old = Upload(project_id=project.id, filename="a.csv", encrypted_path="x")
        db.add(old)
        db.flush()
        assert (old.handoff_md, old.handoff_steps, old.handoff_revision) == (None, "[]", 0)
        assert (old.handoff_revisions, old.handoff_status) == ("[]", "none")
        assert old.dictionary_checksum_sha256 == ""

        new = Upload(
            project_id=project.id, filename="b.csv", encrypted_path="y",
            handoff_md="# Handoff", handoff_steps=json.dumps([{"op": "drop_rows"}]),
            handoff_revision=2, handoff_status="current", handoff_updated_at=datetime.utcnow(),
            handoff_source_upload_id=old.id, dictionary_checksum_sha256="ab" * 32,
        )
        db.add(new)
        db.flush()
        group = WarningGroup(
            project_id=project.id, upload_id=new.id,
            flag_ids=json.dumps(["missing_values:age"]), action="clarify",
        )
        db.add(group)
        db.commit()
        db.refresh(group)
        assert group.status == "open"
        assert group.advisor_turns == "[]"
        assert group.pending_proposal is None
        assert json.loads(group.flag_ids) == ["missing_values:age"]
        assert group.created_at is not None and group.updated_at is not None
        assert new.handoff_source_upload_id == old.id
