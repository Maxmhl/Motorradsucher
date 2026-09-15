from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Testdaten in einem temporaeren Verzeichnis - nie im echten data/.
_TMP = Path(tempfile.mkdtemp(prefix="motorradsucher-tests-"))
os.environ.setdefault("DATA_DIR", str(_TMP))
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}")

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load
