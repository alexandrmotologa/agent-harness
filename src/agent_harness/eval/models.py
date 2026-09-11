from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AssertionType(StrEnum):
    FILE_EXISTS = "file_exists"
    FILE_CONTAINS = "file_contains"
    FILE_NOT_CONTAINS = "file_not_contains"
    MAX_STEPS = "max_steps"
    MAX_COST_USD = "max_cost_usd"
    TOOL_INVOKED = "tool_invoked"
    ANSWER_CONTAINS = "answer_contains"


class EvalAssertion(BaseModel):
    assertion_type: AssertionType
    target: str = ""
    expected: Any = None


class EvalTestCase(BaseModel):
    id: str
    name: str
    goal: str
    initial_files: dict[str, str] = Field(default_factory=dict)
    assertions: list[EvalAssertion] = Field(default_factory=list)
    max_steps: int = 20


class EvalSuite(BaseModel):
    name: str
    description: str = ""
    cases: list[EvalTestCase] = Field(default_factory=list)


class AssertionCheckResult(BaseModel):
    assertion_type: AssertionType
    target: str
    passed: bool
    message: str


class TestCaseResult(BaseModel):
    case_id: str
    name: str
    passed: bool
    steps_taken: int
    cost_usd: float
    duration_seconds: float
    checks: list[AssertionCheckResult] = Field(default_factory=list)
    error: str | None = None


class EvalSuiteReport(BaseModel):
    suite_name: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    total_cost_usd: float
    total_duration_seconds: float
    results: list[TestCaseResult] = Field(default_factory=list)
