import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from ..config import HarnessConfig
from ..graph.checkpoint import CheckpointManager
from ..graph.decision_dag import DecisionDAG, NodeType
from ..providers.base import BaseProvider
from ..sandbox.base import BaseSandbox
from .context_window import ContextWindowManager
from .guardrails import (
    BudgetController,
    BudgetExceededError,
    InfiniteLoopDetector,
    InfiniteLoopError,
)
from .hitl import ActionDecision, ApprovalPolicy, BaseInterventionHandler
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an autonomous AI agent running inside AgentHarness, a zero-trust sandboxed execution environment.
You have access to tools for running shell commands and modifying files inside your isolated workspace.
Always inspect existing files before writing code. Validate your work by running commands.
When you have completely solved the user goal, invoke the 'finish_task' tool with your final answer."""


class RunResult(BaseModel):
    run_id: str
    goal: str
    branch_id: str = "main"
    success: bool = True
    final_answer: str = ""
    error_message: str | None = None
    steps_taken: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    dag: dict[str, Any] = Field(default_factory=dict)


class AutonomousLoop:
    def __init__(
        self,
        goal: str,
        sandbox: BaseSandbox,
        provider: BaseProvider,
        config: HarnessConfig | None = None,
        tool_registry: ToolRegistry | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
        existing_dag: DecisionDAG | None = None,
        start_node_id: str | None = None,
        branch_id: str = "main",
        hitl_handler: BaseInterventionHandler | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ):
        self.run_id = existing_dag.run_id if existing_dag else f"run_{uuid.uuid4().hex[:8]}"
        self.goal = goal
        self.sandbox = sandbox
        self.provider = provider
        self.config = config or HarnessConfig()
        self.event_callback = event_callback
        self.branch_id = branch_id
        self.hitl_handler = hitl_handler
        self.approval_policy = approval_policy or ApprovalPolicy()

        # Setup Decision DAG
        self.dag = existing_dag or DecisionDAG(run_id=self.run_id, goal=self.goal)
        self.current_parent_id = start_node_id or self.dag.current_leaf_id

        # Setup Checkpoint manager using sandbox's filesystem jail if available
        jail = getattr(self.sandbox, "jail", None)
        self.checkpoint_mgr = CheckpointManager(jail) if jail else None

        # Setup Guardrails and Context
        self.loop_detector = InfiniteLoopDetector(
            threshold=self.config.guardrails.max_repeated_calls
        )
        self.budget_controller = BudgetController(
            max_budget_usd=self.config.guardrails.max_budget_usd,
            model_name=self.config.model,
        )
        self.context_mgr = ContextWindowManager(
            max_tokens=self.config.guardrails.max_context_tokens
        )

        # Setup Tool Registry
        self.tools = tool_registry or ToolRegistry()
        self._register_default_tools()

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self.event_callback:
            try:
                self.event_callback(event_type, data)
            except Exception as exc:
                logger.debug("Event callback error: %s", exc)

    def _register_default_tools(self) -> None:
        """Register default sandbox execution and filesystem tools."""
        sandbox = self.sandbox

        @self.tools.register(
            name="execute_command",
            description="Run a shell command inside the sandboxed workspace directory.",
        )
        async def execute_command(command: str) -> str:
            res = await sandbox.execute_command(command)
            return res.format_output()

        @self.tools.register(
            name="read_file",
            description="Read the complete text contents of a file inside the workspace.",
        )
        def read_file(path: str) -> str:
            return sandbox.read_file(path)

        @self.tools.register(
            name="write_file",
            description="Write text content to a file inside the workspace.",
        )
        def write_file(path: str, content: str) -> str:
            sandbox.write_file(path, content)
            return f"Successfully wrote {len(content)} characters to '{path}'"

        @self.tools.register(
            name="list_files",
            description="List relative paths of files inside the workspace directory.",
        )
        def list_files(directory: str = ".") -> list[str]:
            return sandbox.list_files(directory)

        @self.tools.register(
            name="finish_task",
            description="Signal that the user goal has been completed and deliver the final answer.",
        )
        def finish_task(answer: str) -> str:
            return f"Task completed: {answer}"

    async def run(self) -> RunResult:
        """Execute the autonomous agent loop until completion or guardrail stop."""
        start_time = time.perf_counter()
        self._emit("run_started", {"run_id": self.run_id, "goal": self.goal})

        # Initialize conversation messages if starting fresh
        if not self.context_mgr.messages:
            self.context_mgr.add_message("system", SYSTEM_PROMPT)
            self.context_mgr.add_message("user", f"Goal: {self.goal}")

        step = 0
        final_answer = ""
        error_message = None
        success = True

        while step < self.config.guardrails.max_steps:
            step += 1
            self._emit("step_started", {"step": step, "branch_id": self.branch_id})

            # Check context window size
            self.context_mgr.prune_if_needed()

            # Format tool list for provider
            tools_for_provider = self.tools.to_anthropic_tools()

            # Request completion from provider
            try:
                response = await self.provider.chat(
                    messages=self.context_mgr.to_dict_list(),
                    tools=tools_for_provider,
                    system=SYSTEM_PROMPT,
                )
            except Exception as exc:
                error_message = f"LLM Provider error: {exc}"
                success = False
                break

            # Update token usage and budget guardrails
            try:
                self.budget_controller.record_and_check(
                    response.prompt_tokens,
                    response.completion_tokens,
                )
                self.context_mgr.record_usage(
                    response.prompt_tokens,
                    response.completion_tokens,
                )
            except BudgetExceededError as budget_err:
                error_message = str(budget_err)
                success = False
                break

            step_cost = self.budget_controller.calculate_cost(
                response.prompt_tokens,
                response.completion_tokens,
            )

            # Record thought if provided
            if response.content.strip():
                thought_node = self.dag.create_child_node(
                    node_type=NodeType.THOUGHT,
                    title=f"Thought: Step {step}",
                    payload={"thought": response.content},
                    parent_id=self.current_parent_id,
                    branch_id=self.branch_id,
                    token_usage=response.completion_tokens,
                    cost_usd=step_cost,
                )
                self.current_parent_id = thought_node.id
                self._emit("thought", {"step": step, "content": response.content})

            # If no tool calls, treat as assistant response
            if not response.tool_calls:
                self.context_mgr.add_message("assistant", response.content)
                final_answer = response.content
                final_node = self.dag.create_child_node(
                    node_type=NodeType.FINAL_ANSWER,
                    title="Final Answer",
                    payload={"answer": final_answer},
                    parent_id=self.current_parent_id,
                    branch_id=self.branch_id,
                )
                self.current_parent_id = final_node.id
                break

            # Add assistant message with tool calls
            raw_tool_calls = [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
                for tc in response.tool_calls
            ]
            self.context_mgr.add_message(
                "assistant",
                response.content,
                tool_calls=raw_tool_calls,
            )

            # Execute each requested tool call
            is_task_finished = False
            for tc in response.tool_calls:
                # Infinite loop guardrail verification
                try:
                    warning = self.loop_detector.record_and_check(tc.name, tc.arguments)
                    if warning:
                        self._emit("guardrail_warning", {"warning": warning})
                except InfiniteLoopError as loop_err:
                    error_message = str(loop_err)
                    success = False
                    break

                # Human-in-the-Loop Interception
                target_arguments = tc.arguments
                if self.hitl_handler and self.approval_policy.should_require_approval(tc.name, tc.arguments):
                    self._emit("hitl_required", {"tool": tc.name, "arguments": tc.arguments})
                    intervention = await self.hitl_handler.handle_intervention(
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        trigger_reason=f"Approval policy triggered for {tc.name}",
                    )

                    if intervention.decision == ActionDecision.DENY:
                        denial_msg = f"[Action Denied by Operator]: {intervention.denial_reason or 'No reason specified'}"
                        int_node = self.dag.create_child_node(
                            node_type=NodeType.INTERVENTION,
                            title=f"Human Denied: {tc.name}",
                            payload={"tool_name": tc.name, "denial_reason": intervention.denial_reason},
                            parent_id=self.current_parent_id,
                            branch_id=self.branch_id,
                        )
                        self.current_parent_id = int_node.id
                        self.context_mgr.add_message(role="tool", content=denial_msg, tool_call_id=tc.id, name=tc.name)
                        self._emit("observation", {"tool": tc.name, "output": denial_msg})
                        continue
                    elif intervention.decision == ActionDecision.MODIFY and intervention.modified_arguments:
                        target_arguments = intervention.modified_arguments
                        int_node = self.dag.create_child_node(
                            node_type=NodeType.INTERVENTION,
                            title=f"Human Modified: {tc.name}",
                            payload={"original": tc.arguments, "modified": target_arguments},
                            parent_id=self.current_parent_id,
                            branch_id=self.branch_id,
                        )
                        self.current_parent_id = int_node.id

                # Create TOOL_CALL node in DAG
                call_node = self.dag.create_child_node(
                    node_type=NodeType.TOOL_CALL,
                    title=f"Tool Call: {tc.name}",
                    payload={"tool_name": tc.name, "arguments": target_arguments, "call_id": tc.id},
                    parent_id=self.current_parent_id,
                    branch_id=self.branch_id,
                )
                self.current_parent_id = call_node.id
                self._emit("tool_call", {"tool": tc.name, "arguments": target_arguments})

                # Execute tool
                tool_res = await self.tools.execute(tc.name, target_arguments)

                # Capture checkpoint if checkpoint manager is active
                checkpoint_id = None
                if self.checkpoint_mgr:
                    checkpoint_id = self.checkpoint_mgr.capture_checkpoint(call_node.id, step)

                # Create OBSERVATION node in DAG
                obs_node = self.dag.create_child_node(
                    node_type=NodeType.OBSERVATION,
                    title=f"Observation: {tc.name}",
                    payload={"output": tool_res.output, "is_error": tool_res.is_error},
                    parent_id=self.current_parent_id,
                    branch_id=self.branch_id,
                    checkpoint_id=checkpoint_id,
                )
                self.current_parent_id = obs_node.id
                self._emit("observation", {"tool": tc.name, "output": tool_res.output})

                # Append tool observation to message context
                self.context_mgr.add_message(
                    role="tool",
                    content=tool_res.output,
                    tool_call_id=tc.id,
                    name=tc.name,
                )

                if tc.name == "finish_task":
                    final_answer = tc.arguments.get("answer", tool_res.output)
                    is_task_finished = True

            if not success or is_task_finished:
                if is_task_finished:
                    final_node = self.dag.create_child_node(
                        node_type=NodeType.FINAL_ANSWER,
                        title="Final Answer",
                        payload={"answer": final_answer},
                        parent_id=self.current_parent_id,
                        branch_id=self.branch_id,
                    )
                    self.current_parent_id = final_node.id
                break

        if step >= self.config.guardrails.max_steps and not final_answer:
            error_message = f"Step limit of {self.config.guardrails.max_steps} exceeded without task completion."
            success = False

        duration = time.perf_counter() - start_time
        total_tokens = (
            self.budget_controller.cumulative_prompt_tokens
            + self.budget_controller.cumulative_completion_tokens
        )
        total_cost = self.budget_controller.total_cost_usd

        result = RunResult(
            run_id=self.run_id,
            goal=self.goal,
            branch_id=self.branch_id,
            success=success,
            final_answer=final_answer,
            error_message=error_message,
            steps_taken=step,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            duration_seconds=duration,
            dag=self.dag.to_dict(),
        )

        self._emit("run_completed", result.model_dump())
        return result
