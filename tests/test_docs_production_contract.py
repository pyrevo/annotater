"""Contract for the production documentation workflow (Zensical Classic).

`workflow_violations` encodes the guarantees of .github/workflows/docs.yaml:
the site that is verified is the directory that is uploaded as the Pages
artifact, the upload happens only after every verification step, deployment
stays gated and depends only on the verified build, and nothing else can
publish. The real workflow must satisfy it, and every mutation below, applied
to an in-memory copy, must be reported (so the guard itself cannot go slack).
"""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
from pathlib import Path
from typing import Callable

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yaml"
APP_WORKFLOW = ROOT / ".github" / "workflows" / "python-tests.yml"

DEPLOY_IF = "github.event_name == 'push' && vars.DOCS_PUBLISH == 'true'"
EXPECTED_GATE_NEEDS = {"lock-consistency", "tests", "frontend-tests", "browser-regression", "docker-smoke"}


def load(path: Path = WORKFLOW) -> dict:
    return yaml.safe_load(path.read_text("utf-8"))


def _run(step: dict) -> str:
    return str(step.get("run", ""))


def _find(steps: list[dict], needle: str) -> int | None:
    for i, step in enumerate(steps):
        if needle in _run(step) or needle in str(step.get("uses", "")):
            return i
    return None


def workflow_violations(wf: dict) -> list[str]:
    v: list[str] = []
    jobs = wf.get("jobs", {})
    if set(jobs) != {"build", "deploy"}:
        v.append(f"unexpected job set {sorted(jobs)}: only `build` and `deploy` may exist")
    if wf.get("permissions") != {"contents": "read", "pages": "write", "id-token": "write"}:
        v.append("workflow-level permissions changed")
    triggers = wf.get("on", wf.get(True)) or {}
    if "pull_request" not in triggers or triggers.get("push", {}).get("branches") != ["main"]:
        v.append("triggers must include pull_request and push to main")

    build = jobs.get("build", {})
    steps = build.get("steps", [])
    if build.get("permissions") != {"contents": "read"}:
        v.append("build job permissions must be exactly contents: read")

    zen_install = _find(steps, "-r docs/requirements-zensical.txt")
    chromium = _find(steps, "python -m playwright install --with-deps chromium")
    reference = _find(steps, "mkdocs build --strict")
    zen_build = next((i for i, s in enumerate(steps) if _run(s).strip() == "zensical build --clean --strict"), None)
    structural = _find(steps, "scripts/check_docs_site.py")
    search = _find(steps, "scripts/check_docs_search.py")
    for label, index in (
        ("pinned Zensical install", zen_install),
        ("Chromium install", chromium),
        ("Material reference build", reference),
        ("strict Zensical build (`zensical build --clean --strict`)", zen_build),
        ("structural check", structural),
        ("browser search regression", search),
    ):
        if index is None:
            v.append(f"missing step: {label}")

    if structural is not None:
        run = _run(steps[structural])
        if not all(flag in run for flag in ("--site site", "--reference", "--self-test")):
            v.append("structural check must run on `--site site` with --reference and --self-test")
    if search is not None:
        run = _run(steps[search])
        if not all(flag in run for flag in ("--site site", "--self-test")):
            v.append("browser search regression must run on `--site site` with --self-test")
    if reference is not None and not re.search(r'-d\s+"?\$RUNNER_TEMP/', _run(steps[reference])):
        v.append("Material reference build must write outside the published directory")

    pages = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/upload-pages-artifact@")]
    if len(pages) != 1:
        v.append("exactly one Pages artifact upload is required in the build job")
    else:
        upload = steps[pages[0]]
        if upload.get("with", {}).get("path") != "site":
            v.append("uploaded directory must be the verified `site` directory")
        verification = [i for i in (zen_build, structural, search) if i is not None]
        if verification and pages[0] < max(verification):
            v.append("Pages artifact is uploaded before verification has finished")
    if None not in (chromium, search) and chromium > search:
        v.append("Chromium must be installed before the browser check")
    if None not in (zen_install, zen_build) and zen_install > zen_build:
        v.append("Zensical must be installed before it is used")

    for index in (zen_install, chromium, reference, zen_build, structural, search):
        if index is None:
            continue
        step = steps[index]
        if step.get("continue-on-error"):
            v.append(f"continue-on-error on verification step {step.get('name')!r}")
        if "if" in step:
            v.append(f"conditional verification step {step.get('name')!r}")
    for step in steps:
        if "if" in step and not (step["if"] == "failure()" and str(step.get("uses", "")).startswith("actions/upload-artifact@")):
            v.append(f"only the failure-diagnostics upload may be conditional, not {step.get('name')!r}")

    for name, job in jobs.items():
        for step in job.get("steps", []):
            uses = str(step.get("uses", ""))
            if "deploy-pages" in uses and name != "deploy":
                v.append(f"job {name!r} must not deploy")
            if uses.startswith("actions/upload-pages-artifact@") and name != "build":
                v.append(f"job {name!r} must not upload a Pages artifact")

    deploy = jobs.get("deploy", {})
    if deploy.get("needs") not in ("build", ["build"]):
        v.append("deploy must need exactly the verified build job")
    if deploy.get("if") != DEPLOY_IF:
        v.append("deploy condition changed (must be push to a ref with DOCS_PUBLISH == 'true' only)")
    deploy_steps = deploy.get("steps", [])
    if len(deploy_steps) != 1 or not str(deploy_steps[0].get("uses", "")).startswith("actions/deploy-pages@"):
        v.append("deploy must consist of the single actions/deploy-pages step")
    if deploy.get("environment", {}).get("name") != "github-pages":
        v.append("deploy must use the github-pages environment")
    return v


