# 0.6.4 原生建模与双 MCP

native-modeling 提供 modeling_execute、modeling_run、modeling_status；核心流程为自然语言生成专属完整 CATScript，执行后独立回读特征和体积、保存、重新打开并截图。

已部署第二套 catia-v5 时，插件隔离引擎会继承默认 OpenCode 配置中的对应启动项。第二套提供固定的 98 个 CATIA Automation 工具，可用于细粒度查询、草图、实体和曲面操作。

正确编号写法：doc.Product.PartNumber="BrakeDisc"。Part 不提供 PartNumber。明确脚本引擎错误自动标记失败并释放，无需开发者解锁。完整错误、历史源码和实际几何验证保留。
