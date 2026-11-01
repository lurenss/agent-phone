"""The command dataclasses a `Driver` runs, grouped as `main()` and the typed `Driver` methods
share them. One command is one frozen dataclass; `Driver.run` is the one dispatch over them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_phone.core.commands.click import ClickCommand
from agent_phone.core.commands.clipboard import ClipboardGetCommand, ClipboardSetCommand
from agent_phone.core.commands.find import FindCommand
from agent_phone.core.commands.get import GetCommand
from agent_phone.core.commands.is_ import IsCommand
from agent_phone.core.commands.launch import LaunchCommand
from agent_phone.core.commands.open_url import OpenUrlCommand
from agent_phone.core.commands.press import PressCommand
from agent_phone.core.commands.rotate import RotateCommand
from agent_phone.core.commands.scroll import ScrollCommand
from agent_phone.core.commands.set_text import SetTextCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.commands.stop import StopCommand

INPUT_TIMEOUT_MS = 5000


@dataclass(frozen=True, slots=True)
class ScreenshotCommand:
    """`path` None writes under the state root, in the device's own folder."""

    path: Path | None = None


InputCommand = (
    ClickCommand
    | SetTextCommand
    | ScrollCommand
    | PressCommand
    | LaunchCommand
    | StopCommand
    | OpenUrlCommand
    | RotateCommand
    | ClipboardGetCommand
    | ClipboardSetCommand
    | ScreenshotCommand
)
DriverCommand = SnapshotCommand | FindCommand | GetCommand | IsCommand | InputCommand
