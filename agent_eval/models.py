from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import PROTOCOL_VERSION


class RunnerConfig(BaseModel):
    concurrency: int = 1
    timeout_seconds: float = 30
    retry_times: int = 0
    fail_fast: bool = False


class ProjectConfig(BaseModel):
    name: str = "my-agent"
    mode: Literal["script", "http", "adapter"] = "script"


class HttpTargetConfig(BaseModel):
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    payload_mapping: dict[str, Any] = Field(default_factory=dict)


class ScriptTargetConfig(BaseModel):
    command: str = "python sample_agent.py --input-file {input_file}"


class TargetConfig(BaseModel):
    http: HttpTargetConfig = Field(default_factory=HttpTargetConfig)
    script: ScriptTargetConfig = Field(default_factory=ScriptTargetConfig)


class DatasetConfig(BaseModel):
    paths: list[str] = Field(default_factory=lambda: ["cases/sample.jsonl"])


class LlmJudgeConfig(BaseModel):
    enabled: bool = False
    provider: str = "stub"
    model: str = "stub"
    stub_result: Literal["skipped", "pass", "fail"] = "skipped"


class EvaluationConfig(BaseModel):
    llm_judge: LlmJudgeConfig = Field(default_factory=LlmJudgeConfig)
    rule_assertions: dict[str, Any] | bool = True


class ClusterConfig(BaseModel):
    enabled: bool = True
    llm_summary: bool = False


class ArtifactsConfig(BaseModel):
    root_dir: str = "./runs"
    save_raw_response: bool = True
    save_debug_meta: bool = True
    reports_dir: str = "./reports"


class EvalConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    artifacts: ArtifactsConfig = Field(default_factory=ArtifactsConfig)


class AssertionSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    target: str | None = None
    expected: Any = None
    value: Any = None
    metric: str | None = None
    contains: Any = None
    schema_spec: dict[str, Any] | None = Field(default=None, alias="schema")


class ExpectedExecution(BaseModel):
    expected_route: str | None = None
    must_call_tools: list[str] = Field(default_factory=list)
    forbid_tools: list[str] = Field(default_factory=list)
    max_tool_calls: int | None = None
    min_retrieval_docs: int | None = None
    fallback_used: bool | None = None


class EvaluationPolicy(BaseModel):
    reruns: int = 0
    pass_rule: Literal["all", "any", "majority"] = "all"


class EvalCase(BaseModel):
    id: str
    tags: list[str] = Field(default_factory=list)
    priority: str = "p2"
    inputs: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    assertions: list[AssertionSpec] = Field(default_factory=list)
    expected_execution: ExpectedExecution = Field(default_factory=ExpectedExecution)
    evaluation_policy: EvaluationPolicy = Field(default_factory=EvaluationPolicy)


class ToolCall(BaseModel):
    name: str
    latency_ms: float | None = None


class DebugMeta(BaseModel):
    route: str | None = None
    retrieval_used: bool | None = None
    retrieval_doc_count: int | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    fallback_used: bool | None = None
    prompt_version: str | None = None
    config_version: str | None = None
    error_code: str | None = None


class ErrorInfo(BaseModel):
    message: str
    type: str = "error"
    exit_code: int | None = None
    stderr: str | None = None


class RawResult(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    case_id: str
    status: Literal["success", "error", "timeout"]
    latency_ms: float
    request: dict[str, Any] = Field(default_factory=dict)
    response: Any = Field(default_factory=dict)
    debug_meta: dict[str, Any] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    attempt_count: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssertionResult(BaseModel):
    type: str
    passed: bool
    metric: str | None = None
    score: float | None = None
    reason: str = ""
    skipped: bool = False


class FailureSignature(BaseModel):
    assertion_type: str = ""
    error_code: str = ""
    route_name: str = ""
    tool_name: str = ""
    tag: str = ""
    priority: str = ""


class EvalResult(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    case_id: str
    passed: bool
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    failure_signature: FailureSignature | None = None


class FailureRecord(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    case_id: str
    reasons: list[str] = Field(default_factory=list)
    failure_signature: FailureSignature
    raw_status: str


class Cluster(BaseModel):
    cluster_id: str
    title: str
    severity: Literal["low", "medium", "high"] = "medium"
    case_ids: list[str]
    common_signature: dict[str, Any]
    summary: str
    suspected_modules: list[str] = Field(default_factory=list)


class ClustersFile(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    clusters: list[Cluster] = Field(default_factory=list)


class Manifest(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    created_at: datetime
    project: str
    mode: str
    config_snapshot: dict[str, Any]
    dataset_paths: list[str]
    case_count: int
    tool_version: str
    runner: dict[str, Any]
    evaluation: dict[str, Any]


class RepairCluster(BaseModel):
    cluster_id: str
    title: str
    severity: str
    cases: list[str]
    common_signature: dict[str, Any]
    suspected_modules: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class RepairInput(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    project: str
    clusters: list[RepairCluster] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
