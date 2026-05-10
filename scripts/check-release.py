from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_RUN_ARTIFACTS = {
    "manifest.json",
    "raw_results.jsonl",
    "eval_results.jsonl",
    "failures.jsonl",
    "clusters.json",
    "summary.md",
    "repair_input.json",
}


def clean_generated_artifacts() -> None:
    for path in [REPO_ROOT / "build", REPO_ROOT / "dist"]:
        if path.exists():
            shutil.rmtree(path)
    for path in REPO_ROOT.glob("*.egg-info"):
        if path.is_dir():
            shutil.rmtree(path)


def run(command: list[str], *, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    print(f"+ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=cwd, text=True, check=True)


def bin_path(venv_dir: Path, executable: str) -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" and executable in {"python", "pip", "agent-eval"} else ""
    return venv_dir / scripts / f"{executable}{suffix}"


def build_distributions(temp_dir: Path) -> list[Path]:
    dist_dir = temp_dir / "dist"
    dist_dir.mkdir()
    run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)])
    artifacts = sorted(dist_dir.iterdir())
    if not artifacts:
        raise AssertionError("build produced no artifacts")
    if not any(path.name.startswith("agent_deepeval-") and path.suffix == ".whl" for path in artifacts):
        raise AssertionError(f"wheel name did not normalize to agent_deepeval: {[p.name for p in artifacts]}")
    run([sys.executable, "-m", "twine", "check", *map(str, artifacts)])
    return artifacts


def create_venv(venv_dir: Path) -> Path:
    # uv-managed Python lacks ensurepip; use uv if available, else stdlib venv
    uv_bin = shutil.which("uv")
    if uv_bin:
        run([uv_bin, "venv", str(venv_dir)])
    else:
        import venv
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    return bin_path(venv_dir, "python")


def install_wheel(python_bin: Path, artifacts: list[Path]) -> None:
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    if len(wheels) != 1:
        raise AssertionError(f"expected exactly one wheel, found {[p.name for p in wheels]}")
    uv_bin = shutil.which("uv")
    if uv_bin:
        run([uv_bin, "pip", "install", "--python", str(python_bin), str(wheels[0])])
    else:
        run([str(python_bin), "-m", "pip", "install", str(wheels[0])])


def run_installed_e2e(python_bin: Path, work_dir: Path) -> None:
    agent_eval = bin_path(python_bin.parents[1], "agent-eval")
    run([str(agent_eval), "--help"], cwd=work_dir)
    run([str(agent_eval), "init"], cwd=work_dir)
    run([str(agent_eval), "run"], cwd=work_dir)
    run([str(agent_eval), "inspect", "--run", "latest"], cwd=work_dir)
    run([str(agent_eval), "export", "--run", "latest"], cwd=work_dir)
    run([str(agent_eval), "compare", "--base", "latest", "--target", "latest"], cwd=work_dir)
    assert_required_artifacts(work_dir)


def assert_required_artifacts(work_dir: Path) -> None:
    latest = work_dir / "runs" / "latest.txt"
    report = work_dir / "reports" / "latest.md"
    if not latest.exists():
        raise AssertionError("missing runs/latest.txt")
    if not report.exists():
        raise AssertionError("missing reports/latest.md")
    run_id = latest.read_text().strip()
    run_dir = work_dir / "runs" / run_id
    missing = sorted(name for name in REQUIRED_RUN_ARTIFACTS if not (run_dir / name).exists())
    if missing:
        raise AssertionError(f"missing run artifacts: {missing}")
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if manifest.get("protocol_version") != "agent-eval/v1alpha1":
        raise AssertionError("manifest protocol_version mismatch")


def main() -> int:
    clean_generated_artifacts()
    try:
        run([sys.executable, "-m", "pytest", "-q"])
        run([sys.executable, "-m", "compileall", "-q", "agent_eval", "tests"])
        with tempfile.TemporaryDirectory(prefix="agent-deepeval-release-") as tmp:
            temp_dir = Path(tmp)
            artifacts = build_distributions(temp_dir)
            venv_dir = temp_dir / "venv"
            python_bin = create_venv(venv_dir)
            install_wheel(python_bin, artifacts)
            project_dir = temp_dir / "fresh-project"
            project_dir.mkdir()
            run_installed_e2e(python_bin, project_dir)
    finally:
        clean_generated_artifacts()
    print("release-check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
