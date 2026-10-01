import asyncio
import re
import shutil
import tempfile
import time
from pathlib import Path

from ..config import GuardrailConfig, HarnessConfig
from ..core.loop import AutonomousLoop
from ..graph.decision_dag import NodeType
from ..providers.base import BaseProvider
from ..sandbox.process_sandbox import ProcessSandbox
from .models import (
    AssertionCheckResult,
    AssertionType,
    EvalSuite,
    EvalSuiteReport,
    EvalTestCase,
    TestCaseResult,
)


class EvalRunner:
    def __init__(self, provider: BaseProvider, base_work_dir: Path | None = None):
        self.provider = provider
        self.base_work_dir = base_work_dir

    async def run_case(self, case: EvalTestCase) -> TestCaseResult:
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"eval_{case.id}_"))
        sandbox = ProcessSandbox(workspace_dir=tmp_dir)

        # Prepopulate initial files
        for rel_path, content in case.initial_files.items():
            sandbox.write_file(rel_path, content)

        config = HarnessConfig(
            guardrails=GuardrailConfig(max_steps=case.max_steps)
        )
        loop = AutonomousLoop(
            goal=case.goal,
            sandbox=sandbox,
            provider=self.provider,
            config=config,
        )

        start_time = time.perf_counter()
        run_res = await loop.run()
        duration = time.perf_counter() - start_time

        # Check assertions
        checks: list[AssertionCheckResult] = []
        all_passed = run_res.success

        for ass in case.assertions:
            passed = True
            msg = "Passed"

            if ass.assertion_type == AssertionType.FILE_EXISTS:
                files = sandbox.list_files()
                passed = ass.target in files
                msg = f"File '{ass.target}' {'exists' if passed else 'missing'}"

            elif ass.assertion_type == AssertionType.FILE_CONTAINS:
                try:
                    content = sandbox.read_file(ass.target)
                    passed = str(ass.expected) in content
                    msg = f"Substring '{ass.expected}' {'found' if passed else 'not found'} in '{ass.target}'"
                except Exception as exc:
                    passed = False
                    msg = f"Cannot read '{ass.target}': {exc}"

            elif ass.assertion_type == AssertionType.FILE_NOT_CONTAINS:
                try:
                    content = sandbox.read_file(ass.target)
                    passed = str(ass.expected) not in content
                    msg = f"Forbidden substring '{ass.expected}' {'absent' if passed else 'present'} in '{ass.target}'"
                except Exception:
                    passed = True
                    msg = f"File '{ass.target}' does not exist"

            elif ass.assertion_type == AssertionType.REGEX_MATCH:
                try:
                    content = sandbox.read_file(ass.target) if ass.target else run_res.final_answer
                    passed = bool(re.search(str(ass.expected), content))
                    msg = f"Pattern r'{ass.expected}' {'matched' if passed else 'did not match'}"
                except Exception as exc:
                    passed = False
                    msg = f"Regex error on '{ass.target}': {exc}"

            elif ass.assertion_type == AssertionType.MAX_STEPS:
                passed = run_res.steps_taken <= int(ass.expected)
                msg = f"Steps: {run_res.steps_taken} (max: {ass.expected})"

            elif ass.assertion_type == AssertionType.MAX_COST_USD:
                passed = run_res.total_cost_usd <= float(ass.expected)
                msg = f"Cost: ${run_res.total_cost_usd:.4f} (max: ${float(ass.expected):.4f})"

            elif ass.assertion_type == AssertionType.TOOL_INVOKED:
                invoked_tools = [
                    n.payload.get("tool_name")
                    for n in loop.dag.nodes_by_id.values()
                    if n.node_type == NodeType.TOOL_CALL
                ]
                passed = ass.target in invoked_tools
                msg = f"Tool '{ass.target}' was {'invoked' if passed else 'never called'}"

            elif ass.assertion_type == AssertionType.ANSWER_CONTAINS:
                passed = str(ass.expected).lower() in run_res.final_answer.lower()
                msg = f"Answer {'contains' if passed else 'does not contain'} '{ass.expected}'"

            elif ass.assertion_type == AssertionType.STDERR_EMPTY:
                observations = [
                    n.payload.get("output", "")
                    for n in loop.dag.nodes_by_id.values()
                    if n.node_type == NodeType.OBSERVATION
                ]
                has_error = any("Error:" in str(o) or "Traceback" in str(o) for o in observations)
                passed = not has_error
                msg = "Stderr/errors absent" if passed else "Execution generated errors"

            elif ass.assertion_type == AssertionType.EXIT_CODE:
                passed = run_res.success == (int(ass.expected) == 0)
                msg = f"Exit code {'matched' if passed else 'mismatched'}"

            if not passed:
                all_passed = False

            checks.append(
                AssertionCheckResult(
                    assertion_type=ass.assertion_type,
                    target=ass.target,
                    passed=passed,
                    message=msg,
                )
            )

        # Cleanup temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return TestCaseResult(
            case_id=case.id,
            name=case.name,
            passed=all_passed,
            steps_taken=run_res.steps_taken,
            cost_usd=run_res.total_cost_usd,
            duration_seconds=duration,
            checks=checks,
            error=run_res.error_message,
        )

    async def run_suite(self, suite: EvalSuite, concurrency: int = 4) -> EvalSuiteReport:
        sem = asyncio.Semaphore(concurrency)

        async def _bounded_run(c: EvalTestCase) -> TestCaseResult:
            async with sem:
                return await self.run_case(c)

        start_time = time.perf_counter()
        results: list[TestCaseResult] = await asyncio.gather(
            *[_bounded_run(case) for case in suite.cases]
        )
        total_duration = time.perf_counter() - start_time
        total_cost = sum(r.cost_usd for r in results)

        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count

        return EvalSuiteReport(
            suite_name=suite.name,
            total_cases=len(suite.cases),
            passed_cases=passed_count,
            failed_cases=failed_count,
            total_cost_usd=total_cost,
            total_duration_seconds=total_duration,
            results=results,
        )
