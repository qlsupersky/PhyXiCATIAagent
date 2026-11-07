---
name: catia-native
description: Create, inspect, or modify CATIA V5 parts by writing JavaScript programs that call existing MCP tools through PhyXi Code Mode, including reference-image-assisted native macro generation.
---

Use **Code Mode** for this project: write an async JavaScript function body, submit it once through `catia-code.ptc_execute`, and poll `ptc_status`. Discover exact backend schemas with `ptc_catalog(server, names)`. Only three tools face the model; the existing104 tools are capabilities called from code. For a file-based entry without any structured model-side MCP submission, use `code_mode/cli.py run`; see the repository's `code_mode/README.md` for installation and CLI parameters.

Inside code use `await tools.catia_v5.TOOL(args)` or `await tools.native_modeling.TOOL(args)`. Replies are `{ok,data,uncertain,images}`; failed calls throw and stop further host dispatch even if caught. Use loops, branches, aggregation and assertions. Return concise JSON, at most8192 UTF-8 bytes. Full intermediate evidence stays local. Inline images are retained in evidence; only their count reaches guest code. This does not supply an automatic visual feedback loop.

```javascript
const s = await tools.native_modeling.modeling_status({});
if(s.data.gate.status !== 'IDLE') return {ready:false,gate:s.data.gate.status};
const r = await tools.catia_v5.catia_list_documents({});
return {ready:true,documents:r.data};
```

Guest JavaScript runs in QuickJS WebAssembly without Node, filesystem or network APIs. The trusted Python broker actually dispatches MCP. The original shared gate controls each backend call; the whole program is not an atomic transaction. Generate and call `catia_plan_run` for an atomic multi-step span. Do not bypass MCP with COM/shell helpers. CATIA macro execution is not an OS sandbox.

Query the current gate from code before changes. RUNNING/FROZEN/UNCERTAIN blocks new work; inspect the same request, never replay/reset it. FAILED/KNOWN_FINISHED permits corrected NEW requests without manual approval. Same ID+same code returns cache; changed code with the same ID is rejected. Unfinished records remain blocking after broker restart until actual upstream evidence is reconciled. Process exit alone is not completion.

For new parts, generate ASCII CATScript in code and call `modeling_execute`; read [macro-contract.md](references/macro-contract.md). For inspection/edits, discover selected catia-v5 schemas and read [tool-contracts.md](references/tool-contracts.md). Preserve originals and user documents. Use the configured output workspace. Check actual dimensions, material change and save/reopen evidence; execution success alone is not engineering/Class-A acceptance.

For reference images, separate observed shape, legible dimensions and assumptions. Do not claim text-only models see images. Report real evidence and limitations. Keep credentials, customer files and raw sessions out of public packages.
