# 第二套 CATIA MCP 接入

第二套服务基于 [daiemon12/catia-v5-mcp-server](https://github.com/daiemon12/catia-v5-mcp-server)，本版验证固定提交 `ae47bbf6353cf16bda78e23640db6012de890471`。上游源码与虚拟环境独立部署，不包含在本项目或安装包中。

## 部署

1. 按上游说明克隆该提交、建立独立 Python 虚拟环境并安装其依赖。上游需 jsonschema、pywin32 和 MCP SDK；本版契约测试使用 MCP 1.30.0。
2. 安装本项目，将 [示例配置](../examples/opencode-mcp.example.json) 的路径替换为实际路径，合并至现有 OpenCode 配置。保留用户已有模型、API Key 和其他设置。
3. 第二套 `catia-v5` 命令使用其独立 venv 的 Python，运行本项目安装目录中的 `catia_adapter.py --upstream <上游源码目录>`。不要直接启动未封装的上游服务参与共享 CATIA 执行。
4. 两套服务的 `PHYXI_NATIVE_WORKSPACE` 与插件一致，`PHYXI_NATIVE_GATE` 必须为同一个 SQLite 文件。由本项目包装层提供跨服务互斥；仅为原始上游设置环境变量不提供该能力。
5. 等待旧调用实际结束、确认队列空闲后，在目标 OpenCode 项目断开并重连第二套 MCP。`catia_plan_catalog` 返回的版本、PID 和加载时源码 SHA-256 可核对当前进程。

主插件原验证环境使用 MCP 1.26.0，第二套使用 MCP 1.30.0；保持环境隔离。第二套保留 98 个原工具，新增 3 个计划工具。详情见 [WebUI 与计划说明](../WEBUI-070.md)。只部署 `native-modeling` 也可继续使用专用自然语言生成原生宏流程。
