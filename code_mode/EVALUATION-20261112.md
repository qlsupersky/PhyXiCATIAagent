# Complex-part PTC evaluation — 2026-11-12

This follow-up uses actual CATIA V5 and the same `gpt-6.1-sol` / high
reasoning setting for both arms. Both have the same 104 backend capabilities.
The direct MCP arm can batch a complete native macro or a multi-step plan;
it is not restricted to one primitive per model turn. The PTC arm exposes
only execute/status/catalog, with JavaScript driving those same backends.
Production WebUI remains the OpenCode-based 0.7.0 application; this test does
not migrate its conversation runtime to PTC.

## Actual generation results

| Demo part | Direct MCP seconds | PTC seconds | Independently checked result |
| --- | ---: | ---: | --- |
| Wheel: 20 polygon windows, six round bores, six native features; Hub height edited 95 to 105 mm | 100.453 | 119.328 | Both pass the specified STEP checks |
| Roof: 49 points, seven native splines, loft, 2 mm thickening, sunroof and four mount bores | 92.719 | 163.750 | Both pass the specified STEP checks |
| Fender: 49 points, seven splines, freeform loft, 2 mm thickening, wheel arch and four mount bores | 98.610 | 124.421 (incomplete) | Direct passes; PTC stops at the thickened surface |

Each task/arm was run once. No general performance or statistical success-rate
claim follows from this small, sequential cohort. Timings cover the actual model
turn through terminal completion, including discovery, calls, polling and
diagnosis; initial session/tool-list setup is outside the timer. The incomplete
fender time is not a successful-run speed comparison.

Direct/PTC outer-call counts were 12/11, 7/16 and 4/15 respectively. Full
tool-reply JSON envelopes were 50,093/159,784, 241,922/75,265 and
234,438/70,894 bytes. The wheel PTC envelope contains a real screenshot image;
removing image payload makes it 49,268 bytes. Smaller curve-task replies did
not translate to lower latency or lower reported cumulative token usage.
Reply-byte counts exclude submitted code, schemas, input reference images
and other protocol overhead. Provider token telemetry is not an invoice audit.

## Acceptance scope

Independent OpenCascade STEP inspection checks valid single solids and
specified material/clearance ray samples, including all 20 wheel window
locations, 20 spoke material locations, six bore axes and surrounding material,
Hub height, roof opening, fender arch/feet, specified control points and sampled
thickness. The wheel analytic volume agrees with independent solid integration.
This does not certify arbitrary hole recognition, global metrology,
manufacturability, reflection-line quality or automotive Class-A surfaces.

Construction surfaces are separated from closed solids for volume checks.
CATIA and STEP solid integration differ by about 0.76% on the roof and 0.58%
on the completed fender; that discrepancy remains unresolved. An initial
continuous-field oracle was retained as a diagnostic and corrected to check
the actual requested interpolation points. Unrequested points between spline
sections were not quietly relabeled as exact analytic-surface requirements.

Seven additional ray hits on actual trimmed STEP faces support the selected
roof/fender outward-convex regions, with normals aligned to the specified
positive coordinate axis. This is finite sampling, not a global convexity
or Class-A proof. Those offline numeric results are separate from what the
model could access through the current MCP inspection tools.

## Observed failures and correction scope

- Returning an entire large plan result exceeded the 8 KiB PTC final-output
  limit. CAD work had already executed. The model queried the existing result
  with a new read-only program instead of replaying geometry.
- A closed-sketch inspection returned the complete exact upstream
  `No active sketch` precondition error. Legacy classification incorrectly
  froze the gate as uncertain. The narrow classifier patch recognizes only
  `catia_sketch_get_geometry`, the exact complete message, `COM_ERROR`, the
  execute stage and absence of RPC diagnostics. It remains a failed call;
  subsequent writes are skipped. Write tools, altered messages, missing
  returns and RPC failures are not generalized to known-finished.
- Original failure evidence was retained and a single evidence-bound local
  reconciliation performed without replaying CAD. The original generation
  task remains failed.
- An assisted fender follow-up saved a separate candidate, but Pocket
  UpdateObject failed and the one allowed correction failed on Update.
  Independent STEP checks confirm that the arch and four mount bores are
  absent. Both successful and failed cases requested the same symmetric
  Pocket parameters. The specific geometric failure cause is unresolved.
- Face/edge enumeration can return a Search-failure string while the
  upstream transport and containing plan report success. Raw text and
  independent acceptance must be examined; transport-error counts alone
  are inadequate. This enumeration defect is not fixed in this patch.

Two new regression tests cover exact no-active-sketch classification,
counterexamples, stopping later writes, no freezing and no replay. The core
suite reports 92 tests total, four skipped, remaining tests passing. There is
no new plugin version or claim that all backend tools have been validated.

## Understanding, ambiguity and bound-image follow-up

Six additional real image-plus-MCP turns used the same accepted fixture and
same actual CATIA screenshot for both arms, without the original design
recipe. Both arms distinguished an open fender arch from an isolated hole,
and recognized coordinate-dependent overall convex/concave shape from
construction-point evidence. Both acknowledged missing face/edge topology
and did not independently establish every exact hole count or through state.
This is a limitation, not a 100% hole-recognition result. All six requested
specific clarification of ambiguous scope, dimensions, reference frames or
continuity constraints, with no geometry-write tools dispatched and identical
fixture SHA256 before/after.

Direct/PTC understanding-plus-ambiguity turn times were 69.110/171.172 s
(wheel), 91.547/197.625 s (roof) and 80.750/149.187 s (fender). These include
evidence gathering and clarification, not completed modifications. The PTC
turns also encountered oversized-final-output errors. Geometry inspection
and compact return contracts remain bottlenecks.

A separate controlled wheel fault intentionally omitted the final Hub edit,
leaving 95 mm against the original 105 mm target. Actual bound feedback
reported a volume deficit of 86,550.8776 cubic mm. The repair model received
one real MCP ImageContent and measured feature depths, verified the active
candidate, saved a separate copy and edited only the existing Hub parameter.
No new Part or whole-part macro was dispatched. The 155.172 s / 14 outer-call
follow-up passed independent STEP volume, Hub height, window/spoke and six
bore checks. The original failed request and candidate hashes remain intact.
The supplied original target and explicit feedback-reading instruction make
this an assisted diagnostic exercise, not an unprompted repair benchmark.
The screenshot provides visual context; numerical feedback, not pixels alone,
supports the exact 10 mm diagnosis. The failed fender repair remains failed.

Detailed local dialogues, screenshots and generated models are deliberately
excluded from the public repository. No credentials, private configuration,
customer files or runtime session evidence is published.
