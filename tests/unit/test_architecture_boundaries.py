from pathlib import Path


def test_no_amber_platform_imports_in_core():
    core_root = Path("src/core")
    offenders = []
    for path in core_root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        content = path.read_text(encoding="utf-8")
        if "amber_platform" in content:
            offenders.append(str(path))

    assert offenders == [], f"core imports amber_platform: {offenders}"
