# Existing tool contracts

Look up the live schema; the following names refer to server tools, not a guaranteed client namespace.

- `catia_save_document`, `catia_open_document`, `catia_export`, and `catia_screenshot` use `file_path`. A mistaken `path` can be ignored and cause an unintended ordinary Save. Use absolute Windows paths.
- `catia_sketch_circle` uses `cx`, `cy`, `radius`, not `x`, `y`. Inspect the returned actual center.
- Close a sketch before creating a solid feature. GSD elements live under HybridBodies; a deletion tool limited to Body.Shapes cannot delete a spline just because the tree name matches.
- Current distance-path output was observed to multiply a known 140 mm difference to 140000 mm. Do not use that path for dimension acceptance until a corrected unit contract is independently verified. A reported center of gravity cannot establish local concavity.
- `catia_plan_run` takes an immutable `request_id` and a list of steps with `id`, `tool`, and `arguments`. Discover assertion schema when assertions are needed; do not guess JSON-pointer field names. A completed duplicate returns cached evidence. Changed bytes under the same request ID are rejected.
- `catia_plan_catalog` and `catia_plan_status` do not dispatch geometry work. Catalog exposes adapter version/PID/hash; status can query one request. They do not unlock uncertain work.
- Returned image content is preserved by the adapter. Whether a selected Codex model can actually interpret that content must be checked separately; do not substitute a text summary and claim direct vision.

Smooth compatible loft sections can reduce offset risks. A sharp many-segment surface may loft but fail its later ThickSurface operation; surface creation alone is not a solid-generation pass. The demonstrated failures do not establish a universal geometric root cause.

Topology and bore-wall checks complement images. An inward cylinder can also bound an open arch; it is not automatically a through-hole. For a circular bore, check surrounding material, axial clearance and local sections. Independently count disconnected solids and review trimmed-spline integration convergence before calling a volume discrepancy lost material.
