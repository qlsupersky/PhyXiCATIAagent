"""Three-tool PTC MCP facade. Existing CATIA tools are backend-only capabilities."""
import os
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
from engine import Engine, load_config
from feedback import content_for_status
from mcp.types import CallToolResult

config = load_config(os.environ['PHYXI_PTC_BACKENDS'])
engine = Engine(config['catia-v5']['env']['PHYXI_NATIVE_WORKSPACE'], config, os.environ['PHYXI_PTC_NODE'])
@asynccontextmanager
async def lifespan(server):
    try:
        yield {}
    finally:
        await engine.aclose()


mcp = FastMCP('PhyXi CATIA Code Mode', lifespan=lifespan, instructions='Use ptc_execute to submit JavaScript orchestration, not individual CAD tool calls. Code can await tools.catia_v5.NAME(args) and tools.native_modeling.NAME(args), loop/branch/assert/filter and return a concise JSON result. ptc_catalog discovers backend schemas; ptc_status polls without replay. Guest code runs in QuickJS WebAssembly with CPU/memory limits and no OS/network APIs. Only the trusted host dispatches MCP. Failed/uncertain calls stop further dispatch. Existing per-call CATIA shared mutex applies; use catia_plan_run for an atomic multi-step span. No manual review. This facade does not prove geometry or provide a complete OS sandbox for CATIA macros.')


@mcp.tool()
async def ptc_execute(request_id: str, code: str, wait_ms: int = 20000) -> dict:
    """Submit one immutable JavaScript body; wait up to20s, then poll if RUNNING.

    wait_ms=0..20000 (default20000). cad.near offers explicit abs/relative tolerance.
    Backend handles and schemas persist within this server lifetime, not across restart.

    Use await tools.catia_v5.catia_plan_status({}) and conditionals/loops.
    Methods return {ok,data,uncertain,images}; raw intermediate replies stay local.
    Return JSON <=8192 UTF-8 bytes. No imports/fs/process/fetch. 100 calls max,
    32MiB guest heap, 2s guest CPU excluding host waits. Same ID+same code returns
    cached status, changed code rejected. Failed calls stop dispatch even if caught.
    """
    if type(wait_ms) is not int or not 0 <= wait_ms <= 20000:
        raise ValueError('wait_ms must be an integer from 0 to 20000')
    result = await engine.start(request_id, code)
    if result.get('status') == 'RUNNING' and not result.get('cached_no_dispatch'):
        return await engine.wait_status(request_id, wait_ms)
    return result


@mcp.tool()
async def ptc_status(request_id: str, include_feedback: bool = False, wait_ms: int = 0) -> CallToolResult:
    """Read concise running/final result and evidence location. Never replay/unlock.

    Set include_feedback=true to receive a bound native candidate screenshot as
    actual MCP ImageContent plus measured diagnostics, including on known failures.
    It reads recorded evidence only, never captures arbitrary desktop or dispatches CAD.
    Optional wait_ms=0..20000 waits asynchronously for a terminal record, reducing
    repeated model polling; it does not cancel, replay or change job state.
    RUNNING may outlive frontend waits. UNCERTAIN requires actual upstream evidence;
    do not resubmit. SUCCEEDED means program returned, not whole-part acceptance.
    """
    return content_for_status(await engine.wait_status(request_id, wait_ms), include_feedback)


@mcp.tool()
async def ptc_catalog(server: str, names: list[str] | None = None) -> dict:
    """Read existing backend names/descriptions or up to12 exact input schemas.

    server is catia-v5 or native-modeling. No CAD dispatch. These backend tools
    are called from guest program, not exposed as104 direct tools by this facade.
    """
    return await engine.catalog(server, names or [])


if __name__ == '__main__':
    mcp.run(transport='stdio')
