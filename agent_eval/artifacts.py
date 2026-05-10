from __future__ import annotations

import json
import shutil
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .analysis import build_run_analysis
from .config import dump_config
from .models import (
    ClustersFile,
    EvalCase,
    EvalConfig,
    EvalResult,
    FailureRecord,
    Manifest,
    RawResult,
    RepairCluster,
    RepairInput,
    RunAnalysis,
)
from .run_id import new_run_id
from .utils.redact import redact, redact_text


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

    def write_all(
        self,
        cases: list[EvalCase],
        raw_results: list[RawResult],
        eval_results: list[EvalResult],
        failures: list[FailureRecord],
        clusters: ClustersFile,
        summary: str,
        analysis: RunAnalysis | None = None,
        attempts: list[dict[str, Any]] | None = None,
    ) -> RepairInput:
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
        if attempts:
            write_jsonl(self.run_dir / "attempts.jsonl", attempts)
        write_jsonl(self.run_dir / "failures.jsonl", failures)
        write_json(self.run_dir / "clusters.json", clusters.model_dump(mode="json"))
        if analysis is None:
            analysis = build_run_analysis(self.run_id, cases, raw_results, eval_results, failures, clusters, str(self.run_dir))
        repair = build_repair_input(self.config.project.name, self.run_id, clusters, failures, analysis=analysis)
        write_json(self.run_dir / "repair_input.json", repair.model_dump(mode="json"))
        (self.run_dir / "summary.md").write_text(summary)
        (self.runs_dir / "latest.txt").write_text(self.run_id + "\n")
        shutil.copyfile(self.run_dir / "summary.md", self.reports_dir / "latest.md")
        (self.reports_dir / "latest_run.txt").write_text(self.run_id + "\n")
        return repair


def _bucket_map(buckets: Iterable[Any]) -> dict[str, dict[str, Any]]:
    return {
        bucket.name: {
            "total": bucket.total,
            "passed": bucket.passed,
            "failed": bucket.failed,
            "pass_rate": bucket.pass_rate,
        }
        for bucket in buckets
    }


def build_repair_input(project: str, run_id: str, clusters: ClustersFile, failures: list[FailureRecord], analysis: RunAnalysis | None = None) -> RepairInput:
    run_analysis = analysis
    if run_analysis is None:
        # Compatibility path for callers/tests that only have the historical
        # repair inputs. This keeps legacy fields stable while still using the
        # shared analysis shape for cluster-level parity.
        run_analysis = build_run_analysis(run_id, [], [], [], failures, clusters)
    failures_by_case = {f.case_id: f for f in failures}
    analysis_by_cluster = {cluster.cluster_id: cluster for cluster in run_analysis.clusters}
    repair_clusters: list[RepairCluster] = []
    for cluster in clusters.clusters:
        cluster_analysis = analysis_by_cluster.get(cluster.cluster_id)
        if cluster_analysis:
            evidence = [item.model_dump(mode="json") for item in cluster_analysis.evidence]
        else:
            evidence = []
            for case_id in cluster.case_ids:
                failure = failures_by_case.get(case_id)
                if failure:
                    evidence.append({"case_id": case_id, "reason": "; ".join(redact_text(reason) or "" for reason in failure.reasons)})
        signature = cluster.common_signature or {}
        cluster_payload = {
            "representative_cases": cluster_analysis.representative_cases if cluster_analysis else cluster.case_ids[:3],
            "signature_explanation": cluster_analysis.signature_explanation if cluster_analysis else cluster.summary,
        }
        if isinstance(signature.get("analysis"), dict):
            cluster_payload.update(signature["analysis"])
        if cluster_analysis:
            cluster_payload.update(
                {
                    "case_count": cluster_analysis.case_count,
                    "affected_areas": cluster_analysis.affected_areas,
                    "suggested_investigation": cluster_analysis.suggested_investigation,
                    "evidence": [item.model_dump(mode="json") for item in cluster_analysis.evidence],
                }
            )
        repair_clusters.append(
            RepairCluster(
                cluster_id=cluster.cluster_id,
                title=cluster.title,
                severity=cluster.severity,
                cases=cluster.case_ids,
                common_signature=cluster.common_signature,
                suspected_modules=cluster_analysis.suspected_modules if cluster_analysis else cluster.suspected_modules,
                evidence=evidence,
                analysis=cluster_payload,
            )
        )
    totals = run_analysis.totals.model_dump(mode="json")
    return RepairInput(
        run_id=run_id,
        project=project,
        clusters=repair_clusters,
        artifacts={"run_dir": f"runs/{run_id}"},
        analysis={
            "cluster_count": len(repair_clusters),
            "totals": totals,
            "tag_breakdown": _bucket_map(run_analysis.tag_breakdown),
            "priority_breakdown": _bucket_map(run_analysis.priority_breakdown),
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "representative_cases": cluster.representative_cases,
                    "signature_explanation": cluster.signature_explanation,
                    "affected_areas": cluster.affected_areas,
                    "suggested_investigation": cluster.suggested_investigation,
                }
                for cluster in run_analysis.clusters
            ],
        },
    )


def resolve_run(root: Path, run: str, runs_dir: str = "./runs") -> Path:
    base = root / runs_dir
    if run == "latest":
        latest = (base / "latest.txt").read_text().strip()
        new_run_id(latest)
        return base / latest
    new_run_id(run)
    return base / run
