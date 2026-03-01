from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from log import read_json, timestamp_for_filename, to_workspace_relative, utc_now, write_json  # type: ignore
    from ssot import load_config  # type: ignore
else:
    from ..log import read_json, timestamp_for_filename, to_workspace_relative, utc_now, write_json
    from ..ssot import load_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save manual audit text and attach it to the latest orchestrator run."
    )
    parser.add_argument(
        "--file",
        default="",
        help="Optional markdown/text file path. If omitted, reads from stdin.",
    )
    return parser.parse_args()


def _read_input_text(file_arg: str) -> str:
    file_path = str(file_arg).strip()
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    return sys.stdin.read()


def _dedupe(items: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _attach_evidence_path(run_data: Dict[str, Any], evidence_path: str) -> Dict[str, Any]:
    existing = run_data.get("evidence_paths")
    evidence = existing if isinstance(existing, list) else []
    merged = _dedupe([*(str(item) for item in evidence), evidence_path])
    run_data["evidence_paths"] = merged
    return run_data


def _collect_run_json_paths(config: Any, latest_run: Dict[str, Any], run_id: str) -> List[Path]:
    paths: List[Path] = []

    # Primary run file from run_id.
    if run_id:
        paths.append(config.runs_dir / f"{run_id}.json")

    # Any run json paths explicitly referenced in evidence_paths.
    evidence_paths = latest_run.get("evidence_paths")
    if isinstance(evidence_paths, list):
        for item in evidence_paths:
            if not isinstance(item, str):
                continue
            raw = item.strip()
            if not raw:
                continue
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = config.workspace_root / raw
            try:
                resolved = candidate.resolve()
            except Exception:
                continue
            if resolved.suffix.lower() != ".json":
                continue
            if resolved.parent.resolve() != config.runs_dir.resolve():
                continue
            paths.append(resolved)

    deduped: List[Path] = []
    seen = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def main() -> int:
    args = _parse_args()
    text = _read_input_text(args.file)
    if not text.strip():
        print("orch-audit failed: no audit text provided (stdin/file empty)")
        return 1

    config = load_config()
    latest_run = read_json(config.latest_run_path)
    if not latest_run:
        print(f"orch-audit failed: latest run not found or invalid ({config.latest_run_path})")
        return 1

    run_id = str(latest_run.get("run_id", "")).strip()
    if not run_id:
        print("orch-audit failed: run_id missing in runs/latest.json")
        return 1

    audits_dir = config.artifacts_dir / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp_for_filename(utc_now())
    audit_path = audits_dir / f"{timestamp}_audit.md"
    audit_path.write_text(text.rstrip() + "\n", encoding="utf-8")

    audit_rel = to_workspace_relative(audit_path, config.workspace_root)
    latest_updated = _attach_evidence_path(latest_run, audit_rel)
    write_json(config.latest_run_path, latest_updated)

    for run_path in _collect_run_json_paths(config, latest_updated, run_id):
        if not run_path.exists():
            continue
        run_record = read_json(run_path)
        if run_record:
            write_json(run_path, _attach_evidence_path(run_record, audit_rel))

    print(f"audit saved: {audit_rel}")
    print(f"linked run_id: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
