import pytest

from agent_phone.core.act import ledger


@pytest.fixture(autouse=True)
def no_spend_leaks_between_tests():
    """The ledger keeps this process's unrefunded spends in one list. A test that spends must not
    make a later test look like a process that may have sent input."""
    yield
    ledger.UNREFUNDED.clear()
