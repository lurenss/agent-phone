"""The three screens that `survey.py` reads and `fixtures.py` pins: the launcher, Settings and a
system dialog. The first two fill the display, and the dialog does not."""

from enum import Enum


class Screen(Enum):
    LAUNCHER = "launcher"
    SETTINGS = "settings"
    DIALOG = "dialog"

    @property
    def fills_the_display(self) -> bool:
        return self is not Screen.DIALOG
