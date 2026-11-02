# 0.7.0 验证范围

开发验证日期：2026-10-31。公开快照复核日期：2026-11-02。

| 检查 | 开发实测结果 |
|---|---|
| 核心离线回归 | 82 项通过，覆盖原生流程、图文提交、回执、互斥和计划语义 |
| 上游适配契约 | 4 项通过：98 个原 schema、目录过滤、查询预检、图像保留和异常处理；未调用 COM |
| 直接 MCP 多步骤 | 一个请求完成 11 步，保存、关闭、重开后再次检查体积 |
| 11 步样件 | 34557.5192 mm³，保存前和重开后均满足 ±0.1 mm³；重复请求不派发 |
| WebUI 图文任务 | 一次用户提交和一张图；正确读取 3 个红圆、蓝矩形与英文标识 |
| WebUI 建模 | 一次 8 步计划，圆环外半径 30、内半径 10、厚 6 mm；15079.6447 mm³，±0.1 mm³ 检查通过并保存 CATPart |
| 原有工具 | 同轮 OpenCode 文件写入并回读通过 |
| 已安装 Electron | 两套 MCP connected，读取当时 24 模型 / 7 Agent 目录，无浏览器脚本错误 |
| 版本核对 | 实际工具返回的适配器 PID / SHA-256 与安装源码一致 |
| 安装与检查 | Python / JS / PowerShell 语法、桥接编译、七页自检和源码安装一致性通过 |

公开源码发布前重新运行核心离线测试及独立上游契约测试，并检查脚本语法、桥接编译、七页自检、WebUI 静态页面与 Electron 启动。公开阶段未新增真实 CAD 建模测试，不能据此声称新的几何验收。

## 复现

```powershell
$env:PHYXI_TEST_WORK = Join-Path $env:TEMP 'phyxi-offline-tests'
New-Item -ItemType Directory -Force $env:PHYXI_TEST_WORK | Out-Null
python -m unittest discover -s tests -p 'test_*.py' -v
```

未设置上游目录时，4 项适配测试显示 skipped，实际执行 82 项核心测试。要单独运行适配契约，使用上游自己的 venv，设置 `PHYXI_TEST_CATIA_UPSTREAM` 为所验证提交的源码目录，再运行：

```powershell
$env:PHYXI_TEST_CATIA_UPSTREAM = 'C:/Path/To/catia-v5-mcp-server'
& 'C:/Path/To/catia-v5/.venv/Scripts/python.exe' -m unittest discover -s tests -p test_catia_adapter.py -v
```

契约测试不派发 CATIA；历史 `tests/*_validation.py` 可能真实操作 CAD，需先阅读。真实会话、原始日志、客户模型、部署地址和授权存储不公开。两次失败保存未计为通过，修复后使用新的请求。上述检查不构成汽车 A 级曲面认证或全部工具验证。
