# ensure_mumu 实例发现 Bug：定位与修复说明

**日期**：2026-09-13
**影响版本**：新 UI 包 `v0.6.0-ci.3-gc7c9278`（以及任何含该改动的构建）
**严重程度**：功能完全不可用 —— 每次都启动**错误的、空的**模拟器实例

---

## 一、问题现象

在 UI 里点「开始活动」后，**拉起的模拟器是 `#0 MuMu模拟器121`（空实例，从未使用过）**，
而不是实际在用的 `#1 MuMu模拟器12`。

而且**每次都这样**，即使 `#1` 一直开着。

UI 里的设备配置本身是**正确的**：

```json
// install/config/configs/<id>.json → tasks[Controller].task_option["ADB 默认方式"]
"adb_path": "E:\\MuMuPlayer-12.0\\nx_main\\adb.exe",
"address": "127.0.0.1:16416",
"mumu": { "enable": true, "index": 1, "path": "E:/MuMuPlayer-12.0" },
"device_name": "MuMu模拟器12-MuMuPlayer v5+[1](127.0.0.1:16416)",
"emulator_params": "-v 1",
"device_index": "1"
```

**五项全部指向 `#1`** —— 所以问题不在配置，在预任务的实例发现。

---

## 二、问题位置

| 项 | 内容 |
|---|---|
| **文件** | `agent/ensure_mumu.py` |
| **函数** | `choose_instance()` |
| **行号** | 约 268~299（`install` 副本为 268 起）|
| **调用方** | `main()` 第 613 行 |

---

## 三、根因

### 3.1 病灶代码

```python
def choose_instance(manager, requested=None, preferred_serial="",
                    cached_index=None, fallback_index=None):
    # 已知实例编号（配置 / 缓存 / 上次保存）时只查这几个，不要盲扫 0..9。
    targeted = [ ... requested / cached_index / fallback_index 去重 ... ]

    def collect(indices):
        items = []
        for index in indices:
            info = manager_info(manager, index)
            if info:
                items.append((index, info))
        return items

    found = collect(targeted)
    if not found:                      # ← ★ 这里
        found = collect(range(10))     # ← 全量扫描，永远不会执行
```

### 3.2 为什么会失效

**`manager_info(manager, 0)` 永远能返回数据**（哪怕 `#0` 从未启动过 —— 它只是"未开机"，
但实例本身是注册存在的，`MuMuManager info --vmindex 0` 会正常返回 `error_code: 0`、`index: "0"`）。

于是：

```
targeted = [0]        （来自过期的 config/mumu_runtime.json）
   ↓
found = collect([0]) = [(0, {...})]     ← 非空
   ↓
if not found: 为 False                  ← 全量扫描被跳过
   ↓
只看到 #0 → 选中 #0 → 启动 #0            ← 错误
```

**`#1` 从未被查询过**，所以无论它是否在运行都发现不了。

### 3.3 日志铁证

```
[2026-09-13 12:29:06] 诊断：扫到实例 [(0, {'进程已起': False, '安卓已起': False, 'adb': 'None:None'})]（已耗时 0.2s）
[2026-09-13 12:29:06] [2/3] 使用 MuMu 实例 0
[2026-09-13 12:29:06] 诊断：实例 0 判定为未启动 —— is_process_started=False is_android_started=False
[2026-09-13 12:29:06] 正在启动 MuMu 12 实例 0
```

**只扫到 `#0`**，且**耗时仅 0.1~0.2 秒**（10 次查询若都执行需约 1.1 秒）。

### 3.4 一个容易误判的对照

同一台机器上，用**不带缓存参数**的方式调用同一个函数，却能看到两个实例：

```
[MuMu pretask] 诊断：扫到实例 [(0, ...), (1, {进程已起:True, adb:'127.0.0.1:16416'})]（已耗时 2.6s）
```

**原因**：无参数时 `targeted = []` → `collect([])` 为空 → **触发了全量扫描** ✅

**所以"有时候能扫到两个、有时候只扫到一个"不是间歇性故障**，而是**取决于调用时有没有传
`cached_index`**。排查时若只看到其中一次，极易误判为"MuMu 状态不稳定"。

---

## 四、修法

**恢复全量扫描，删除"只查已知编号"的快路径。**

