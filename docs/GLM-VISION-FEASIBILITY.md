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

## Geometry checks need separate evidence

The following statements are different:

- A tool finished.
- A feature exists in the tree.
- A measurable solid changed as intended.
- An exported STEP is topologically valid.
- All requested design features are present.
- The model is fully parameterized, manufacturable, or Class-A.

For STEP inspection, isolate closed solids before calculating physical volume. Exports may also contain open construction surfaces; their aggregate signed mass is not a solid's volume. Use adaptive integration for trimmed B-spline solids, and compare the independent volume with CATIA's measurement. Valid BRep topology alone does not verify hole count, parameter relations, surface continuity, or manufacturing constraints.

## Local deployment remains a separate project

An eight-GPU server description is insufficient to establish deployment fit. Verify per-device VRAM, obtainable weights, quantization and framework support, tensor/expert parallelism, context length, concurrency, and the resources needed by both text and vision services.

The GLM-5.3-Flash specification states 320B total / 18B active parameters. Active parameters are not the resident weight size. Theoretical weight-only lower bounds for 320B parameters are about 640 GB at 16-bit, 320 GB at 8-bit, or 160 GB at 4-bit, before runtime overhead, KV cache, activations, and inter-device buffers. These estimates do not establish that an available quantized model or supported deployment stack exists. Do not infer GLM-5.3's parameter count from a different GLM release.

Keep inference services and the Windows CATIA execution host separate. API connectivity and latency tests cannot substitute for measurements on the target hardware.

Only general methodology and sanitized findings are included here. Reference images, customer requirements, generated customer models, conversations, service configuration, credentials, and raw local logs are excluded from the public repository.
