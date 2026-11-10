# CATIA Code Mode / PTC（扩展0.2.0）

这次扩展实现“AI 写程序 → 运行时调用 MCP → 程序筛选结果 → 只返回摘要”。它与仅把 MCP 配置迁入 Codex 不同，也不把固定 JSON 工具列表包装成代码。JavaScript 可以根据工具结果循环、分支、断言、计算参数及生成 CATIA 原生宏。

```text
Codex 生成 JavaScript
        ↓ 一次提交或运行代码文件
QuickJS WebAssembly（编排程序）
        ↕ Promise 暂停/恢复；仅 JSON 跨边界
Python broker（schema 校验、日志、去重）
        ↓ MCP client → 原有两套 MCP → 共享执行门 → CATIA
        ↑ 完整结果在本地；代码只 return 精炼结果给模型
```

## 两种使用入口

**MCP facade** 只暴露三个工具：`ptc_catalog(server,names)` 查找内层工具、`ptc_execute(request_id,code)` 一次提交程序、`ptc_status(request_id)` 查询进度/最终结果。已有的104个业务工具不再作为模型逐步调用的接口暴露。外层程序提交仍可走 MCP 协议，这是代码执行入口，不代表底层取消了 MCP 请求。

**CLI 直接运行代码文件** 不要求模型提交结构化工具调用：模型写好 `.js`，用一次终端命令运行 `cli.py run`。运行时内部仍作为 MCP 客户端使用原服务器。CLI 和 facade 共享任务日志、去重和不确定状态阻断。

```javascript
const gates=[];
for(let i=0;i<2;i++) {
  const reply=await tools.native_modeling.modeling_status({});
  gates.push(reply.data.gate.status);
}
const busy=gates.filter(x=>x!=='IDLE');
return {ready:busy.length===0, observed:gates};
```

这是一段 async 函数体，不需要 `export`、`main` 或 import。工具别名为 `tools.catia_v5.NAME(args)`、`tools.native_modeling.NAME(args)`，也可用 `mcp.call('catia-v5','NAME',args)`。回复为 `{ok,data,uncertain,images}`；失败抛错且宿主停止后续派发，即便程序 catch 异常也不能继续派发。单步 catia-v5 工具的适配器 envelope 被解包为 `.data`，完整原始回复保留在本地证据。

## 安装

要求 Windows、Node.js（本机验证v20.11.0）、Python3.12与现有两套可用 CATIA MCP。项目整体安装版仍为0.7.0，此处为独立 Code Mode 扩展0.2.0、Skill0.2.0（说明已补充反馈流程）。

```powershell
python -m pip install -r code_mode/requirements.txt
cd code_mode/runtime
npm ci --ignore-scripts --no-audit --no-fund
cd ../..
python code_mode/install.py --source C:/path/to/opencode.json --node C:/path/to/node.exe
python code_mode/install.py --source C:/path/to/opencode.json --node C:/path/to/node.exe --apply
```

默认先 dry-run；`--apply` 只把 Codex 的 `native-modeling` / `catia-v5` 条目设为 disabled 并注册 `catia-code`。保留模型、provider、其他插件和 MCP。OpenCode 配置不变，因此已有 WebUI 仍是原先的 OpenCode 工作流；此项不是 WebUI 后端替换。

本机后端命令、环境与共享 gate 路径保存在 Codex home 的 `phyxi-code-mode/backends.json`，不包含模型 API Key。完整配置备份可能含私密资料，只能留在用户 home，不得打包/上传。打印的回滚凭据供定向恢复：

```powershell
python code_mode/install.py --rollback C:/path/to/ptc-install.json
```

修改后创建新的 Codex 会话；旧会话可能需要重启应用才能刷新工具。不要同时启用旧的直接104工具注册和 Code Mode 注册来验证“三工具入口”。Skill 在 `codex/plugins/phyxi-catia`，安装/更新后应为0.2.0；如果此前启用了自带 MCP 的替代插件，应先切换到 skill-only 安装，防止重复注册。

CLI示例（把路径替换为实际安装）：

```powershell
python code_mode/cli.py --backends C:/path/to/backends.json --node C:/path/to/node.exe catalog --server native-modeling --names modeling_execute
python code_mode/cli.py --backends C:/path/to/backends.json --node C:/path/to/node.exe run --request-id my-new-run-001 --file code_mode/examples/inspect.js
python code_mode/cli.py --backends C:/path/to/backends.json --node C:/path/to/node.exe status --request-id my-new-run-001
```

