"""Three-tool PTC MCP facade. Existing CATIA tools are backend-only capabilities."""
import os
from mcp.server.fastmcp import FastMCP
from engine import Engine, load_config

config = load_config(os.environ['PHYXI_PTC_BACKENDS'])
engine = Engine(config['catia-v5']['env']['PHYXI_NATIVE_WORKSPACE'], config, os.environ['PHYXI_PTC_NODE'])
mcp = FastMCP('PhyXi CATIA Code Mode', instructions='Use ptc_execute to submit JavaScript orchestration, not individual CAD tool calls. Code can await tools.catia_v5.NAME(args) and tools.native_modeling.NAME(args), loop/branch/assert/filter and return a concise JSON result. ptc_catalog discovers backend schemas; ptc_status polls without replay. Guest code runs in QuickJS WebAssembly with CPU/memory limits and no OS/network APIs. Only the trusted host dispatches MCP. Failed/uncertain calls stop further dispatch. Existing per-call CATIA shared mutex applies; use catia_plan_run for an atomic multi-step span. No manual review. This facade does not prove geometry or provide a complete OS sandbox for CATIA macros.')


@mcp.tool()
async def ptc_execute(request_id: str, code: str) -> dict:
    """Start one immutable JavaScript async-function body, then poll ptc_status.

    Use await tools.catia_v5.catia_plan_status({}) and conditionals/loops.
    Methods return {ok,data,uncertain,images}; raw intermediate replies stay local.
    Return JSON <=8192 UTF-8 bytes. No imports/fs/process/fetch. 100 calls max,
    32MiB guest heap, 2s guest CPU excluding host waits. Same ID+same code returns
    cached status, changed code rejected. Failed calls stop dispatch even if caught.
    """
    return await engine.start(request_id, code)


@mcp.tool()
def ptc_status(request_id: str) -> dict:
    """Read concise running/final result and evidence location. Never replay/unlock.

    RUNNING may outlive frontend waits. UNCERTAIN requires actual upstream evidence;
    do not resubmit. SUCCEEDED means program returned, not whole-part acceptance.
    """
    return engine.status(request_id)


@mcp.tool()
async def ptc_catalog(server: str, names: list[str] | None = None) -> dict:
    """Read existing backend names/descriptions or up to12 exact input schemas.

    server is catia-v5 or native-modeling. No CAD dispatch. These backend tools
    are called from guest program, not exposed as104 direct tools by this facade.
    """
    return await engine.catalog(server, names or [])


if __name__ == '__main__':
    mcp.run(transport='stdio')