# --- the real workflow --------------------------------------------------------


def test_real_workflow_satisfies_the_production_contract():
    assert workflow_violations(load()) == []


def test_production_build_uses_pinned_zensical_classic_and_keeps_material_for_rollback():
    def pins(name: str) -> list[str]:
        text = (ROOT / "docs" / name).read_text("utf-8")
        return [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]

    assert pins("requirements-zensical.txt") == ["zensical==0.0.73"]
    assert pins("requirements-docs-browser.txt") == ["playwright==1.64.0"]
    assert pins("requirements-docs.txt") == ["mkdocs-material>=9.5,<10"]
    config = (ROOT / "mkdocs.yml").read_text("utf-8")
    assert re.search(r"^theme:\n  name: material\n(?:  #.*\n)*  variant: classic\n", config, re.M)
    assert "modern" not in config and not re.search(r"^\s*-\s*offline\b", config, re.M)
    assert "use_directory_urls" not in config  # directory-style URLs stay the default


def test_application_ci_gate_is_unchanged_and_independent_of_the_docs_workflow():
    app = load(APP_WORKFLOW)
    assert set(app["jobs"]["ci-gate"]["needs"]) == EXPECTED_GATE_NEEDS
    assert set(app["jobs"]) == EXPECTED_GATE_NEEDS | {"ci-gate"}
    assert set(app["jobs"]).isdisjoint(load()["jobs"])


def test_tested_directory_is_the_uploaded_directory():
    steps = load()["jobs"]["build"]["steps"]
    checked = [re.search(r"--site (\S+)", _run(s)).group(1) for s in steps if "--site" in _run(s)]
    uploaded = next(s["with"]["path"] for s in steps if str(s.get("uses", "")).startswith("actions/upload-pages-artifact@"))
    assert checked and set(checked) == {uploaded} == {"site"}


# --- mutations: the guard must catch each regression ---------------------------


def _build_steps(wf: dict) -> list[dict]:
    return wf["jobs"]["build"]["steps"]


def _step_index(wf: dict, needle: str) -> int:
    index = _find(_build_steps(wf), needle)
    assert index is not None, needle
    return index


def _drop(needle: str) -> Callable[[dict], None]:
    return lambda wf: _build_steps(wf).pop(_step_index(wf, needle))


def _upload_first(wf: dict) -> None:
    steps = _build_steps(wf)
    steps.insert(_step_index(wf, "zensical build"), steps.pop(_step_index(wf, "upload-pages-artifact")))


def _upload_before_search(wf: dict) -> None:
    steps = _build_steps(wf)
    steps.insert(_step_index(wf, "check_docs_search.py"), steps.pop(_step_index(wf, "upload-pages-artifact")))


def _non_strict(wf: dict) -> None:
    steps = _build_steps(wf)
    steps[_step_index(wf, "zensical build")]["run"] = "zensical build --clean"


def _set(path: Callable[[dict], dict], key: str, value) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        target = path(wf)
        if value is _DELETE:
            target.pop(key)
        else:
            target[key] = value

    return mutate


_DELETE = object()


def _step(needle: str) -> Callable[[dict], dict]:
    return lambda wf: _build_steps(wf)[_step_index(wf, needle)]


def _extra_job(wf: dict) -> None:
    wf["jobs"]["docs-zensical"] = {
        "runs-on": "ubuntu-latest",
        "steps": [{"uses": "actions/upload-pages-artifact@v3", "with": {"path": "site"}}],
    }


def _second_pages_upload(wf: dict) -> None:
    _build_steps(wf).append({"uses": "actions/upload-pages-artifact@v3", "with": {"path": "site"}})


def _reference_writes_to_site(wf: dict) -> None:
    _build_steps(wf)[_step_index(wf, "mkdocs build")]["run"] = "mkdocs build --strict"


def _deploy_step_in_build(wf: dict) -> None:
    _build_steps(wf).append({"uses": "actions/deploy-pages@v4"})


