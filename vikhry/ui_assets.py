from __future__ import annotations

from pathlib import Path


def resolve_ui_assets_dir() -> Path | None:
    package_root = Path(__file__).resolve().parent
    packaged_dir = package_root / "_ui"
    if _is_valid_ui_dir(packaged_dir):
        return packaged_dir

    repo_dir = package_root.parent / "frontend" / "dist"
    if _is_valid_ui_dir(repo_dir):
        return repo_dir

    return None


def _is_valid_ui_dir(path: Path) -> bool:
    return path.is_dir() and (path / "index.html").is_file()
