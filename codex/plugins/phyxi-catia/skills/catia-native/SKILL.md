---
name: catia-native
description: Create, inspect, or modify CATIA V5 parts by writing JavaScript programs that call existing MCP tools through PhyXi Code Mode, including reference-image-assisted native macro generation.
---

Use **Code Mode** for this project: write an async JavaScript function body, submit it once through `catia-code.ptc_execute`, and poll `ptc_status`. Discover exact backend schemas with `ptc_catalog(server, names)`. Only three tools face the model; the existing104 tools are capabilities called from code. For a file-based entry without any structured model-side MCP submission, use `code_mode/cli.py run`; see the repository's `code_mode/README.md` for installation and CLI parameters.

Inside code use `await tools.catia_v5.TOOL(args)` or `await tools.native_modeling.TOOL(args)`. Replies are `{ok,data,uncertain,images}`; failed calls throw and stop further host dispatch even if caught. Use loops, branches, aggregation and assertions. Return concise JSON, at most8192 UTF-8 bytes. Full intermediate evidence stays local. Only image counts reach guest JavaScript. After a native run, `ptc_status(request_id, include_feedback=true)` can return the executor-bound candidate screenshot as actual MCP ImageContent and measured diagnostics to the model. Read the image and measurements before deciding a correction; a screenshot alone cannot establish exact dimensions. This is evidence delivery, not a guaranteed autonomous repair policy.

```javascript
const s = await tools.native_modeling.modeling_status({});
if(s.data.gate.status !== 'IDLE') return {ready:false,gate:s.data.gate.status};
const r = await tools.catia_v5.catia_list_documents({});
return {ready:true,documents:r.data};
```

Guest JavaScript runs in QuickJS WebAssembly without Node, filesystem or network APIs. The trusted Python broker actually dispatches MCP. The original shared gate controls each backend call; the whole program is not an atomic transaction. Generate and call `catia_plan_run` for an atomic multi-step span. Do not bypass MCP with COM/shell helpers. CATIA macro execution is not an OS sandbox.

Query the current gate from code before changes. RUNNING/FROZEN/UNCERTAIN blocks new work; inspect the same request, never replay/reset it. FAILED/KNOWN_FINISHED permits corrected NEW requests without manual approval. Same ID+same code returns cache; changed code with the same ID is rejected. Unfinished records remain blocking after broker restart until actual upstream evidence is reconciled. Process exit alone is not completion.

Combine dependent operations in one program and discover only required schemas. Use `ptc_status(request_id, wait_ms=20000)` for bounded asynchronous waiting rather than repeated short model polls. On failure inspect `upstream_failure.message`, original measurements and bound screenshot. When saving an already-named current document to the SAME file, omit `file_path` in `catia_save_document` to use Save instead of SaveAs/overwrite dialogs. After any open, verify the actual active full path: an upstream success string alone does not prove the intended document loaded.

On a known geometry failure, keep the failed candidate, compare measured feature depths/volume to the ORIGINAL target, and use a new request for a corrected candidate. Do not lower acceptance targets to match a bad result. An observation of an uncertain upstream job is not permission to repair it. Clarify missing object identity, reference frame or quantity (for example diameter versus area) before changing an ambiguous design.

For new parts, generate ASCII CATScript in code and call `modeling_execute`; read [macro-contract.md](references/macro-contract.md). For inspection/edits, discover selected catia-v5 schemas and read [tool-contracts.md](references/tool-contracts.md). Preserve originals and user documents. Use the configured output workspace. Check actual dimensions, material change and save/reopen evidence; execution success alone is not engineering/Class-A acceptance.

For reference images, separate observed shape, legible dimensions and assumptions. Do not claim text-only models see images. Report real evidence and limitations. Keep credentials, customer files and raw sessions out of public packages.
