"""
Programmatic usage example of AgentHarness Python SDK.
Demonstrates custom tool registration, sandboxed execution, and HTML report export.
"""

import asyncio
from pathlib import Path

from agent_harness.config import GuardrailConfig, HarnessConfig
from agent_harness.core.loop import AutonomousLoop
from agent_harness.core.tool_registry import ToolRegistry
from agent_harness.export.report import generate_html_report, generate_mermaid_diagram
from agent_harness.providers.base import LLMResponse, LLMToolCall
from agent_harness.providers.mock import MockProvider
from agent_harness.sandbox.process_sandbox import ProcessSandbox


async def main():
    workspace = Path("./.harness/demo_workspace").resolve()
    sandbox = ProcessSandbox(workspace_dir=workspace)

    # 1. Custom tool registry
    tools = ToolRegistry()

    @tools.register(description="Compute mathematical equations securely.")
    def math_eval(expression: str) -> str:
        # Restricted safe evaluator
        return str(eval(expression, {"__builtins__": {}}))

    # 2. Mock or frontier provider (e.g. AnthropicProvider, OpenAIProvider, GeminiProvider)
    provider = MockProvider(
        responses=[
            LLMResponse(
                content="I will compute the result and write it to output.txt",
                tool_calls=[
                    LLMToolCall(id="tc_1", name="math_eval", arguments={"expression": "128 * 4 + 16"}),
                ],
            ),
            LLMResponse(
                content="Writing result to workspace",
                tool_calls=[
                    LLMToolCall(id="tc_2", name="write_file", arguments={"path": "result.txt", "content": "528\n"}),
                ],
            ),
            LLMResponse(
                content="Task finished successfully.",
                tool_calls=[
                    LLMToolCall(id="tc_3", name="finish_task", arguments={"answer": "Saved calculated value 528 into result.txt"}),
                ],
            ),
        ]
    )

    # 3. Initialize Autonomous Loop with guardrails
    config = HarnessConfig(
        guardrails=GuardrailConfig(max_steps=10, max_budget_usd=0.50)
    )

    loop = AutonomousLoop(
        goal="Calculate 128 * 4 + 16 and save to result.txt",
        sandbox=sandbox,
        provider=provider,
        tool_registry=tools,
        config=config,
    )

    # 4. Execute the loop
    result = await loop.run()
    print(f"Execution Success: {result.success}")
    print(f"Steps Taken: {result.steps_taken}")
    print(f"Final Answer: {result.final_answer}")

    # 5. Export Decision DAG to standalone HTML and Mermaid
    report_file = Path("./.harness/demo_report.html")
    generate_html_report(loop.dag, report_file)
    print(f"Generated standalone report: {report_file}")

    mermaid_file = Path("./.harness/demo_dag.mmd")
    generate_mermaid_diagram(loop.dag, mermaid_file)
    print(f"Generated Mermaid diagram: {mermaid_file}")


if __name__ == "__main__":
    asyncio.run(main())
