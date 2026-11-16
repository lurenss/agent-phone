"""Phones plugged into another computer, reached over ssh.

`remote_hub` is the only name another package may import from here. `tests/test_architecture.py`
fails on an import of any module below this one from outside it.
"""

from agent_phone.adapters.remote.hub import remote_hub

__all__ = ["remote_hub"]
