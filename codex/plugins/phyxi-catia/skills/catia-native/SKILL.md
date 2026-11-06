---
name: catia-native
description: Create, inspect, or modify CATIA V5 parts using PhyXi native macro execution and catia-v5 MCP tools, including reference-image-assisted modeling. Use for CATIA work, not generic CAD conversion or offline SimpleCAD geometry.
---

Use the connected `catia-v5` or `native-modeling` server. Discover the actual tool names and schemas exposed by the current Codex client; server IDs with hyphens may be normalized in tool namespaces. Do not invent a renamed tool, use OpenCode-only `execute` syntax, or create a COM script to bypass the MCP.

Start with `catia_plan_status` or `modeling_status`. Both clients share one CATIA gate. A RUNNING/FROZEN/uncertain request blocks new CAD calls; inspect its recorded result rather than retrying, resetting its database, or killing CAD. A returned FAILED/KNOWN_FINISHED request may be corrected with a new request ID without a manual approval step. Respect the current user's execution authorization; this skill does not grant independent authority.

Choose a route:

- For a complete new part driven by natural language, generate a native ASCII CATScript and use `modeling_execute`; read [macro-contract.md](references/macro-contract.md) for the actual entrypoint and checks. Codex generates the program directly; no OpenCode model service is required.
- For inspection, local edits, or stepwise native construction, use existing `catia-v5` tools. Query `catia_plan_catalog` with selected names and `include_schema=true`. A `catia_plan_run` plan holds the shared mutex for up to 30 serial steps and persists results. Read [tool-contracts.md](references/tool-contracts.md) for known field/unit pitfalls before saving, cutting, or measuring.
- For an attached image, distinguish visible geometry, dimensions read from labels, and assumptions. If the active model cannot accept images, state that limitation and use an explicitly available visual service; do not silently claim text-only image recognition. A screenshot is supporting evidence, not proof of thickness, hole count, topology, Class-A continuity or manufacturing quality.

Preserve existing documents and customer originals. New models and diagnostic copies go to the configured workspace or the user's selected output directory. Retain native features and measurable design intent. A known failed strategy should not be retried more than twice without changing the construction method or reporting the missing feature.

Check the returned result of each significant operation. `FEATURE_NO_EFFECT` means the intended cut did not occur even if the outer transport says SUCCEEDED. A saved file, a feature-tree node, a changed volume, valid STEP topology and complete requirements are distinct findings. Verify operation position/direction, material change, solid count, and requested dimensions as appropriate. Report actual missing or simplified geometry. For images, compare clean solid-only views or sections with geometry evidence before claiming a hole is blocked or a surface is concave.

If a call times out, observe the same request until its true state is known. A Codex timeout or closing a conversation is not evidence that CATIA finished. Do not resubmit an uncertain operation. Save actual conversations, outputs and checks locally; exclude credentials and customer material from public packages.