def _no_self_test(needle: str) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        step = _build_steps(wf)[_step_index(wf, needle)]
        step["run"] = step["run"].replace("--self-test", "")

    return mutate


def _wrong_checked_site(wf: dict) -> None:
    step = _build_steps(wf)[_step_index(wf, "check_docs_search.py")]
    step["run"] = step["run"].replace("--site site", "--site other-site")


def _conditional_diagnostics(wf: dict) -> None:
    _build_steps(wf).append({"name": "extra", "if": "always()", "run": "true"})


def _deploy(wf: dict) -> dict:
    return wf["jobs"]["deploy"]


MUTATIONS: dict[str, tuple[Callable[[dict], None], str]] = {
    "Pages upload moved before the Zensical build": (_upload_first, "uploaded before verification"),
    "Pages upload moved before the browser check": (_upload_before_search, "uploaded before verification"),
    "browser search regression removed": (_drop("check_docs_search.py"), "missing step: browser search regression"),
    "structural check removed": (_drop("check_docs_site.py"), "missing step: structural check"),
    "Chromium install removed": (_drop("playwright install"), "missing step: Chromium install"),
    "pinned Zensical install removed": (_drop("requirements-zensical.txt"), "missing step: pinned Zensical install"),
    "Zensical build no longer strict": (_non_strict, "strict Zensical build"),
    "continue-on-error on the browser check": (_set(_step("check_docs_search.py"), "continue-on-error", True), "continue-on-error"),
    "browser check made conditional": (_set(_step("check_docs_search.py"), "if", "github.event_name == 'push'"), "conditional verification"),
    "unrelated conditional step added": (_conditional_diagnostics, "only the failure-diagnostics upload"),
    "browser self-test dropped": (_no_self_test("check_docs_search.py"), "browser search regression must run"),
    "structural self-test dropped": (_no_self_test("check_docs_site.py"), "structural check must run"),
    "browser check runs on another directory": (_wrong_checked_site, "browser search regression must run"),
    "different directory uploaded": (_set(_step("upload-pages-artifact"), "with", {"path": "material-reference"}), "uploaded directory must be"),
    "second Pages upload added": (_second_pages_upload, "exactly one Pages artifact upload"),
    "Material reference writes to site/": (_reference_writes_to_site, "write outside the published directory"),
    "extra job that uploads a Pages artifact": (_extra_job, "unexpected job set"),
    "deploy step added to the build job": (_deploy_step_in_build, "must not deploy"),
    "deploy no longer needs build": (_set(_deploy, "needs", ["build", "other"]), "deploy must need exactly"),
    "deploy dependency removed": (_set(_deploy, "needs", _DELETE), "deploy must need exactly"),
    "deploy runs on pull requests": (_set(_deploy, "if", "github.event_name == 'pull_request'"), "deploy condition changed"),
    "deploy not gated on DOCS_PUBLISH": (_set(_deploy, "if", "github.event_name == 'push'"), "deploy condition changed"),
    "deploy condition removed": (_set(_deploy, "if", _DELETE), "deploy condition changed"),
    "build job gains pages permission": (_set(lambda wf: wf["jobs"]["build"]["permissions"], "pages", "write"), "build job permissions"),
    "workflow permissions widened": (_set(lambda wf: wf["permissions"], "contents", "write"), "workflow-level permissions"),
}


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_guard_detects_regression(name):
    mutate, expected = MUTATIONS[name]
    broken = copy.deepcopy(load())
    mutate(broken)
    problems = workflow_violations(broken)
    assert any(expected in p for p in problems), problems


def test_every_mutation_really_changes_the_workflow():
    original = load()
    for name, (mutate, _expected) in MUTATIONS.items():
        broken = copy.deepcopy(original)
        mutate(broken)
        assert broken != original, name


# --- failing closed on a missing browser ---------------------------------------


def _load_search_module():
    spec = importlib.util.spec_from_file_location("check_docs_search", ROOT / "scripts" / "check_docs_search.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_playwright_fails_the_gate(monkeypatch, tmp_path, capsys):
    search = _load_search_module()
    (tmp_path / "index.html").write_text("x", "utf-8")
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    monkeypatch.setattr("sys.argv", ["check_docs_search.py", "--site", str(tmp_path)])
    assert search.main() == 2
    assert "playwright is not installed" in capsys.readouterr().err


def test_missing_chromium_fails_the_gate(monkeypatch, tmp_path, capsys):
    pytest.importorskip("playwright.sync_api")
    search = _load_search_module()
    (tmp_path / "index.html").write_text("x", "utf-8")
    (tmp_path / "search.json").write_text('{"items": [1]}', "utf-8")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "no-browsers"))
    monkeypatch.setattr("sys.argv", ["check_docs_search.py", "--site", str(tmp_path)])
    assert search.main() == 2
    assert "Chromium cannot be launched" in capsys.readouterr().err
