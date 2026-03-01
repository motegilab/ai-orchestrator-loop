from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_SOURCE = "cursor"


@dataclass(frozen=True)
class OrchestratorConfig:
    workspace_root: Path
    runtime_root: Path
    host: str
    port: int
    source: str
    ssot_path: Optional[Path]  # None = SSOT 読込なし。Path = ワークスペースルート基準

    @property
    def runs_dir(self) -> Path:
        return self.runtime_root / "runs"

    @property
    def artifacts_dir(self) -> Path:
        return self.runtime_root / "artifacts"

    @property
    def webhooks_dir(self) -> Path:
        return self.artifacts_dir / "webhooks"

    @property
    def summaries_dir(self) -> Path:
        return self.artifacts_dir / "summaries"

    @property
    def diffs_dir(self) -> Path:
        return self.artifacts_dir / "diffs"

    @property
    def unity_logs_dir(self) -> Path:
        return self.runtime_root / "unity_logs"

    @property
    def gas_logs_dir(self) -> Path:
        return self.runtime_root / "gas_logs"

    @property
    def logs_dir(self) -> Path:
        return self.runtime_root / "logs"

    @property
    def next_prompt_path(self) -> Path:
        return self.logs_dir / "next_prompt.md"

    @property
    def latest_run_path(self) -> Path:
        return self.runs_dir / "latest.json"


def load_config() -> OrchestratorConfig:
    script_dir = Path(__file__).resolve().parent
    default_workspace_root = (script_dir / ".." / "..").resolve()
    config_path = script_dir / "config.yaml"

    values: Dict[str, Any] = {}
    if config_path.exists():
        values = _parse_simple_yaml(config_path)

    workspace_raw = values.get("workspace_root", str(default_workspace_root))
    workspace_root = _resolve_path(workspace_raw, base_dir=script_dir)

    runtime_raw = values.get(
        "runtime_root",
        str(workspace_root / "tools" / "orchestrator_runtime"),
    )
    runtime_root = _resolve_path(runtime_raw, base_dir=workspace_root)

    host = str(values.get("host", DEFAULT_HOST)).strip() or DEFAULT_HOST
    port = _coerce_port(values.get("port", DEFAULT_PORT))
    source = str(values.get("source", DEFAULT_SOURCE)).strip() or DEFAULT_SOURCE

    ssot_path: Optional[Path] = None
    if values.get("ssot_path"):
        raw = str(values.get("ssot_path", "")).strip().strip("\"'")
        if raw:
            ssot_path = (workspace_root / raw).resolve()

    config = OrchestratorConfig(
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        host=host,
        port=port,
        source=source,
        ssot_path=ssot_path,
    )
    ensure_runtime_structure(config)
    return config


def ensure_runtime_structure(config: OrchestratorConfig) -> None:
    required_dirs = [
        config.runtime_root,
        config.runs_dir,
        config.artifacts_dir,
        config.webhooks_dir,
        config.summaries_dir,
        config.diffs_dir,
        config.unity_logs_dir,
        config.gas_logs_dir,
        config.logs_dir,
    ]
    for directory in required_dirs:
        directory.mkdir(parents=True, exist_ok=True)


def _resolve_path(raw: Any, base_dir: Path) -> Path:
    value = str(raw).strip().strip("\"'")
    if not value:
        return base_dir.resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _coerce_port(raw: Any) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def _parse_simple_yaml(path: Path) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = _strip_inline_comment(raw_value).strip().strip("\"'")
        if not key:
            continue

        values[key] = _coerce_scalar(value)
    return values


def _strip_inline_comment(value: str) -> str:
    in_single_quote = False
    in_double_quote = False
    result_chars = []

    for char in value:
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote

        if char == "#" and not in_single_quote and not in_double_quote:
            break
        result_chars.append(char)
    return "".join(result_chars)


def _coerce_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        return value
