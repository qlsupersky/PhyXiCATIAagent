# 第二套 CATIA MCP 接入

第二套服务基于 [daiemon12/catia-v5-mcp-server](https://github.com/daiemon12/catia-v5-mcp-server)；本地验证时固定提交为 `ae47bbf6353cf16bda78e23640db6012de890471`。该上游仓库和其虚拟环境没有复制到本仓库。

插件会继承 OpenCode 中名称为 `catia-v5` 的本地 MCP 配置。上游服务的部署按其说明进行，生产协作时还需使其执行包装层使用本项目 `native_gate.SessionGate`，且两套服务指向同一个 SQLite 路径。仅设置环境变量不代表上游自动实现了共享互斥。

本仓库包含 `native-modeling` 完整服务。第二套服务在本机原部署中已验证，但本公开快照不会把用户本机绝对路径、配置和运行库作为通用安装配置发布。若只部署 native-modeling，专用原生宏流程仍可工作。