```diff
-    # 已知实例编号（配置 / 缓存 / 上次保存）时只查这几个，不要盲扫 0..9。
-    targeted = []
-    for candidate in (requested, cached_index, fallback_index):
-        if candidate is None:
-            continue
-        try:
-            value = int(candidate)
-        except (TypeError, ValueError):
-            continue
-        if value not in targeted:
-            targeted.append(value)
-
-    def collect(indices):
-        items = []
-        for index in indices:
-            info = manager_info(manager, index)
-            if info:
-                items.append((index, info))
-        return items
-
-    found = collect(targeted)
-    if not found:
-        if targeted:
-            log(f"已知实例编号 {targeted} 均未命中，回退全量扫描 0-9")
-        found = collect(range(10))
-    if not found:
-        return None, {}
+    # 必须全量扫描 0..9。曾经为了"提速"改成"只查已知编号、查不到才全扫"，
+    # 结果是：索引 0 永远能返回数据 -> found 永远非空 -> 全扫永不执行 ->
+    # 只看到 0 号实例 -> 启动了错误的（空的）模拟器；正在运行的实例反而发现不了。
+    # 实测全量扫描 10 个索引仅约 1.1 秒，这个"优化"本来就不必要。
+    found = []
+    for index in range(10):
+        info = manager_info(manager, index)
+        if info:
+            found.append((index, info))
+    if not found:
+        return None, {}
```

**改动要点**：`requested` / `cached_index` / `fallback_index` 不再影响**扫描范围**，
只在下游的优先级判定里使用（`choose_instance` 后半段原有逻辑不变）。

**同时清理过期缓存**：

```json
// install/config/mumu_runtime.json
- { "root": "E:\\MuMuPlayer-12.0", "vm_index": 0, "adb_serial": "127.0.0.1:16384" }
+ {}
```

（`vm_index: 0` 与 `adb_serial: 127.0.0.1:16384` 都指向已不存在的实例状态，
留着会继续把 `cached_index=0` 喂给 `choose_instance`。）

---

## 五、验证

用**真实场景的调用方式**（带 `cached_index=0`）复现：

```python
idx, info = m.choose_instance(mgr, cached_index=0)
```

**修复前**：

```
诊断：扫到实例 [(0, {'进程已起': False, '安卓已起': False, 'adb': 'None:None'})]
选中实例: 0        ← 错误
```

**修复后**：

```
诊断：扫到实例 [(0, {'进程已起': False, '安卓已起': False, 'adb': 'None:None'}),
                (1, {'进程已起': True,  '安卓已起': True,  'adb': '127.0.0.1:16416'})]（已耗时 1.2s）
选中实例: 1  端口: 16416     ← 正确
```

**端到端验证**：在 UI 里点开始活动，确认不再拉起 `#0 MuMu模拟器121` ✅

---

## 六、为什么这个改动当初就不该加

修复时查到的历史：

| 当时的推断 | 实测 |
|---|---|
| "盲扫 10 个索引，每次 timeout=12 秒，**最坏 120 秒**" | **10 个索引合计约 1.1 秒** ❌ |
| "这是 pretask 卡 60~70 秒的原因" | 真因是 **pretask 路径解析**（解析器在 `DataRoot` 找不到 `ensure_mumu.cmd`，静默降级成裸 `python.exe` 无参数）|

**为一个不存在的性能问题做了"优化"，反而破坏了实例发现。**

### 通用教训

1. **改"看起来低效"的代码前，先量一下它到底多慢** —— 最坏情况的理论值（10 × 12s）
   和实际耗时（1.1s）差了 100 倍，差在"查询不存在的索引会立刻返回"这个事实。
2. **"查不到才回退"这种兜底有陷阱**：兜底的触发条件是"结果为空"，而
   **在这个问题里结果永远不会为空**（索引 0 总有数据），于是兜底形同虚设。
   写这类回退时要想清楚：**什么情况下前置查询会"部分成功但结果不完整"**，
   那种情况是靠 `not found` 检测不到的。
3. **`requested` / `cached_index` 这类"已知信息"只能用于"选中哪个"，
   不能用于"去查哪些"** —— 后者会漏掉"已知信息过期、真实目标在别处"的情形。

---

## 七、待办

| # | 事项 |
|---|---|
| 1 | `install/agent/ensure_mumu.py` 已修 ✅（立即生效，但换发布包会被覆盖）|
| 2 | 源码 `agent/ensure_mumu.py` 已同步修好 ✅，**待提交** |
| 3 | ⚠️ 当前源码分支是 `huangtong`（对应**旧 UI** MFAAvalonia），而运行时是新 UI（MFW）。**提交前需先切到 `test/ui`**，否则修的是不匹配的代码线 |
| 4 | 建议向上游反馈此 Bug 与修法 |
