from pathlib import Path


def test_initial_migration_exists() -> None:
    versions_dir = Path("migrations/versions")
    revision_files = [
        p for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    ]

    assert revision_files, "Expected at least one Alembic revision file"


def test_initial_migration_has_create_tables() -> None:
    versions_dir = Path("migrations/versions")
    revision_files = sorted(
        p for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    latest = revision_files[-1]
    content = latest.read_text(encoding="utf-8")

    assert "initial schema" in content
    assert "op.create_table('tasks'" in content
    assert "op.create_table('projects'" in content
    assert "op.create_table('users'" in content
