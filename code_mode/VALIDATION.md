# Code Mode 验证记录 — 2026-11-07

## 实现范围

采用 QuickJS WebAssembly + Python MCP broker，实现 JavaScript 的循环、条件、筛选、聚合、生成原生宏及 MCP Promise 暂停/恢复。没有把 JSON plan 改名冒充代码执行。Codex配置中原两套直接工具注册已禁用并保留，新增 catia-code；Skill-only Plugin更新为0.2.0。现有0.7.0应用、OpenCode WebUI及模型凭据不变。

## 实测

| 项目 | 实际结果 |
|---|---|
| 离线运行与安装测试 | 20项通过，包含真实QuickJS-WASM而非模拟JS执行器 |
| 真实Codex客户端 | CLI0.162.1 app-server连接并只发现catia-code三个工具；旧两套直接工具未启用 |
| Skill | 0.2.0安装成功，skills/list发现，quick_validate通过 |
| CLI代码文件运行 | 两次只读原生状态查询在代码内循环，结果筛选为ready=true |
| CATIA代码编排 | 一段JavaScript在内层执行5次MCP调用，程序循环生成宏及过滤孔位置 |
| 原生零件 | 80×50×8mm底板，中央R12凸台总高12mm，6个D6通孔、1个D10中心通孔 |
| 保存/重开读回 | 1 Body、4个实体特征、4张草图；passed=true、saved=true |
| 体积 | 理论及重开读回均为31509.91154603999mm³ |
| 去重 | 完成后同ID同代码返回cached_no_dispatch=true，没有再次执行 |
| 结束状态 | 程序SUCCEEDED/KNOWN_FINISHED；查询共享gate为IDLE |

程序由当前Codex编写，随后通过真实Codex客户端提交；没有启动额外自主模型回合，也没有开展多模型对照实验。原底层返回的历史source标签仍为OpenCode_MCP_live_CSharp_STA，未篡改为新的来源；真实客户端证据在本机另存。

## 数据量

只读CLI：两次完整MCP回复合计612字节；最终return值61字节。

原生建模：五次完整MCP回复序列化合计10835字节，最终return值414字节；含请求状态、路径、时间等元数据的最终ptc_status业务JSON为1006字节。程序内部用时39.684秒，包含本次新CATIA实例启动、建模、保存/重开；GuestCPU记录50ms。

上述为特定样例的UTF-8字节计数。原始MCP envelope可能同时含text与structuredContent；414字节不包含状态轮询、schema发现、代码输入、模型推理和协议包装。没有进行传统逐工具模式的受控时延、token或准确率对照，不能推导文章引用的效率提升比例。没有声称总上下文只剩414字节。

## 边界与遗留项

- 验证了编排层及一个新原生演示件，不是104项工具逐项验收、汽车复杂零件、STEP拓扑或A级曲面验收。
- `geometry_verified=false`保留；尺寸/体积检查基于声明要求及执行器读回，非独立需求等价证明。
- 本次catia_connect实际启动一个新实例，初始没有文档；程序对文档列表的数组计数输出为null，因为原工具返回“No documents open in CATIA”字符串，不把null说成计数验证成功。原生执行器另记录original_document_count=0。
- 现有用户文档未主动关闭；完成的新模型留在CATIA中。
- 图片留本地，仅传数量给代码，未新增截图自动回送视觉模型。
- 未提供遗留RUNNING/UNCERTAIN的自动对账；保持阻断，不擅自解锁。一次程序各调用间不具有全局原子锁，要原子跨度仍使用原catia_plan_run。
- 首轮Windows SQLite连接清理问题已修复并复测；100次边界用例最初受12秒测试等待上限中断，扩大测试等待上限后完整20项通过，原失败日志保留。
- 不调用在线模型API，不进行H20部署或恢复CAA工作。
