"""The trace of a batch is a private JSONL file that grows one line at a time, so a crash leaves the
steps before it, and it never holds the text a step typed."""

import json
import os
import stat

import pytest
from fakes import J7_SERIAL

from agent_phone.cli.args import parse_args
from agent_phone.cli.trace import Trace, redacted


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_a_trace_is_a_0600_file_in_the_devices_own_0700_folder(tmp_path):
    with Trace.open(tmp_path, J7_SERIAL) as trace:
        assert trace.path.parent == tmp_path / "traces" / J7_SERIAL
        assert trace.path.name.endswith("-batch.jsonl") and mode(trace.path) == 0o600
    assert mode(tmp_path / "traces") == 0o700 and mode(trace.path.parent) == 0o700


def test_a_folder_that_exists_with_wider_rights_is_closed_again(tmp_path):
    folder = tmp_path / "traces" / J7_SERIAL
    folder.mkdir(parents=True)
    os.chmod(tmp_path / "traces", 0o755)
    os.chmod(folder, 0o755)
    with Trace.open(tmp_path, J7_SERIAL):
        pass
    assert mode(tmp_path / "traces") == 0o700 and mode(folder) == 0o700


def test_every_line_is_on_disk_before_the_next_step_starts(tmp_path):
    trace = Trace.open(tmp_path, J7_SERIAL)
    trace.append({"line": "step", "i": 0})
    trace.append({"line": "step", "i": 1})
    lines = trace.path.read_text().splitlines()
    assert [json.loads(line) for line in lines] == [{"line": "step", "i": 0}, {"line": "step", "i": 1}]
    trace.close()


def test_two_traces_never_share_a_file(tmp_path):
    with (
        Trace.open(tmp_path, J7_SERIAL) as first,
        Trace.open(tmp_path, J7_SERIAL) as second,
    ):
        assert first.path != second.path


@pytest.mark.parametrize(
    ("argv", "shown"),
    [
        (["set-text", "role=field", "hunter2"], ["set-text", "role=field", "<7 chars>"]),
        (
            ["set-text", "role=field", "hunter2", "--wait-for", "role=field"],
            ["set-text", "role=field", "<7 chars>", "--wait-for", "role=field"],
        ),
        (["set-text", "@k3x9q:e3", "héllo wörld"], ["set-text", "@k3x9q:e3", "<11 chars>"]),
        (["set-text", "@k3x9q:e3", ""], ["set-text", "@k3x9q:e3", "<0 chars>"]),
        (["clipboard", "set", "a secret"], ["clipboard", "set", "<8 chars>"]),
        (["click", "name=hunter2"], ["click", "name=hunter2"]),
        (["clipboard", "get"], ["clipboard", "get"]),
    ],
)
def test_the_text_of_set_text_and_clipboard_set_is_replaced_by_its_length(argv, shown):
    assert redacted(argv, parse_args(argv).command) == shown


@pytest.mark.parametrize(
    ("argv", "shown"),
    [
        (
            ["set-text", "role=field", "hunter2", "--wait-for", "value=hunter2"],
            ["set-text", "role=field", "<7 chars>", "--wait-for", "value=<7 chars>"],
        ),
        (
            ["set-text", "role=field", "hunter2", "--wait-for=value=hunter2"],
            ["set-text", "role=field", "<7 chars>", "--wait-for=value=<7 chars>"],
        ),
        (
            ["set-text", "@k3x9q:e3", "it", "--wait-for", "name*=it", "--timeout-ms", "900"],
            ["set-text", "@k3x9q:e3", "<2 chars>", "--wait-for", "name*=<2 chars>", "--timeout-ms", "900"],
        ),
    ],
    ids=["in-a-query", "in-a-flag-value", "a-short-text-leaves-the-flag-names"],
)
def test_the_typed_text_is_redacted_inside_every_word_that_holds_it(argv, shown):
    assert redacted(argv, parse_args(argv).command) == shown
