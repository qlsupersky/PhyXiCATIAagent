# GLM text and vision routing: feasibility notes

This note describes an API feasibility exercise with the existing 0.7.0 WebUI and `catia-v5` adapter. It is not a new plugin release, a completed automotive part benchmark, or an acceptance test of a local GPU deployment. The installed plugin and the user's default model configuration were not replaced by the experiment.

## Keep text and vision capability explicit

The official [GLM-5.3 documentation](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3) describes a text-only model. In the exercised service, text input returned HTTP 200 and image input returned HTTP 400 (`unsupported_image_input`). The service accepted images for GLM-5.3-Flash, which has a separate [vision model specification](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash).

A workable test route is:

1. Attach an image in a dedicated WebUI vision conversation.
2. Ask the vision model to distinguish visible geometry, dimensions read from labels, and unknown details.
3. Transfer the visible analysis text to a GLM-5.3 planning conversation.
4. Use the actual `catia-v5` tools to construct a new native CATPart.
5. Save the model, export STEP, and check the resulting solids independently.

This is explicit orchestration between conversations, not a claim that the installed WebUI automatically routes every image to a second model. Text extraction from labeled reference images must not be scored as blind visual recognition. API model names and returned IDs also do not independently establish the identity of underlying weights.

## Failures found during the exercise

Unknown argument names can have a much larger effect than an obvious schema rejection. The upstream schemas permit extra properties in several tools. For example:

- `catia_save_document` expects `file_path`. Passing `path` can silently select ordinary `Save()` instead of `SaveAs()`; an unnamed document then fails.
- `catia_sketch_circle` expects `cx`, `cy`, and `radius`. Passing `x` and `y` can leave the default center at `(0, 0)`.
- A `FEATURE_NO_EFFECT` textual result can be wrapped as transport/execution success although a pocket removed no material.
- A live two-point distance probe, whose coordinates differed by 140 mm, was reported as 140000 mm by the current measurement path. That result is unsuitable for dimensional acceptance without a corrected and validated unit contract.

These are integration findings, not reasons to reinterpret a failed model as successful. The exercise retained the original failures and documented developer intervention. A synchronously returned Save exception was adjudicated for that exact request from its bound exception and persisted terminal step, with an audit and without replay. Generic `E_UNEXPECTED`, process disappearance, or a missing output file must not become universal automatic-unlock criteria.

Recommended follow-up work is strict unknown-field rejection before any CAD dispatch, verification of returned feature positions, explicit no-effect classifications, and per-operation unit contracts. This note does not claim these follow-up changes have been deployed.

Object kinds also matter. The exercised upstream feature-deletion implementation searches `Body.Shapes`; a GSD spline is not in that collection. A lookup failure raised before `Selection.Delete` was wrapped as generic `COM_ERROR`, causing an unnecessary uncertain gate state. The exact request was adjudicated from the persisted synchronous failure, source control flow, and terminal session evidence, without replay. This does not permit a universal exemption for COM or transport errors. Query and deletion tools should distinguish solid features, sketches, and hybrid-shape objects explicitly.

## Geometry checks need separate evidence

The following statements are different:

- A tool finished.
- A feature exists in the tree.
- A measurable solid changed as intended.
- An exported STEP is topologically valid.
- All requested design features are present.
- The model is fully parameterized, manufacturable, or Class-A.

For STEP inspection, isolate closed solids before calculating physical volume. Exports may also contain open construction surfaces; their aggregate signed mass is not a solid's volume. Use adaptive integration for trimmed B-spline solids, and compare the independent volume with CATIA's measurement. Valid BRep topology alone does not verify hole count, parameter relations, surface continuity, or manufacturing constraints.

Numerical integration itself needs checking. An ordinary adaptive Gauss result for a heavily trimmed B-spline solid differed materially from a span-aware Gauss-Kronrod calculation. Refining the latter's requested tolerance produced stable results close to the CAD-side measurement. Preserve the original result, report the reached error estimate, and compare multiple tolerances before treating a volume discrepancy as lost material. Requested tolerance is not proof that the algorithm reached it.

A valid BRep can still contain small disconnected solid remnants. One native Body and a plausible overall view do not establish that the exported part is one continuous solid. Check solid count, connectivity and each component's volume separately. Independently rendered solid-only views also prevent visible construction surfaces from making genuine openings appear filled.

For analytic cylinder boundaries, grouping by axis, radius and oriented radial normal can support a bore-wall inventory. Such candidates do not establish through-hole semantics, arbitrary opening count, or design compliance. Textual inferences also need review: a center of gravity cannot establish every local concavity, and area/volume unit conversions must be checked independently.

## Post-result images and bounded observation

A separate post-result vision check compared the reference image, the actual CAD screenshot, and an independent solid-only STEP rendering. It helped expose broad shape simplification and construction-surface occlusion. It also produced unsupported small-hole guesses and an inconsistent count. Preserve these replies as model observations; do not promote image uncertainty into confirmed missing or blocked geometry. This is an explicit postcheck, not an already deployed automatic visual correction loop.

Selected circular bores can be checked more strongly than an inward-cylinder inventory. In one independently inspected single-solid cover, all 22 selected cylindrical walls also had surrounding material-ring samples and clear center/near-wall axial lines. These are sampled geometric checks for the selected axes and radii, not a general recognizer for blind holes, irregular openings, or every point of the bore volume.

A complex joined-section surface can be created successfully yet fail its subsequent offset/thickening update. In one trial, two bound ThickSurface updates returned explicit failures after about 193 and 1089 seconds. The sharp multi-segment input is a risk observation; the geometric root cause was not independently established. Do not count the surface as a finished solid or reinterpret long execution as success.

A language-stall observer must exclude CAD execution time. Checking only that a gate is IDLE at one instant can interrupt language processing immediately after a long CAD call returns. A corrected observer requires both no visible language/tool progress and a continuously IDLE CAD interval exceeding the budget. Six offline timing decisions covered running CAD, newly returned CAD, true idle stall, recent progress, already interrupted work, and missing idle evidence. This correction was made to the test supervisor only; it is not a production plugin release or a reason to cancel/replay an in-flight CAD operation. The original premature interruption remains in the evidence.

## Local deployment remains a separate project

An eight-GPU server description is insufficient to establish deployment fit. Verify per-device VRAM, obtainable weights, quantization and framework support, tensor/expert parallelism, context length, concurrency, and the resources needed by both text and vision services.

The GLM-5.3-Flash specification states 320B total / 18B active parameters. Active parameters are not the resident weight size. Theoretical weight-only lower bounds for 320B parameters are about 640 GB at 16-bit, 320 GB at 8-bit, or 160 GB at 4-bit, before runtime overhead, KV cache, activations, and inter-device buffers. These estimates do not establish that an available quantized model or supported deployment stack exists. Do not infer GLM-5.3's parameter count from a different GLM release.

Keep inference services and the Windows CATIA execution host separate. API connectivity and latency tests cannot substitute for measurements on the target hardware.

Only general methodology and sanitized findings are included here. Reference images, customer requirements, generated customer models, conversations, service configuration, credentials, and raw local logs are excluded from the public repository.
