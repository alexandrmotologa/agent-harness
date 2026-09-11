import asyncio
import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel, create_model


class ToolCallResult(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    output: str
    is_error: bool = False
    execution_time_ms: float = 0.0


class ToolDefinition:
    def __init__(
        self,
        name: str,
        description: str,
        func: Callable[..., Any],
        args_model: type[BaseModel],
    ):
        self.name = name
        self.description = description
        self.func = func
        self.args_model = args_model
        self.is_async = asyncio.iscoroutinefunction(func)

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return the JSON schema representing the tool parameters."""
        schema = self.args_model.model_json_schema()
        # Clean schema for strict tool calling compatibility
        schema.pop("title", None)
        return schema

    def to_anthropic(self) -> dict[str, Any]:
        """Convert to Anthropic Claude tool calling definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_parameters_schema(),
        }

    def to_openai(self) -> dict[str, Any]:
        """Convert to OpenAI function calling definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema(),
            },
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolCallResult:
        """Validate arguments against schema and execute the function."""
        import time

        start_time = time.perf_counter()
        try:
            validated_args = self.args_model.model_validate(arguments)
            kwargs = validated_args.model_dump()
            if self.is_async:
                result = await self.func(**kwargs)
            else:
                result = await asyncio.to_thread(self.func, **kwargs)

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolCallResult(
                tool_name=self.name,
                arguments=arguments,
                output=str(result),
                is_error=False,
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolCallResult(
                tool_name=self.name,
                arguments=arguments,
                output=f"Tool execution error: {type(exc).__name__}: {exc}",
                is_error=True,
                execution_time_ms=elapsed_ms,
            )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator to register a function as an agent tool."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            tool_desc = description or inspect.getdoc(func) or f"Tool: {tool_name}"

            # Introspect function parameters and types
            sig = inspect.signature(func)
            type_hints = get_type_hints(func)

            fields: dict[str, Any] = {}
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue
                param_type = type_hints.get(param_name, Any)
                if param.default is inspect.Parameter.empty:
                    fields[param_name] = (param_type, ...)
                else:
                    fields[param_name] = (param_type, param.default)

            args_model = create_model(f"{tool_name}_Args", **fields)
            tool_def = ToolDefinition(
                name=tool_name,
                description=tool_desc.strip(),
                func=func,
                args_model=args_model,
            )
            self._tools[tool_name] = tool_def
            return func

        return decorator

    def add_tool(self, tool_def: ToolDefinition) -> None:
        self._tools[tool_def.name] = tool_def

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        return [tool.to_anthropic() for tool in self._tools.values()]

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai() for tool in self._tools.values()]

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolCallResult(
                tool_name=tool_name,
                arguments=arguments,
                output=f"Error: Tool '{tool_name}' not found. Available tools: {list(self._tools.keys())}",
                is_error=True,
            )
        return await tool.execute(arguments)
