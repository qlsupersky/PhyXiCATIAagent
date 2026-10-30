# 第三方组件与来源

## OpenCode

专用隔离建模引擎使用官方 npm 包 `@opencode/cli-windows-x64@2.0.20` 中的 Windows x64 可执行文件，SHA-256：

`298d15cf834f828ce85650ab42677061d8a9697686c7e6bb4852bf21a0ff7f23`

MIT 许可证全文见 [bin/OpenCode-LICENSE.txt](bin/OpenCode-LICENSE.txt)。Git 源码中通过 fetch-runtime.ps1 固定下载；Release 包随附该运行时。

通用图文页使用用户另行安装的 OpenCode Desktop 默认服务；本仓库不分发 Desktop。

## Python 与 CAD 依赖

MCP Python SDK、pywin32、SimpleCADAPI、marimo、matplotlib 及传递依赖通过 pip 独立安装，许可证以安装包的 LICENSE / metadata 为准。OpenCascade、VTK 等许可证不因本适配代码而改变。

## 第二套 MCP

可选上游为 https://github.com/daiemon12/catia-v5-mcp-server ，本仓库不捆绑上游或其虚拟环境。

## 项目范围

本目录为新实现的 CATIA 自动化适配代码，不包含原 PhyXiSWAgent DLL、SolidWorks interop、图标、HTML、原服务凭据或客户模型；没有反混淆或复制原插件实现。

CATIA 需用户自己安装并具备相应 Automation / STEP 转换能力。本包不提供 CATIA、CAA SDK 或任何许可绕过。产品名用于说明适配目标，本实现未获得原插件或 Dassault Systèmes 的兼容性认证。

本公开快照没有为项目自有代码新增许可证；公开可访问不改变第三方和原作者权利。
