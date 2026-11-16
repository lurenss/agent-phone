"""Which phones this process drives. The one place a hub is built, so `main()` and `open_phone`
cannot choose differently."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from agent_phone.adapters.uiautomator2.adb import SubprocessAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.cli.settings import Settings
from agent_phone.core.phone import PhoneHub
from agent_phone.core.wait.clock import Clock


@contextmanager
def open_hub(settings: Settings, clock: Clock) -> Iterator[PhoneHub]:
    """The phones on this computer's adb. Leaving the block lets go of what the hub holds."""
    yield U2Hub(SubprocessAdb(settings.adb), settings.idle_limit_s, clock)
