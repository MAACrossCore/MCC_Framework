# 每日探索识别区域可视化

本目录保存每日探索关键识别区和点击落点的可视化文件。坐标以
`1920×1080` 为统一基准，运行时由 `agent/viewport.py` 缩放。

- `capacity_overflow_ocr.svg`：仓满弹窗 OCR 区域、实测“确定”文字框与点击中心。
- `sweep_count_controls.svg`：次数页面复核区、当前次数 OCR 区、固定加减按钮。
- `settlement_rows_reference.svg`：结算行文字区域、安全纵坐标和两个芯片槽横坐标。
- `capacity_and_count_source_1280x720.png`：2026-09-09 失败现场原图。
- `chip_finish_home.svg`：芯片任务结束后复用的主页按钮和主页确认识别区域。

## 查看实际 Pipeline

正式流程文件是 `assets/resource/pipeline/base/每日探索.json`、
`assets/resource/pipeline/base/通用-扫荡.json` 和
`assets/resource/pipeline/base/chip.json`，均可直接导入 MPE：

1. 打开 https://mpe.codax.site/stable/ 。
2. 复制目标 JSON 全文。
3. 在 MPE 选择“导入（粘贴板）”。

如需保存回本地，在 `assets/resource` 目录运行 `mpelb`，然后让网页连接
`localhost:9066`。

## 实机查看识别结果

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m MaaDebugger
```

打开 `http://127.0.0.1:8011`，资源目录选择 `assets/resource`，控制器选
`Adb` 并填写 MuMu 的 ADB 路径与地址。带 `Custom` 的节点还需要按
`开发专用.md` 第 2.2 节启动 Agent。
