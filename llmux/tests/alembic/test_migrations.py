import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url


@pytest.mark.anyio
async def test_migrations_upgrade_empty_schema(test_engine):
    project_root = Path(__file__).resolve().parents[2]
    schema = f"migration_test_{uuid4().hex}"
    url = make_url(os.environ["DATABASE_URL"]).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )

    async with test_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    try:
        environment = os.environ.copy()
        environment["DATABASE_URL"] = url.render_as_string(
            hide_password=False
        ).replace("%", "%%")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        async with test_engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": schema},
                )
            )
        assert tables == {
            "alembic_version",
            "conversations",
            "ingress_logs",
            "job_records",
        }
    finally:
        async with test_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
