from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STALE_DISTRIBUTION = "agent-" + "eval-cli"
STALE_NORMALIZED = "agent_" + "eval_cli"


def test_distribution_identity_and_release_extra_are_publish_ready():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["name"] == "agent-deepeval"
    assert pyproject["project"]["scripts"]["agent-eval"] == "agent_eval.cli:app"
    assert pyproject["project"]["optional-dependencies"]["release"] == [
        "build>=1.2",
        "twine>=5",
    ]


def test_no_non_historical_old_distribution_references_remain():
    checked_roots = [
        REPO_ROOT / "agent_eval",
        REPO_ROOT / "docs",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
        REPO_ROOT / ".github",
    ]
    checked_files = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "uv.lock",
    ]
    hits: list[str] = []
    for root in checked_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text(errors="ignore")
                if STALE_DISTRIBUTION in text or STALE_NORMALIZED in text:
                    hits.append(str(path.relative_to(REPO_ROOT)))
    for path in checked_files:
        text = path.read_text(errors="ignore")
        if STALE_DISTRIBUTION in text or STALE_NORMALIZED in text:
            hits.append(str(path.relative_to(REPO_ROOT)))

    assert hits == []


def test_readme_documents_10_minute_local_onboarding_path():
    readme = (REPO_ROOT / "README.md").read_text()

    for expected in [
        "agent-deepeval",
        "agent-eval",
        "10-minute local onboarding smoke",
        "agent-eval init",
        "agent-eval run",
        "agent-eval inspect --run latest",
        "agent-eval export --run latest",
        "agent-eval compare --base latest --target latest",
        "one sample case passes and one sample case fails",
        "repair_input.json",
        "reports/latest.md",
        "no API keys",
        "Do not run the `--publish` command unless a separate release decision grants publish authority",
    ]:
        assert expected in readme


def test_docs_preserve_adoption_polish_scope_and_current_surface():
    prd = (REPO_ROOT / "docs" / "prd.md").read_text()
    checklist = (REPO_ROOT / "docs" / "release-checklist.md").read_text()

    for expected in [
        "Python 本地适配器模式",
        "compare",
        "evaluation_policy.reruns",
        "LLM cluster 总结与命名",
        "加权 pass rule",
        "Web/SaaS Dashboard",
    ]:
        assert expected in prd
    assert "本地适配器模式（V1.1）" not in prd

    for expected in [
        "Adoption-polish scope gate",
        "local/dry-run only",
        "Do not run TestPyPI/PyPI upload commands",
        "python scripts/publish-release.py --publish",
        "future, separately authorized release-publish guidance",
    ]:
        assert expected in checklist


def test_release_assets_document_required_gates():
    checklist = REPO_ROOT / "docs" / "release-checklist.md"
    script = REPO_ROOT / "scripts" / "check-release.py"
    workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    assert checklist.exists()
    checklist_text = checklist.read_text()
    for expected in [
        "agent-deepeval",
        "agent-eval",
        "TestPyPI",
        "PyPI",
        "adapter",
        "LLM cluster",
        "twine check",
    ]:
        assert expected in checklist_text

    assert script.exists()
    script_text = script.read_text()
    for expected in [
        "pytest",
        "compileall",
        "build",
        "twine",
        "agent-eval",
        "manifest.json",
        "repair_input.json",
    ]:
        assert expected in script_text
    ast.parse(script_text)

    assert workflow.exists()
    workflow_text = workflow.read_text()
    assert "scripts/check-release.py" in workflow_text


def test_release_script_uses_temp_dist_for_twine_check():
    script = (REPO_ROOT / "scripts" / "check-release.py").read_text()

    assert "--outdir" in script
    assert re.search(r"twine.*check", script, re.DOTALL)
    assert "dist/*" not in script


def test_direct_pypi_publish_script_is_safe_for_continuous_releases():
    script = REPO_ROOT / "scripts" / "publish-release.py"

    assert script.exists()
    script_text = script.read_text()
    for expected in [
        "--publish",
        "scripts/check-release.py",
        "pypi.org/pypi",
        "twine",
        "upload",
        "git",
        "dry-run",
    ]:
        assert expected in script_text
    assert "testpypi" not in script_text.lower()
    assert "TWINE_USERNAME" not in script_text
    assert "TWINE_PASSWORD" not in script_text
    ast.parse(script_text)
