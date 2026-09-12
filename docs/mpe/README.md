# Agent 流程的 MPE 总览

本目录暂存尚未迁移的历史 Python Custom Action 流程。竞技场与芯片筛选
已经完成迁移，不再维护独立的“Agent流程总览”副本。

竞技场与芯片筛选应直接在 MPE 中打开正式运行文件：

- `assets/resource/pipeline/base/模拟军演.json`
- `assets/resource/pipeline/base/chip.json`

两者均直接包含完整 `$__mpe_code`，可视流程与实际运行流程是同一份文件。

新任务及后续重构应把页面识别、跳转、分支、循环和结束条件写入
`assets/resource/pipeline/base` 的正式可执行 Pipeline，并直接附带 `$__mpe_code`。
Agent 只保留可独立测试的 OCR、计算、配置或单次判断能力。

页面导航使用正式可执行 Pipeline：

- `assets/resource/pipeline/base/界面导航.json`：可复用导航入口及页面识别节点，可直接在 MPE 中打开。
- `assets/navigation/page_graph.json`：页面名称、识别特征、任务归属、录制样本和页面边的机器可读图谱。
- 维护说明见 `docs/zh_cn/develop/page_navigation.md`。