`examples/flange.js` 展示根据几何规则筛选孔位置、循环生成原生宏、执行并核查保存/重开结果。示例带一次性请求 ID；自行做新设计时必须同时修改外层运行 ID 和代码内 native request ID，不要重放已完成实验。

## 隔离与执行语义

- 用户代码仅在 QuickJS WebAssembly 中运行；不使用 Node eval、vm 或 Function 执行用户代码，无 Node/process/require/fetch/文件/网络 API。Node 和 Python 是可信宿主。
- 限制：代码64KiB，工具参数256KiB，Guest heap32MiB、stack512KiB、Guest CPU2秒（不计等待 MCP）、每程序最多100次桥调用、最终 JSON8KiB。32MiB 是 Guest heap，不是 Node 总内存。
- 工具名和参数按实际加载 schema 验证。Promise.all 的底层派发仍串行；CATIA 不并行执行。未 await 的工具调用报错，但此前可能已有调用执行，必须检查日志。
- **编排代码隔离不等于 CATIA 宏的 OS 沙箱**。原工具能力、原生宏筛选与原共享执行门继续生效。完整脚本不持有跨调用原子锁；需要原子多步骤时从代码生成并调用 `catia_plan_run`。
- 持久化先记录 intent，再调用 MCP，再保存原始结果，最后将结果送回代码。相同 ID+相同代码只读缓存；相同 ID+不同代码拒绝。传输错误/未知结束保持 UNCERTAIN，阻止新任务，不自动重试或重置。
- RUNNING 任务异步执行，前端查询无需等 CAD 返回。关闭服务不是取消 CAD 的证据。进程重启后的遗留 RUNNING/UNCERTAIN 记录仍阻断，当前未提供自动对账/解锁入口，需根据真实底层终态证据处理。
- 只向 Guest 传图片数量；`ptc_status(request_id, include_feedback=true)` 可将本次原生执行器产生的成功或失败候选截图作为真正的 MCP ImageContent 返回给模型，并包含特征/厚度/体积偏差。图片固定绑定任务目录和SHA256，不捕获任意桌面。默认不带图片。模型仍须主动读取、解释和决定修正；封装本身不保证自动识图或自修复。
- 状态记录新增启动、底层MCP及总耗时；完整时序留在本地。观测到未知上游状态的已完成只读查询，会保留上游阻断提示，而不冒充一次未知的CAD写操作；真实写入或传输不确定仍保持阻断。
- SUCCEEDED 表示程序运行完成；`geometry_verified` 保持 false，不能代替独立拓扑、制造或 A 级曲面验收。

依赖 quickjs-emscripten0.32.0（MIT），锁文件固定依赖。安装目录需保留 runtime/node_modules；公共源码不提交该目录。

## 验证

```powershell
$env:PHYXI_PTC_TEST_NODE='C:/path/to/node.exe'
cd code_mode
python -m unittest -v test_engine test_install test_feedback
```

31项测试覆盖循环/分支/聚合、去重、失败停止、未知阻断、schema、CPU/内存/输出/调用上限、Guest不可访问Node、Promise串行、未await报错、安装配置保留、回滚冲突，以及绑定截图、空读回、截图篡改、只读观测分类、具体上游错误保留和异步等待。真实 Codex/CATIA 结果见 [VALIDATION.md](VALIDATION.md)及[PTC对照评测](EVALUATION-20261110.md)。不将引用文章的token或基准提升比例当作本项目实测。

建议把状态检查、执行及结果筛选放入同一个程序；首次只发现所需schema。可用`ptc_status(request_id, wait_ms=20000, include_feedback=true)`异步等待最多20秒以减少模型反复轮询。默认等待0毫秒，不改变CAD状态或重发请求。失败时`upstream_failure.message`保留最多1200字符的具体上游原因，供模型修改新候选。新功能可减少诊断障碍，但不能把修复前实验耗时改写为修复后的成绩。

可用`benchmark.py --backends <本机保护配置> --node <node.exe> --output <新目录>`复现只读传输层对照；无模型推理、无几何写入。每档1/6/18次相同目录查询，默认3重复，交替次序。它测执行开销和序列化数据量，不测模型token、CAD复杂度或自主准确率。已有原生宏/plan也能批处理，因此PTC不保证比这些基线更快。
