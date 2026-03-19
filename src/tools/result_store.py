"""Result persistence store for multi-agent citation workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class ResultStoreConfig:
    """Configuration for ResultStore."""

    base_dir: str = "./output/runs"
    run_id: Optional[str] = None


class ResultStore:
    """File-based result store for batch processing."""

    def __init__(
        self,
        base_dir: str = "./output/runs",
        run_id: Optional[str] = None,
        config_snapshot: Optional[dict[str, Any]] = None,
        tool_params: Optional[dict[str, Any]] = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.run_id = self._sanitize_run_id(run_id or self._generate_run_id())
        self.run_dir = self.base_dir / self.run_id
        self.papers_dir = self.run_dir / "papers"
        self._paper_cache: dict[str, str] = {}

        self.papers_dir.mkdir(parents=True, exist_ok=True)
        self._init_run_file(config_snapshot=config_snapshot, tool_params=tool_params)

    def _generate_run_id(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_run")

    def _sanitize_run_id(self, run_id: str) -> str:
        return run_id.replace(":", "-").replace(" ", "_")

    def _init_run_file(
        self,
        config_snapshot: Optional[dict[str, Any]] = None,
        tool_params: Optional[dict[str, Any]] = None,
    ) -> None:
        run_path = self.run_dir / "run.json"
        if run_path.exists():
            data = self._read_json(run_path)
        else:
            data = {"run_id": self.run_id, "created_at": _utc_now()}

        if config_snapshot:
            data["config_snapshot"] = config_snapshot
        if tool_params:
            data["tool_params"] = tool_params

        # v3 schema version
        data["schema_version"] = "v3"

        self._write_json(run_path, data)

    def register_paper(self, source_path: str, metadata: Optional[dict[str, Any]] = None) -> str:
        source_path = str(Path(source_path).resolve())
        if source_path in self._paper_cache:
            return self._paper_cache[source_path]

        paper_id = self._hash_file(source_path)
        paper_dir = self.papers_dir / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)

        stat = Path(source_path).stat()
        source = {
            "paper_id": paper_id,
            "source_path": source_path,
            "sha256": paper_id,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "metadata": metadata or {},
        }
        self._write_json(paper_dir / "source.json", source)
        self._paper_cache[source_path] = paper_id
        return paper_id

    def save_extraction(self, paper_id: str, extraction: dict[str, Any]) -> Path:
        """Save citation extraction results (citations + references)."""
        return self._write_json(self._paper_dir(paper_id) / "extraction.json", extraction)

    def save_validation(self, paper_id: str, validation: dict[str, Any]) -> Path:
        """Save validation results (C3, C5) + ref_metadata_cache."""
        return self._write_json(self._paper_dir(paper_id) / "validation.json", validation)

    def save_c6_alignment(self, paper_id: str, data: dict[str, Any]) -> Path:
        """Save C6 citation-sentence alignment results."""
        return self._write_json(self._paper_dir(paper_id) / "c6_alignment.json", data)

    def save_citation_analysis(self, paper_id: str, data: dict[str, Any]) -> Path:
        """Save CitationAnalyzer T/S series metrics (T1-T5, S1-S4)."""
        return self._write_json(self._paper_dir(paper_id) / "analysis.json", data)

    def save_graph_analysis(self, paper_id: str, data: dict[str, Any]) -> Path:
        """Save CitationGraphAnalysis G series metrics + S5."""
        return self._write_json(self._paper_dir(paper_id) / "graph_analysis.json", data)

    def save_trend_baseline(self, paper_id: str, data: dict[str, Any]) -> Path:
        """Save field_trend_baseline (yearly publication counts)."""
        return self._write_json(self._paper_dir(paper_id) / "trend_baseline.json", data)

    def save_key_papers(self, paper_id: str, data: dict[str, Any]) -> Path:
        """Save candidate_key_papers + G4 coverage + missing/suspicious lists."""
        return self._write_json(self._paper_dir(paper_id) / "key_papers.json", data)

    def append_error(self, paper_id: str, record: dict[str, Any]) -> None:
        record = dict(record)
        record.setdefault("ts", _utc_now())
        self._append_jsonl(self._paper_dir(paper_id) / "errors.jsonl", record)

    def append_agent_log(self, paper_id: str, record: dict[str, Any]) -> None:
        record = dict(record)
        record.setdefault("ts", _utc_now())
        self._append_jsonl(self._paper_dir(paper_id) / "agent_logs.jsonl", record)

    def update_index(
        self,
        paper_id: str,
        status: str,
        source_path: Optional[str] = None,
    ) -> None:
        index_path = self.run_dir / "index.json"
        data = self._read_json(index_path) if index_path.exists() else {"papers": {}}
        entry = data["papers"].get(paper_id, {})
        entry["paper_id"] = paper_id
        entry["status"] = status
        entry["updated_at"] = _utc_now()
        if source_path:
            entry["source_path"] = str(Path(source_path).resolve())
        data["papers"][paper_id] = entry
        self._write_json(index_path, data)

    def _paper_dir(self, paper_id: str) -> Path:
        path = self.papers_dir / paper_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _hash_file(self, path: str) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()[:12]

    def _write_json(self, path: Path, data: dict[str, Any]) -> Path:
        """Write JSON to file and return the path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
