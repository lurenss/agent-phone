"""Which phones this process drives: the ones on this computer's adb, or a phone host's.

The one place a hub is built, so `main()` and `open_phone` cannot choose differently.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from agent_phone.adapters.remote import remote_hub
from agent_phone.adapters.uiautomator2.adb import Adb, SubprocessAdb
from agent_phone.adapters.uiautomator2.phone import U2Hub
from agent_phone.adapters.uiautomator2.server import SERVER_PORT
from agent_phone.cli.settings import Settings
from agent_phone.core.phone import PhoneHub
from agent_phone.core.wait.clock import Clock


@contextmanager
def open_hub(settings: Settings, clock: Clock, *, task: str, linger: bool) -> Iterator[PhoneHub]:
    def backend(adb: Adb) -> PhoneHub:
        return U2Hub(adb, settings.idle_limit_s, clock)

    local = SubprocessAdb(settings.adb)
    if settings.remote is None:
        yield backend(local)
        return
    with remote_hub(
        settings.remote,
        settings.state_root,
        local,
        backend,
        device_port=SERVER_PORT,
        task=settings.task or task,
        linger=linger,
        wait_s=settings.lock_wait_s,
        clock=clock,
    ) as hub:
        yield hub
