#!/usr/bin/env python3
"""What the u2.jar server does for the JSON-RPC input methods agent-phone sends, read from its
bytecode. It touches no phone. androguard is not a project dependency, so run it through uvx and
hand it the jar that ships inside the uiautomator2 package:

    JAR=$(uv run python -c 'import importlib.util as u, pathlib as p; \
print(p.Path(u.find_spec("uiautomator2").submodule_search_locations[0]) / "assets" / "u2.jar")')
    uvx --from androguard==4.1.2 python -I probes/android/jar_rpc.py "$JAR"

It prints the instructions and the exception handlers of each method in METHODS. FINDINGS rows
A2-11 and A2-12 cite its output (`captures/2026-11-01-unit4-jar-rpc.txt`).
"""

import sys
import tempfile
import zipfile
from pathlib import Path

from androguard.core.dex import DEX
from loguru import logger

METHODS = {
    "Lcom/wetest/uia2/stub/AutomatorServiceImpl;": {
        "click",
        "setText",
        "swipe",
        "pressKeyCode",
        "setClipboard",
    },
    "Lcom/wetest/uia2/stub/Selector;": {"toUiObject2", "checkBySelectorNull"},
    "Landroidx/test/uiautomator/UiObject;": {"click", "setText"},
    "Landroidx/test/uiautomator/UiObject2;": {"click"},
}


def show(dex: DEX, method) -> None:
    print(f"== {method.get_class_name()} {method.get_name()} {method.get_descriptor()}")
    code = method.get_code()
    if code is None:
        return
    offset = 0
    for instruction in code.get_bc().get_instructions():
        print(f"   {offset:04x} {instruction.get_name()} {instruction.get_output()}")
        offset += instruction.get_length()
    handlers = code.get_handlers()
    for item in handlers.get_list() if handlers else ():
        for handler in item.get_handlers():
            print(f"   catch {dex.get_cm_type(handler.get_type_idx())} -> {handler.get_addr() * 2:04x}")


def main(jar: str) -> int:
    logger.remove()
    with tempfile.TemporaryDirectory() as unpacked:
        with zipfile.ZipFile(jar) as archive:
            names = [n for n in archive.namelist() if n.startswith("classes") and n.endswith(".dex")]
            archive.extractall(unpacked, names)
        for name in sorted(names):
            dex = DEX((Path(unpacked) / name).read_bytes())
            for cls in dex.get_classes():
                wanted = METHODS.get(cls.get_name(), set())
                for method in cls.get_methods():
                    if method.get_name() in wanted:
                        show(dex, method)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
