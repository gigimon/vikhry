from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        packaged_ui_dir = Path(self.root) / "vikhry" / "_ui"
        if (packaged_ui_dir / "index.html").is_file():
            return

        dist_dir = Path(self.root) / "frontend" / "dist"
        if not (dist_dir / "index.html").is_file():
            raise RuntimeError(
                "Frontend build is missing. Run `./scripts/build_frontend.sh` before building Python artifacts."
            )

        force_include = build_data.setdefault("force_include", {})
        if not isinstance(force_include, dict):
            raise RuntimeError("Unexpected hatch build_data['force_include'] type.")

        for asset_path in sorted(dist_dir.rglob("*")):
            if not asset_path.is_file():
                continue
            relative_path = asset_path.relative_to(dist_dir)
            target_path = Path("vikhry") / "_ui" / relative_path
            force_include[str(asset_path)] = target_path.as_posix()
