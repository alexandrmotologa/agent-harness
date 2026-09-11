from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class SandboxType(StrEnum):
    PROCESS = "process"
    WASM = "wasm"
    DOCKER = "docker"


class ProviderType(StrEnum):
    MOCK = "mock"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


class GuardrailConfig(BaseModel):
    max_steps: int = Field(default=30, description="Maximum iterations before halting")
    max_budget_usd: float = Field(default=1.0, description="Maximum dollar budget for LLM calls")
    max_repeated_calls: int = Field(
        default=3, description="Threshold for identical repeated tool invocations"
    )
    max_context_tokens: int = Field(default=100_000, description="Context window token ceiling")


class SandboxConfig(BaseModel):
    sandbox_type: SandboxType = Field(default=SandboxType.PROCESS)
    workspace_dir: Path = Field(default_factory=lambda: Path(".harness/workspace").resolve())
    timeout_seconds: float = Field(default=15.0, description="Per-command execution timeout")
    memory_limit_mb: int = Field(default=256, description="Memory ceiling in megabytes")
    cpu_limit: float = Field(default=0.5, description="CPU core quota")
    allow_network: bool = Field(default=False, description="Whether network access is permitted")


class HarnessConfig(BaseModel):
    provider: ProviderType = Field(default=ProviderType.MOCK)
    model: str = Field(default="claude-3-7-sonnet")
    api_key: str | None = Field(default=None)
    api_base_url: str | None = Field(default=None)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    guardrails: GuardrailConfig = Field(default_factory=GuardrailConfig)
    storage_dir: Path = Field(default_factory=lambda: Path(".harness").resolve())
