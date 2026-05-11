from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
PYPI_JSON_BASE = "https://pypi.org/pypi"


class ReleaseError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path = REPO_ROOT) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, text=True, check=True)


def capture(command: list[str], *, cwd: Path = REPO_ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def read_project_identity() -> tuple[str, str]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    project = pyproject.get("project", {})
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name:
        raise ReleaseError("pyproject.toml is missing project.name")
    if not isinstance(version, str) or not version:
        raise ReleaseError("pyproject.toml is missing project.version")
    return name, version


def assert_clean_git(*, allow_dirty: bool) -> None:
    if allow_dirty:
        return
    status = capture(["git", "status", "--porcelain"])
    if status:
        raise ReleaseError(
            "working tree is not clean; commit or stash changes before publishing "
            "or rerun with --allow-dirty for an intentional local release"
        )


def assert_not_already_published(name: str, version: str) -> None:
    url = f"{PYPI_JSON_BASE}/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            if response.status == 200:
                raise ReleaseError(
                    f"{name}=={version} already exists on PyPI; bump the version first"
                )
            raise ReleaseError(
                f"unexpected PyPI response for {url}: HTTP {response.status}"
            )
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print(f"PyPI availability: OK ({name}=={version} is not published)")
            return
        raise ReleaseError(
            f"unexpected PyPI response for {url}: HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise ReleaseError(
            f"could not verify PyPI availability for {name}=={version}: {error}"
        ) from error


def clean_dist() -> None:
    for path in [DIST_DIR, BUILD_DIR]:
        if path.exists():
            shutil.rmtree(path)
    for path in REPO_ROOT.glob("*.egg-info"):
        if path.is_dir():
            shutil.rmtree(path)


def build_artifacts() -> list[Path]:
    clean_dist()
    run(
        [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(DIST_DIR)]
    )
    artifacts = sorted(path for path in DIST_DIR.iterdir() if path.is_file())
    if not artifacts:
        raise ReleaseError("build produced no dist artifacts")
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        names = [path.name for path in artifacts]
        raise ReleaseError(f"expected one wheel and one sdist, found: {names}")
    run([sys.executable, "-m", "twine", "check", *map(str, artifacts)])
    return artifacts


def wait_for_pypi_version(
    name: str, version: str, *, timeout_seconds: int = 90
) -> None:
    url = f"{PYPI_JSON_BASE}/{name}/{version}/json"
    deadline = time.monotonic() + timeout_seconds
    last_error = "not checked"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    if payload.get("info", {}).get("version") == version:
                        print(f"PyPI verification: OK ({name}=={version})")
                        return
                    last_error = "version metadata mismatch"
                else:
                    last_error = f"HTTP {response.status}"
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"
        except Exception as error:  # index propagation can briefly race network state
            last_error = str(error)
        time.sleep(5)
    raise ReleaseError(
        f"upload command finished, but PyPI verification did not observe {name}=={version}: {last_error}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the official local release gate, build clean artifacts, and optionally publish to PyPI."
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="actually upload dist artifacts to PyPI; without this flag the script stops after a dry-run build",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow publishing from a dirty working tree (not recommended for normal releases)",
    )
    parser.add_argument(
        "--skip-release-check",
        action="store_true",
        help="skip scripts/check-release.py (only for rerunning after a just-passed gate)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    name, version = read_project_identity()
    print(f"Release target: {name}=={version}")

    assert_clean_git(allow_dirty=args.allow_dirty)
    assert_not_already_published(name, version)

    if not args.skip_release_check:
        run([sys.executable, "scripts/check-release.py"])

    artifacts = build_artifacts()
    if not args.publish:
        print("dry-run: OK")
        print("Artifacts ready:")
        for artifact in artifacts:
            print(f"- {artifact.relative_to(REPO_ROOT)}")
        print("To publish, rerun: python scripts/publish-release.py --publish")
        return 0

    assert_not_already_published(name, version)
    run([sys.executable, "-m", "twine", "upload", *map(str, artifacts)])
    wait_for_pypi_version(name, version)
    print("publish-release: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"publish-release: FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
