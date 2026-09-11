# Time-Travel Debugger and Branching Engine

Agent workflows often fail due to early misconceptions: a hallucinated variable name or an invalid CLI argument at step 2 cascades into repeated errors down the line. The time-travel debugger allows developers to rewind to any past step, supply corrected instructions, and branch execution without losing earlier history.

## Causal Trajectory Model

In AgentHarness, each step corresponds to an immutable node in the decision graph:

```
Step 1: Goal Initialized
   |
   v
Step 2: Read config.yaml
   |
   +---> Step 3A: Attempted invalid command (Failed)
   |        |
   |        v
   |     Step 4A: Hallucinated recovery (Dead end)
   |
   +---> Step 3B: Rewound with instruction "Use JSON parser instead"
            |
            v
         Step 4B: Successful file parse and test pass
```

The original branch (`Branch A`) remains intact in the decision graph for auditing and comparison. The new branch (`Branch B`) receives a pointer to the parent checkpoint and proceeds independently.

## Rewind Mechanics

When a rewind command is executed:

1. Target selection: the developer specifies either a step index or a specific node identifier.
2. Checkpoint restoration: the `FilesystemJail` resets the workspace to the exact snapshot recorded at the target step. Any files created or modified by later steps on the old branch are reverted.
3. Branch creation: a new branch label is created in the DAG with its parent set to the target node.
4. Instruction injection: optional modified user instructions, system prompts, or mock tool outputs are appended to the context.
5. Resumed execution: the autonomous coordinator continues running from the new node.

## Cross-Branch Diffing

AgentHarness can compare two execution branches across several dimensions:

- Step count: total reasoning iterations taken to complete the task.
- Token expenditure: prompt and completion tokens consumed by each branch.
- Latency: total clock time spent in model generation and sandbox execution.
- File modifications: git-style unified diff showing the final code output of Branch A versus Branch B.

## Deterministic Cassette Recording (VCR)

AgentHarness includes a cassette recording engine:

- Recording mode: every request to the language model and every sandbox tool output is serialized into a JSON cassette file under `.harness/cassettes/<run_id>.json`.
- Replay mode: subsequent executions read directly from the cassette without making network requests to LLM providers or re-executing sandbox commands.

This allows developers to build regression test suites for complex agent loops that run in milliseconds and incur zero API cost.
