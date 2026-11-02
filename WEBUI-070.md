# 0.7.0 WebUI / Electron / 多步骤工具计划

本版在 0.6.5 基础上新增本地 WebUI 与 Electron 桌面壳，保留 Tk 插件的全部七页与 OpenCode 原生入口。WebUI 不替换 OpenCode 引擎，不限制现有模型和工具。

## 启动

安装后打开工作目录中的 `PhyXiCATIAAgent-Web` 或 `PhyXiCATIAAgent-Desktop` 快捷方式；也可在原插件顶部点 WebUI / Electron，或在 CATIA 宏库中运行新建的 `PhyXiCATIAAgent-Web.CATScript` / `PhyXiCATIAAgent-Desktop.CATScript`。

发行 ZIP 不包含 Electron 运行时。新电脑安装插件后，请进入**安装目录**运行 `install-desktop.ps1` 下载锁定依赖，再打开 Desktop 快捷方式。浏览器 WebUI 不需要 Electron。本次开发机器已配置可用运行时，无需重复下载。

源码启动：

```powershell
python web_server.py --browser --workspace "D:\CAD\PhyXiCATIAagent-workspace"
# Electron 需要 Node.js/npm，仅首次安装运行时
.\install-desktop.ps1
python launch_ui.py desktop
```

WebUI 只监听 127.0.0.1，启动入口将本进程认证信息交给浏览器，不暴露 OpenCode 密码和提供者 API Key。Electron 使用同一个 WebUI，关闭 Node integration、开启 context isolation 与 sandbox，拒绝页面外部导航。关闭 Electron 只停止本界面的等待，不终止 OpenCode 或 CATIA 的已派发调用。

## 使用

1. 点“连接 OpenCode”，选择/新建会话和模型、Agent、变体。
2. 添加图片/文件或粘贴图片，在“对话”模式输入自然语言；消息不附加固定 CAD JSON 约束。
3. “多步骤任务”模式每行一个目标，一次发送。该模式明确要求模型按序使用实际工具，失败时停止后续修改并报告；模型的实际选择由工具结果核对，不把文字计划当作已执行结果。
4. 右侧显示实际工具调用，以及本机共享 CAD 队列最近三个计划的逐步事件、返回码、耗时、显式检查状态与未执行步骤。共享计划列表不是当前会话独占列表。
5. “完整 OpenCode”进入同一项目/session 的原生界面，继续使用终端、斜杠命令和其他功能。

单附件最多 8 MiB，合计最多 16 MiB/12 个附件。PNG/JPEG 超过既有接口尺寸限制时适配快照并保留原始输入；模型是否能识图由实际服务决定。

## 新增 MCP 工具

`catia_adapter.py` 基于既有 CATIA-V5 MCP Server 扩展，保留原来的 98 个工具，新增：

- `catia_plan_catalog`：不连接 COM，默认返回工具名与说明；传入 `names` 和 `include_schema: true` 获取指定工具完整 schema，减少模型上下文截断。
- `catia_plan_run`：一个唯一 request_id，1–30 步，先验证整份计划的输入，整段计划持有同一 CATIA 互斥，在原有单线程 STA 中逐步执行。
- `catia_plan_status`：默认返回近期计划摘要，传入 request_id 读取完整持久计划状态，不派发 COM；不排在长任务 STA 后，可以在执行中读取进度。

每步包含 `id`、`tool`、可选 `arguments` 和 `expect`。示例：

```json
{
  "request_id": "inspect-part-unique-001",
  "steps": [
    {"id": "info", "tool": "catia_get_active_document_info"},
    {"id": "volume", "tool": "catia_get_inertia", "expect": [
      {"path": "/volume_mm3", "op": "gt", "value": 0}
    ]}
  ]
}
```

`expect.path` 是实际返回数据的 JSON pointer。支持 eq/gt/ge/lt/le；eq 可加数值 tolerance。缺少测量值、类型不符或检查失败均返回失败。`SUCCEEDED` 只表示工具正常返回；`declared_checks_passed` 只说明声明的检查通过，不能替代整件几何或 A 级曲面的验收。

返回保留原始 MCP 数据及图像，补充 completion、effects、verification、duration_ms、逐步事件。普通原工具也通过相同包装反馈，原调用名称和 schema 保留。已知结束失败释放入口；RPC、超时、异常中断等状态不明时保留未确认状态，不自动重试、回滚或解锁。相同 request_id 永远返回已有记录；改动内容必须使用新标识。

## 部署第二套扩展

使用第二套服务自己的 venv 及现有上游源码（验证提交 `ae47bbf6353cf16bda78e23640db6012de890471`）。将 OpenCode `catia-v5` 的 command 改为：

```text
<第二套venv/python.exe> <插件目录/catia_adapter.py> --upstream <catia-v5-mcp-server源码目录>
```

环境中保留相同 `PHYXI_NATIVE_WORKSPACE`、`PHYXI_NATIVE_GATE`。两套服务必须指向相同 gate。主插件仍使用 MCP 1.26.0，第二套原环境使用 MCP 1.30.0，保持环境隔离，不覆盖各自依赖。此扩展不修改 CATIA 商业软件本体，也不修改上游源码。

更新后应先确认当前请求结束和共享 gate 空闲，再在相应 OpenCode 项目中断开并重连该 MCP。仅修改相同 command 的配置可能复用旧进程。catalog 返回 adapter.version、pid 和 source_sha256，可用于核实加载的版本。

## 状态与记录

- `workspace/tool-plans/plans.sqlite`：多步骤意图、结果与事件。
- `workspace/web-jobs`：WebUI 提交回执，重启后未确认记录只观察，不重发。
- `workspace/opencode-conversations`：OpenCode 原始会话及附件快照。

WebUI 使用独立的当前会话指针，保留旧 Tk 界面所选会话。真实 OpenCode session ID 可跨界面继续。
