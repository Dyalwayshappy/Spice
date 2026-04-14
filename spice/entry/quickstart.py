from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from spice.decision import (
    DEFAULT_LOCAL_DECISION_PROFILE,
    DEFAULT_LOCAL_SUPPORT_PROFILE,
    DecisionProfileInitReport,
    explain_decision_guidance,
    init_decision_profile,
    load_default_decision_support,
)
from spice.entry.init_domain import InitDomainReport, run_init_domain_from_spec
from spice.entry.scaffold import write_scaffold
from spice.entry.spec import DomainSpec


QUICKSTART_DEFAULT_OUTPUT = Path(".spice/quickstart")
QUICKSTART_LLM_DEFAULT_OUTPUT = Path(".spice/quickstart_llm")
QUICKSTART_REPORT_SCHEMA_VERSION = "spice.quickstart.report.v1"
INTEGRATED_QUICKSTART_REPORT_SCHEMA_VERSION = "spice.quickstart.integrated_report.v1"


@dataclass(slots=True)
class QuickstartReport:
    output_dir: Path
    domain_id: str
    domain_spec_path: Path
    scaffold_files: list[str]
    demo_ran: bool
    demo_command: list[str]
    demo_exit_code: int | None
    stdout_log_path: Path
    stderr_log_path: Path
    last_cycle: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": QUICKSTART_REPORT_SCHEMA_VERSION,
            "domain_id": self.domain_id,
            "output_dir": str(self.output_dir),
            "domain_spec_path": str(self.domain_spec_path),
            "scaffold_files": list(self.scaffold_files),
            "demo_ran": self.demo_ran,
            "demo_command": list(self.demo_command),
            "demo_exit_code": self.demo_exit_code,
            "stdout_log_path": str(self.stdout_log_path),
            "stderr_log_path": str(self.stderr_log_path),
            "last_cycle": dict(self.last_cycle) if isinstance(self.last_cycle, dict) else None,
        }


@dataclass(slots=True)
class IntegratedQuickstartReport:
    core_report: QuickstartReport
    decision_profile_report: DecisionProfileInitReport
    decision_explain_report: dict[str, Any]
    llm_report: InitDomainReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": INTEGRATED_QUICKSTART_REPORT_SCHEMA_VERSION,
            "core": self.core_report.to_dict(),
            "decision_profile": self.decision_profile_report.to_payload(),
            "decision_explain": dict(self.decision_explain_report),
            "llm_runtime": self.llm_report.to_dict(),
        }


def load_builtin_quickstart_spec() -> DomainSpec:
    asset = files("spice.entry.assets").joinpath("quickstart.domain_spec.json")
    payload = json.loads(asset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Built-in quickstart spec payload must be an object.")
    return DomainSpec.from_dict(payload)


def run_quickstart(
    *,
    output_dir: str | Path = QUICKSTART_DEFAULT_OUTPUT,
    force: bool = False,
    no_run: bool = False,
) -> QuickstartReport:
    output_path = Path(output_dir)
    spec = load_builtin_quickstart_spec()

    _prepare_output_dir(output_path, force=force)
    written_paths = write_scaffold(spec, output_path, overwrite=False)
    scaffold_files = sorted(str(path.relative_to(output_path)) for path in written_paths)

    artifacts_dir = output_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    stdout_log_path = artifacts_dir / "run_demo.stdout.log"
    stderr_log_path = artifacts_dir / "run_demo.stderr.log"
    demo_command = [sys.executable, "run_demo.py"]

    demo_exit_code: int | None
    last_cycle: dict[str, Any] | None
    if no_run:
        demo_exit_code = None
        last_cycle = None
        stdout_log_path.write_text("demo skipped (--no-run)\n", encoding="utf-8")
        stderr_log_path.write_text("", encoding="utf-8")
    else:
        completed = _run_generated_demo(output_path, command=demo_command)
        demo_exit_code = int(completed.returncode)
        stdout_log_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_log_path.write_text(completed.stderr or "", encoding="utf-8")
        last_cycle = _extract_last_cycle(completed.stdout or "")
        if completed.returncode != 0:
            raise RuntimeError(
                "Generated quickstart demo failed with exit code "
                f"{completed.returncode}. See logs under {artifacts_dir}."
            )

    report = QuickstartReport(
        output_dir=output_path,
        domain_id=spec.domain.id,
        domain_spec_path=output_path / "domain_spec.json",
        scaffold_files=scaffold_files,
        demo_ran=not no_run,
        demo_command=demo_command,
        demo_exit_code=demo_exit_code,
        stdout_log_path=stdout_log_path,
        stderr_log_path=stderr_log_path,
        last_cycle=last_cycle,
    )
    summary_path = artifacts_dir / "quickstart_summary.json"
    summary_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def run_integrated_quickstart(
    *,
    output_dir: str | Path = QUICKSTART_DEFAULT_OUTPUT,
    llm_output_dir: str | Path = QUICKSTART_LLM_DEFAULT_OUTPUT,
    decision_profile_path: str | Path = DEFAULT_LOCAL_DECISION_PROFILE,
    support_output_path: str | Path = DEFAULT_LOCAL_SUPPORT_PROFILE,
    force: bool = False,
    no_run: bool = False,
) -> IntegratedQuickstartReport:
    output_path = Path(output_dir)
    llm_output_path = Path(llm_output_dir)
    profile_path = Path(decision_profile_path)
    support_path = Path(support_output_path)
    _preflight_integrated_outputs(
        paths=(output_path, llm_output_path, profile_path, support_path),
        force=force,
    )

    core_report = run_quickstart(
        output_dir=output_path,
        force=force,
        no_run=no_run,
    )
    decision_profile_report = init_decision_profile(
        output=profile_path,
        support_output=support_path,
        force=force,
        include_support=True,
    )
    decision_explain_report = explain_decision_guidance(
        decision_profile_report.profile_path,
        support=load_default_decision_support(),
    )
    llm_report = run_init_domain_from_spec(
        spec=load_builtin_quickstart_spec(),
        output_dir=llm_output_path,
        force=force,
        no_run=no_run,
        with_llm=True,
        interactive=False,
        from_spec_path=core_report.domain_spec_path,
    )

    artifacts_dir = output_path / "artifacts"
    integrated_summary_path = artifacts_dir / "integrated_quickstart_summary.json"
    integrated_report = IntegratedQuickstartReport(
        core_report=core_report,
        decision_profile_report=decision_profile_report,
        decision_explain_report=decision_explain_report,
        llm_report=llm_report,
    )
    integrated_summary_path.write_text(
        json.dumps(
            integrated_report.to_dict(),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return integrated_report


def _prepare_output_dir(output_dir: Path, *, force: bool) -> None:
    if output_dir.exists():
        if not force:
            raise FileExistsError(
                f"Quickstart output directory already exists: {output_dir}. "
                "Use --force to replace it."
            )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def _preflight_integrated_outputs(*, paths: tuple[Path, ...], force: bool) -> None:
    if force:
        return
    existing = [path for path in paths if path.exists()]
    if existing:
        rendered = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"Quickstart output already exists: {rendered}. Use --force to replace it."
        )


def _run_generated_demo(
    output_dir: Path,
    *,
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[2])
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{package_root}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else package_root
    )
    return subprocess.run(
        command,
        cwd=output_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _extract_last_cycle(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if not line.startswith("last_cycle="):
            continue
        raw = line.split("=", 1)[1].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
        return None
    return None
