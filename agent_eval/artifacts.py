from __future__ import annotations

import json
import shutil
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .config import dump_config
from .utils.redact import redact
from .models import ClustersFile, EvalConfig, EvalResult, FailureRecord, Manifest, RawResult, RepairCluster, RepairInput
from .run_id import new_run_id


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, items: Iterable[Any]) -> None:
    with path.open("w") as fh:
        for item in items:
            if hasattr(item, "model_dump"):
                item = item.model_dump(mode="json")
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


class ArtifactStore:
    def __init__(self, root: Path, config: EvalConfig, run_id: str):
        self.root = root
        self.config = config
        self.run_id = run_id
        self.runs_dir = root / config.artifacts.root_dir
        self.reports_dir = root / config.artifacts.reports_dir
        self.run_dir = self.runs_dir / run_id

    def prepare(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def write_all(self, raw_results: list[RawResult], eval_results: list[EvalResult], failures: list[FailureRecord], clusters: ClustersFile, summary: str) -> RepairInput:
        manifest = Manifest(
            run_id=self.run_id,
            created_at=datetime.now(UTC),
            project=self.config.project.name,
            mode=self.config.project.mode,
            config_snapshot=redact(dump_config(self.config)),
            dataset_paths=self.config.dataset.paths,
            case_count=len(raw_results),
            tool_version=__version__,
            runner=self.config.runner.model_dump(mode="json"),
            evaluation=self.config.evaluation.model_dump(mode="json"),
        )
        write_json(self.run_dir / "manifest.json", manifest.model_dump(mode="json"))
        write_jsonl(self.run_dir / "raw_results.jsonl", raw_results)
        write_jsonl(self.run_dir / "eval_results.jsonl", eval_results)
        write_jsonl(self.run_dir / "failures.jsonl", failures)
        write_json(self.run_dir / "clusters.json", clusters.model_dump(mode="json"))
        repair = build_repair_input(self.config.project.name, self.run_id, clusters, failures)
        write_json(self.run_dir / "repair_input.json", repair.model_dump(mode="json"))
        (self.run_dir / "summary.md").write_text(summary)
        (self.runs_dir / "latest.txt").write_text(self.run_id + "\n")
        shutil.copyfile(self.run_dir / "summary.md", self.reports_dir / "latest.md")
        (self.reports_dir / "latest_run.txt").write_text(self.run_id + "\n")
        return repair


def build_repair_input(project: str, run_id: str, clusters: ClustersFile, failures: list[FailureRecord]) -> RepairInput:
    failures_by_case = {f.case_id: f for f in failures}
    repair_clusters: list[RepairCluster] = []
    for cluster in clusters.clusters:
        evidence = []
        for case_id in cluster.case_ids:
            failure = failures_by_case.get(case_id)
            if failure:
                evidence.append({"case_id": case_id, "reason": "; ".join(failure.reasons)})
        repair_clusters.append(RepairCluster(cluster_id=cluster.cluster_id, title=cluster.title, severity=cluster.severity, cases=cluster.case_ids, common_signature=cluster.common_signature, suspected_modules=cluster.suspected_modules, evidence=evidence))
    return RepairInput(run_id=run_id, project=project, clusters=repair_clusters, artifacts={"run_dir": f"runs/{run_id}"})


def resolve_run(root: Path, run: str, runs_dir: str = "./runs") -> Path:
    base = root / runs_dir
    if run == "latest":
        latest = (base / "latest.txt").read_text().strip()
        new_run_id(latest)
        return base / latest
    new_run_id(run)
    return base / run
