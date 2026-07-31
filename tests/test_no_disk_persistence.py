import ast
from pathlib import Path

import pytest


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        called = _qualified_name(node.func)
        return f"{called}()" if called else ""
    return ""


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                local_name = imported.asname or imported.name.split(".")[0]
                aliases[local_name] = imported.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for imported in node.names:
                if imported.name == "*":
                    continue
                local_name = imported.asname or imported.name
                aliases[local_name] = f"{module}.{imported.name}".strip(".")
    return aliases


def _resolve_alias(call_name: str, aliases: dict[str, str]) -> str:
    head, separator, tail = call_name.partition(".")
    was_called = head.endswith("()")
    lookup = head.removesuffix("()")
    resolved_head = aliases.get(lookup, lookup)
    if was_called:
        resolved_head = f"{resolved_head}()"
    return f"{resolved_head}{separator}{tail}" if separator else resolved_head


def _open_mode(node: ast.Call, positional_index: int) -> str | None:
    mode_node = node.args[positional_index] if len(node.args) > positional_index else None
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return mode_node.value
    return None


def _disk_write_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported = [alias.name for alias in node.names]
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            if module == "tempfile" or any(name == "tempfile" for name in imported):
                violations.append(f"line {node.lineno}: tempfile usage")

        if not isinstance(node, ast.Call):
            continue

        call_name = _resolve_alias(_qualified_name(node.func), aliases)
        if call_name == "cv2.imwrite" or call_name.endswith(".save"):
            violations.append(f"line {node.lineno}: {call_name}")
            continue

        if call_name.startswith("tempfile."):
            violations.append(f"line {node.lineno}: {call_name}")
            continue

        if call_name.endswith((".write_bytes", ".write_text")):
            violations.append(f"line {node.lineno}: {call_name}")
            continue

        if call_name in {"open", "builtins.open", "io.open"}:
            mode = _open_mode(node, positional_index=1)
        elif call_name.endswith(".open"):
            mode = _open_mode(node, positional_index=0)
        else:
            continue
        if mode is not None and any(flag in mode for flag in "wax+"):
            violations.append(f"line {node.lineno}: {call_name} mode {mode!r}")

    return violations


@pytest.mark.parametrize(
    "source",
    [
        "cv2.imwrite('crop.png', image)",
        "image.save('crop.png')",
        "open('crop.png', 'wb')",
        "open('crop.png', mode='w')",
        "import tempfile",
        "from tempfile import NamedTemporaryFile",
        "tempfile.NamedTemporaryFile()",
        "import cv2 as vision\nvision.imwrite('crop.png', image)",
        "from cv2 import imwrite as write_image\nwrite_image('crop.png', image)",
        "from pathlib import Path\nPath('crop.png').write_bytes(data)",
        "path.write_text(extracted_text)",
        "path.open('wb')",
        "import io\nio.open('crop.png', 'wb')",
        "from io import open as io_open\nio_open('text.txt', 'w')",
    ],
)
def test_static_detector_recognizes_forbidden_persistence_patterns(source: str) -> None:
    assert _disk_write_violations(source)


def test_labelcheck_source_never_writes_images_or_extracted_data_to_disk() -> None:
    source_root = Path(__file__).parents[1] / "src" / "labelcheck"
    violations: list[str] = []

    for path in source_root.rglob("*.py"):
        for violation in _disk_write_violations(path.read_text(encoding="utf-8")):
            violations.append(f"{path.relative_to(source_root)}: {violation}")

    assert not violations, "Disk persistence is forbidden:\n" + "\n".join(violations)
