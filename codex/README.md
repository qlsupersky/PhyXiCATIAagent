# Codex 接入：MCP 配置与原生 Skill / Plugin

## 当前推荐：代码编排模式

2026-11-07新增 [Code Mode / PTC](../code_mode/README.md)，Skill更新至0.2.0。下面的直接104工具配置迁移是历史接入路径；新需求采用 JavaScript 编排、三个模型侧入口或代码文件 CLI。两种注册不要同时启用；Code Mode安装器会禁用旧直接条目且保留回滚。

两条路径均已实现。本扩展版本为 **0.1.0**，现有 CATIA 插件和工具服务仍为 **0.7.0**。这里适配的是 MCP 客户端和工作流，未把 CATIA 商业软件重写为 Codex，也未替换现有 WebUI 的 OpenCode 后端。

## 路径一：现有 MCP 直接接入 Codex

现有 `native-modeling`、`catia-v5` 继续以 stdio 运行；Codex 作为新的客户端。无需额外的社区迁移工具。脚本只读取这两个服务器，不迁移模型服务商或认证信息。

在本目录执行（Python 3.11+；实际 CATIA 运行环境推荐 Python 3.12 x64）：

```powershell
python -m pip install -r requirements.txt
python migrate_mcp.py --source "C:\Path\To\opencode.json"
python migrate_mcp.py --source "C:\Path\To\opencode.json" --apply
codex mcp list --json
```

默认目标是 Codex home 下的 `config.toml`，也可通过 `--config` 指定。默认只预览，`--apply` 才写入。备份及回滚凭据留在用户配置旁的 `phyxi-backups`；其中完整旧配置可能含敏感信息，不能加入发布包或 Git。回滚：

```powershell
python migrate_mcp.py --rollback "C:\Path\To\phyxi-backups\TIMESTAMP\migration.json"
```

回滚只恢复本次管理的 MCP，保留其后无关设置；若用户已修改这两个 MCP，拒绝覆盖。迁移保留其他 MCP、模型设置及 TOML 注释。两个服务必须沿用同一个 `PHYXI_NATIVE_GATE` 和 `PHYXI_NATIVE_WORKSPACE`，以免 OpenCode/Codex 并行操作 CATIA。仅支持当前项目的 stdio 配置，不是任意 HTTP/MCP 通用转换器。

## 路径二：Codex 原生 Plugin / Skill

默认插件只有 Skill，与路径一组合，避免重复登记服务器：

```powershell
codex plugin marketplace add "C:\Path\To\PhyXiCATIAagent\codex" --json
codex plugin add phyxi-catia@phyxi-catia-local --json
codex plugin list --json
```

在新的 Codex 会话中选择 **CATIA 原生建模** Skill；实际注册名为 `phyxi-catia:catia-native`。示例需求：

> 使用 CATIA 原生建模 Skill，新建一个60×40×6毫米的矩形板，在坐标(±20,±10)处开4个直径6毫米的通孔，保留原生草图和特征，保存后重新打开验证。

也可附加参考图片，要求先区分可见形状、尺寸和假设，再建模。图片理解取决于当前 Codex 模型；本轮没有验证图片自动识别或复杂曲面生成。

Skill 指导 Codex 按自然语言生成 CATScript，经 `modeling_execute` 自动执行、保存、重开、读回；局部编辑、查询和多步骤操作使用原有 `catia-v5` 工具。无需 OpenCode 服务参与 Codex 的模型生成。工具命名以客户端实际暴露值为准，不使用 OpenCode 专属调用语法。

若只需要独立 Skill，可用以下方式**代替**插件安装；不要同时安装两份同名 Skill：

```powershell
python package_extension.py --out "$env:USERPROFILE\.codex\skills\catia-native" --standalone-skill
```

若需要 Plugin 同时携带 MCP，用下面的生成包**代替**全局 MCP 注册；不要两者同时开启：

```powershell
python package_extension.py --out "C:\Path\To\LocalMarketplace" --bundle-mcp "C:\Path\To\opencode.json"
codex plugin marketplace add "C:\Path\To\LocalMarketplace" --json
codex plugin add phyxi-catia@phyxi-catia-local --json
```

该包的 `.mcp.json` 绑定本机启动路径，迁移电脑必须重新生成。本项目不捆绑 CATIA、Python、原安装插件或上游 MCP 的全部运行环境；需先部署它们，并确保 COM 可连接。默认插件是原生 Codex 扩展，并非旧 WebUI 的新皮肤。

## 验证与边界（2026-11-06）

实际客户端为 Codex CLI **0.162.1**。通过其独立 app-server 的 `mcpServerStatus/list`、`mcpServer/tool/call`、`skills/list` 验证，不仅检查配置文件。

| 验证 | 实际结果 |
|---|---|
| 迁移、回滚、配置保留、冲突/环境检查、打包 | 8项离线测试通过 |
| Skill frontmatter | quick_validate 通过 |
| 全局配置 + Skill 插件 | 101个 catia-v5 工具、3个 native-modeling 工具，Skill启用，状态/目录调用成功 |
| 隔离 Codex 配置 + 插件自带 MCP | 同样发现101+3工具，状态/目录调用成功；无全局注册依赖 |
| 实际新建原生零件 | Codex编写的四孔板宏经 Codex MCP客户端执行一次，保存和重开读回通过 |
| 四孔板读回 | 1 Body、2实体特征、2草图；体积13721.415986824606 mm³，理论13721.415986824604 mm³ |
| 执行门 | 实验后实际查询 IDLE；无人工审核步骤 |

四孔板是当前 Codex 编写程序、独立 Codex 客户端调用工具的接入测试；未另外发起自主模型对话回合，未证明所有104工具、复杂车身件、识图闭环、A级曲面或制造验收。底层结果中历史固定标签 `OpenCode_MCP_live_CSharp_STA` 仍可能出现，此标签不代表本次由 OpenCode 发起。保留实际返回值。

配置或插件安装不会即时向已运行会话增加工具。关闭并重新打开使用它的 Codex 会话；必要时重启 Codex 应用。原 OpenCode 功能、当前模型和凭据不改动。超时不代表 CATIA 结束，不重放未知调用；两个客户端共享同一执行门。串行工程互斥继续保留，不是人工审批。

可重新执行只读接入验证（`--codex` 需指向实际 Codex 可执行文件）：

```powershell
python verify_connection.py --codex "C:\Path\To\codex.exe" --out connection.json
python -m unittest -v test_migration
```

验证器不启动模型回合，不调用 CAD 几何工具。`CAD_dispatch:false` 只描述该验证器，不适用于上面的实体验证。

官方参考：[MCP](https://developers.openai.com/codex/mcp/)、[Skills](https://developers.openai.com/codex/skills/)、[Plugins](https://developers.openai.com/codex/plugins/)。本轮访问官方页面收到403；配置和插件格式根据本机 CLI 帮助、生成的协议 schema 及已安装插件验证，未把无法读取的网页视为测试证据。
