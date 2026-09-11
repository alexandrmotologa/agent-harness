import json
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionDecision(StrEnum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    MODIFY = "MODIFY"


class InterventionResponse(BaseModel):
    decision: ActionDecision
    modified_arguments: dict[str, Any] | None = None
    denial_reason: str | None = None


class ApprovalPolicy(BaseModel):
    require_all: bool = False
    require_commands: bool = True
    require_writes: bool = False
    flagged_command_keywords: list[str] = Field(
        default_factory=lambda: [
            "rm",
            "del",
            "rmdir",
            "format",
            "install",
            "git push",
            "curl",
            "wget",
            "drop",
        ]
    )

    def should_require_approval(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        if self.require_all:
            return True

        if tool_name == "execute_command" and self.require_commands:
            command = arguments.get("command", "").lower()
            if any(kw in command for kw in self.flagged_command_keywords):
                return True

        if tool_name == "write_file" and self.require_writes:
            return True

        return False


class BaseInterventionHandler(ABC):
    @abstractmethod
    async def handle_intervention(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        trigger_reason: str,
    ) -> InterventionResponse:
        """Prompt operator or system to approve, deny, or modify a tool invocation."""


class CLIInterventionHandler(BaseInterventionHandler):
    """Interactive human approval handler using console prompts."""

    async def handle_intervention(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        trigger_reason: str,
    ) -> InterventionResponse:
        import asyncio

        from rich.console import Console
        from rich.panel import Panel
        from rich.prompt import Prompt

        console = Console()

        def prompt_user() -> InterventionResponse:
            console.print(
                Panel(
                    f"[bold yellow]Tool:[/bold yellow] {tool_name}\n"
                    f"[bold yellow]Arguments:[/bold yellow] {json.dumps(arguments, indent=2)}\n"
                    f"[bold yellow]Trigger:[/bold yellow] {trigger_reason}",
                    title="Human-in-the-Loop Approval Required",
                    border_style="yellow",
                )
            )

            choice = Prompt.ask(
                "Action",
                choices=["a", "d", "e"],
                default="a",
            ).lower()

            if choice == "a":
                return InterventionResponse(decision=ActionDecision.APPROVE)
            elif choice == "d":
                reason = Prompt.ask("Enter reason for denial", default="Action denied by operator")
                return InterventionResponse(
                    decision=ActionDecision.DENY,
                    denial_reason=reason,
                )
            else:
                raw_json = Prompt.ask("Enter modified JSON arguments")
                try:
                    modified = json.loads(raw_json)
                    return InterventionResponse(
                        decision=ActionDecision.MODIFY,
                        modified_arguments=modified,
                    )
                except Exception as exc:
                    console.print(f"[red]Invalid JSON ({exc}), proceeding with original arguments.[/red]")
                    return InterventionResponse(decision=ActionDecision.APPROVE)

        return await asyncio.to_thread(prompt_user)
