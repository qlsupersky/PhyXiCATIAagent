# 开发环境准备状态（2026-11-02）

## 已完成的通用微软工具准备

VS2019 Build Tools 原有未完成安装已续装成功。微软安装器返回 `0`；`vswhere` 同时检测以下四个组件，实例状态为 `isComplete=true`、`isLaunchable=true`、`isRebootRequired=false`：

- `Microsoft.VisualStudio.Component.VC.Tools.x86.x64`
- `Microsoft.VisualStudio.Component.Windows10SDK.19041`
- `Microsoft.VisualStudio.Component.VC.ATL`
- `Microsoft.VisualStudio.Component.VC.ATLMFC`

实际工具为 MSVC **19.29.30159**、Windows SDK **10.0.19041.0**。在 `vcvars64.bat` 初始化的子命令环境中，x64 ATL/COM 内存流写入测试，以及静态 MFC 的初始化、CString 与 CMemFile 读写测试，均完成编译、链接与运行。

这说明当前通用 C++/ATL/MFC 工具可用。**Build Tools 不是完整 Visual Studio IDE，也不是 CAA-RADE；当前尚未确认 B33 官方支持的编译器/SDK/操作系统/RADE 组合。** 如后续 RADE 需要 IDE 集成，应按匹配版本的正式文档补充，不能由本次通用测试推定。

原生 WebView2 宿主的 MSVC 构建与独立运行结果见 [README](README.md)。CATIA 安装及现有插件没有被此次工具补装替换。

## 尚未完成的 CAA 开发环境

目标为 CATIA V5-6R2023 B33 SP4、Windows x64。仍缺匹配的 CAA 开发介质、关键公开头文件与导入库、RADE 构建工具和开发条件；CAA 候选模块尚未编译，尚未在 CATIA 中加载。

已有预检至少检查下列接口文件与库（不是完整 SDK 清单）：

- `CATBaseUnknown.h`、`CATDialog.h`、`CATDlgDialog.h`、`CATApplicationFrame.h`、`CATStateCommand.h`、`CATCreateWorkshop.h`、`CATIAfrGeneralWksAddin.h`、`TIE_CATIAfrGeneralWksAddin.h`。
- `JS0GROUP.lib`、`CATApplicationFrame.lib`、`DI0PANV2.lib`。
- RADE 的 `mkmk`；实际构建还需要 `mkGetPreq`、`mkrtv` 及可工作的开发环境。

本机运行版及安装介质核查没有补齐这些文件。运行安装包里的 RADEInfrastructure 资源不等于完整 RADE 开发包。

## 官方获取与交接

1. 向软件管理员或开发供应商申请 **V5-6R2023/B33 对应 CAA API 介质、win_b64 导入库、CAA-RADE 及所需开发权益**，或使用其已有的匹配开发环境。
2. 取得该版本 Program Directory / Software Prerequisites，确认与 SP4 的兼容关系，以及 MSVC/SDK/RADE/系统版本。SDK 与运行版同为 B33 也不能替代完整兼容性核对。
3. 由账号管理员确认账号站点、产品介质下载和 Support 文档访问权限。公开开发指南说明 CAA 介质通过下载平台获取，开发指南随 CAA 安装，在线开发指南要求 Support 权限。
4. 取得后运行 [预检与构建入口](README.md#caa-后续构建与部署)，保留实际构建和运行视图证据，再进行 CATIA 内的加载、输入、关闭重开及建模验收。

官方入口：

- [软件介质下载](https://software.3ds.com/)
- [Developer Guides](https://www.3ds.com/support/documentation/developer-guides)
- [V5 Program Directory](https://media.3ds.com/support/progdir/all/?pdir=v5)
- [官方支持中心](https://www.3ds.com/support/contact-your-support-center)

本仓库提供自有候选源码和构建脚本，不包含 Dassault SDK、授权文件或商业源代码。上述缺项补齐并完成真实编译与加载之前，仍应将内嵌实现视为实验原型。
