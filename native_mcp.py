"""Automatic native modeling tools, with immutable one-use request records."""
import os
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from native_service import NativeService

WORKSPACE = Path(os.environ['PHYXI_NATIVE_WORKSPACE'])
GATE = Path(os.environ['PHYXI_NATIVE_GATE'])
mcp = FastMCP('PhyXi Native Modeling', instructions='Native modeling is preauthorized by the user. No manual review or developer unlock is needed for KNOWN_FINISHED geometry failures: the service releases them automatically. If state=FAILED and completion=KNOWN_FINISHED, explain actual geometry mismatch, correct the program, and use a NEW request_id for the revised operation without asking approval. Never replay the same consumed request or claim a failed model passed. Unknown/in-flight work cannot be replayed. Use modeling_execute for new direct programs and modeling_run for prepared workflow jobs.')


@mcp.tool()
def modeling_run(job_id: str, macro_ascii: str) -> dict:
    """Run an automatically prepared workflow CATScript once in a new CATIA Part.

    Reject unknown jobs or changed code. Save/reopen/read back/capture own result.
    Duplicates of completed jobs return recorded evidence without CAD dispatch.
    Known terminal validation failures return FAILED and release the queue
    automatically. A corrected program uses a NEW request. Unknown work blocks.
    """
    return NativeService(WORKSPACE, GATE).run(job_id, macro_ascii)


@mcp.tool()
def modeling_execute(request_id: str, requirement: str, macro_ascii: str, checks: dict, summary: str = '') -> dict:
    """Create and execute a new native CATIA Part automatically; no approval step.

    Provide a complete CATMain(runId, outputPath, resultPath) ASCII CATScript and
    checks with features, sketch_count, volume_mm3. Use one stable request_id for
    this operation. Part has no PartNumber property: use doc.Product.PartNumber
    or omit numbering. Explicit CATIA VBScript errors return FAILED/KNOWN_FINISHED.
    A completed duplicate returns cached evidence, never a
    second CAD dispatch. Changed input under the same id is rejected. Known
    finished failures return diagnostics and allow a corrected NEW request
    automatically, without human review; a failed candidate is not success.
    """
    return NativeService(WORKSPACE, GATE).execute_request(request_id, requirement, macro_ascii, checks, summary)


@mcp.tool()
def modeling_status(job_id: str = '') -> dict:
    """Read execution state and a recorded result without any CATIA dispatch.

    Use this after errors instead of reading SQLite or attempting an unlock.
    Known terminal script/validation failures automatically release the queue.
    """
    service = NativeService(WORKSPACE, GATE)
    result = {'gate': service.snapshot(), 'interactive_approval_required': False, 'CAD_dispatch': False}
    if job_id:
        row = service.job(job_id)
        result.update(job_id=job_id, state=row['state'],
                      recorded_result=json.loads(row['result_json']) if row['result_json'] else None)
    return result


if __name__ == '__main__':
    mcp.run(transport='stdio')
