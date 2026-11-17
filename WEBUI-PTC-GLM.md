# WebUI + GLM-5.3-Flash + Code Mode

2026-11-17 增加 `webui_ptc.py` 专用入口。在现有 WebUI 中输入自然语言，由 GLM-5.3-Flash 编写 JavaScript 编排程序，经 Code Mode 0.3.0 调用既有 MCP 和 CATIA。无需打开 Codex 原生界面。WebUI 工具卡片展示实际 `ptc_execute` 输入中的代码和 request_id，不从助手文字推测程序。

## 启动

使用已有 Python/OpenCode/WebUI 环境，另需安装好的 Code Mode 0.3.0 及其后端配置：

```powershell
python webui_ptc.py --project D:/CAD/WebUI-GLM-PTC-project --workspace D:/CAD/plugin-workspace --server D:/CAD/PhyXiCATIA-CodeMode-0.3.0/code_mode/server.py --backends C:/Users/you/.codex/phyxi-code-mode/backends.json --node D:/node.exe
```

程序会打开浏览器。点击“连接 OpenCode”，选择 `phyxi-glm / GLM-5.3-Flash / PTC` 和 Build，再新建对话。可以输入原生零件建模或既有参数修改要求，也保留图片/文件附件及 OpenCode 其他能力。图片理解仍取决于所接服务，本文轮毂验证为文字修改任务。

本机可从已有 CCSwitch provider 读取 API 配置，默认 provider ID 为 `phyxi-catia-micu-glm-5-3-flash`，可用 `--ccswitch-provider` 改指定项。也可以在启动进程的本地环境中设置 `PHYXI_GLM_BASE_URL`、`PHYXI_GLM_API_KEY`。凭据不写入项目 JSON。

专用服务用 `XDG_CONFIG_HOME` 隔离全局旧 MCP 注册，只配置 `catia-code` 三个程序入口。此 OpenCode 构建会忽略 MCP 的 enabled/disabled 字段，因此不能仅靠这些字段切换。全局 OpenCode/Codex 模型配置保持原值。已连接的 PTC 不因再次点击连接而重新注册，失败连接不自动重连或重放。重复启动会打开已运行的同项目 WebUI。

## 实测范围

GLM-5.3-Flash 实际 WebUI 会话生成 PTC 程序，对 20 辐轮毂的 Hub 高度进行 105→85 mm 修改。先另存副本，207 项参数仅一项变化，6 个原生特征保留，保存重开读回 85 mm、体积 7,633,382.9932 mm³，并导出 STEP。所有几何修改、保存重开及导出经 PTC 执行。首次发现阶段仍继承旧状态接口，后续完成专用配置隔离；最终会话只出现 catia-code 调用，并只读核验实际零件。

初始轮毂会话包含 wait_ms 超限、8192 字节返回超限以及计划结果解析错误。模型随后调整编排并完成任务，不能表述为首次无错。30 秒为真实录屏的剪辑时长，不是任务总耗时。未进行新的多模型速度对比、全部 104 项工具验收或制造认证。

验证包含 WebUI 实际代码展示、项目配置、连接保持及失败不重连，共 13 项相关单元测试通过。本机 API 结果不证明企业 H20 部署性能。
