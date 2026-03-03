from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List


def _resolve_targets(workspace_root: Path, raw_paths: Iterable[str]) -> List[Path]:
    resolved: List[Path] = []
    seen = set()
    for raw in raw_paths:
        text = str(raw).strip()
        if not text:
            continue
        has_glob = any(token in text for token in ("*", "?", "["))
        if has_glob:
            for match in workspace_root.glob(text):
                if match.is_file():
                    norm = match.resolve()
                    if norm not in seen:
                        seen.add(norm)
                        resolved.append(norm)
            continue

        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        if candidate.is_file():
            norm = candidate.resolve()
            if norm not in seen:
                seen.add(norm)
                resolved.append(norm)
    return resolved


def _relative(workspace_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description="Find evidence lines in files without ripgrep.")
    parser.add_argument("--path", action="append", required=True, help="Target path or glob (repeatable).")
    parser.add_argument(
        "--pattern",
        action="append",
        required=True,
        help="Substring pattern to search for (repeatable).",
    )
    args = parser.parse_args()

    workspace_root = Path.cwd()
    targets = _resolve_targets(workspace_root, args.path)
    patterns = [str(item) for item in args.pattern if str(item).strip()]
    if not targets or not patterns:
        print("N/A")
        return 1

    found = False
    for target in targets:
        rel = _relative(workspace_root, target)
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line_number, line in enumerate(lines, start=1):
            if any(pattern in line for pattern in patterns):
                print(f"{rel}:{line_number}:{line}")
                found = True

    if not found:
        print("N/A")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
