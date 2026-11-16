import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_phone.core.act import ledger


@pytest.fixture(autouse=True)
def no_spend_leaks_between_tests():
    """The ledger keeps this process's unrefunded spends in one list. A test that spends must not
    make a later test look like a process that may have sent input."""
    yield
    ledger.UNREFUNDED.clear()


@pytest.fixture
def short_root() -> Iterator[Path]:
    """A state root whose path is short. The control socket of ssh lives under it, and pytest's own
    temporary folders are longer than a socket path may be (R1-14)."""
    root = Path(tempfile.mkdtemp(prefix="ap-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)
