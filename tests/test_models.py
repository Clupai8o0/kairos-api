from kairos.models.project import Project
from kairos.models.task import Task


def test_task_metadata_column_name_is_preserved() -> None:
    assert "metadata" in Task.__table__.c
    assert "metadata_json" not in Task.__table__.c


def test_project_metadata_column_name_is_preserved() -> None:
    assert "metadata" in Project.__table__.c
    assert "metadata_json" not in Project.__table__.c
