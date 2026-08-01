import ast
from pathlib import Path

import pytest

# The federal firewall constraint: the verification path must run fully offline.
# Like test_no_disk_persistence.py, the requirement gets a red test, not just prose.
_FORBIDDEN_ROOT_MODULES = {
    "aiohttp",
    "http",
    "httpx",
    "requests",
    "socket",
    "urllib",
    "urllib3",
}


def _network_import_violations(source: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            if module.split(".")[0] in _FORBIDDEN_ROOT_MODULES:
                violations.append(f"line {node.lineno}: import of {module}")
    return violations


@pytest.mark.parametrize(
    "source",
    [
        "import requests",
        "import requests as fetch",
        "import urllib.request",
        "from urllib.request import urlopen",
        "from urllib import request",
        "import urllib3",
        "import httpx",
        "from httpx import Client",
        "import aiohttp",
        "import socket",
        "from http.client import HTTPSConnection",
    ],
)
def test_static_detector_recognizes_forbidden_network_imports(source: str) -> None:
    assert _network_import_violations(source)


def test_verification_path_never_imports_network_modules() -> None:
    repo_root = Path(__file__).parents[1]
    scanned = sorted((repo_root / "src" / "labelcheck").rglob("*.py"))
    scanned.append(repo_root / "app.py")
    violations: list[str] = []

    for path in scanned:
        for violation in _network_import_violations(path.read_text(encoding="utf-8")):
            violations.append(f"{path.relative_to(repo_root)}: {violation}")

    assert not violations, "Outbound network access is forbidden:\n" + "\n".join(violations)
