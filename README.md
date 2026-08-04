# FapACH — FAPIXEL 反作弊辅助客户端 MOD

> **Fap**ixel **A**nti**C**heat **H**elper
>
> 我的世界中国版客户端行为包 + 资源包，运行在玩家本地客户端，
> 采集 CPS、准星目标、移动状态、方块破坏等反作弊关键数据，
> 通过 PyRpc 上报给服务端桥接插件，供反作弊系统辅助判定。

---

## 目录

- [核心原理](#核心原理)
- [检测项总览（按可靠性排序）](#检测项总览按可靠性排序)
- [已实现的功能](#已实现的功能)
  - [模块 1：CPS 模式分析](#模块-1cps-模式分析cpscollector)
  - [模块 2：准星目标上报](#模块-2准星目标上报aimcollector)
  - [模块 3：移动状态交叉验证](#模块-3移动状态交叉验证movecollector)
  - [模块 4：方块破坏时序](#模块-4方块破坏时序blockcollector)
  - [模块 5：配置同步](#模块-5配置同步configsync)
  - [模块 6：FOV 监控](#模块-6fov-监控)
- [移动类作弊检测方法论](#移动类作弊检测方法论)
- [使用的技术和 ModSDK 接口](#使用的技术和-modsdk-接口)
- [项目结构](#项目结构)
- [PyRpc 通信协议](#pyrpc-通信协议)
- [服务端桥接插件](#服务端桥接插件)
- [反作弊插件如何对接本 MOD](#反作弊插件如何对接本-mod)
- [反作弊插件如何吸收桥接插件](#反作弊插件如何吸收桥接插件不再单独部署)
- [性能影响分析](#性能影响分析)
- [安全约束与局限性](#安全约束与局限性)
- [版本历史](#版本历史)

---

## 核心原理

### 为什么需要客户端辅助反作弊？

服务端反作弊有一个先天盲区：**服务端只能看到结果，看不到过程**。

| 场景 | 服务端能看到什么 | 服务端看不到什么 |
|------|------------------|------------------|
| KillAura（自动攻击） | 玩家攻击了某实体 | 玩家准星是否瞄准了该实体 |
| 自动连击器/宏 | 玩家 CPS 很高 | 点击间隔是否异常均匀（机器人特征） |
| Sprint Hack | 玩家在移动 | 玩家是否真的按了疾跑键 |
| NoSlowDown | 玩家在移动 | 移动轮盘输入向量与实际速度是否匹配 |

### 数据流架构

```
┌──────────────────────────────────────────────────────────────┐
│                        玩家客户端                              │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ CPS 采集 │ │ 准星采集 │ │ 移动采集 │ │ 方块采集 │        │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘        │
│       └────────────┼────────────┼────────────┘               │
│                    ▼            ▼                            │
│              FapAchClient (统一上报 + FOV 监控)               │
│                    │  NotifyToServer (PyRpc)                 │
└────────────────────┼─────────────────────────────────────────┘
                     │
═════════════════════╪═════════════════════════════════════════
                  网络（WaterdogPE 透明转发）
═════════════════════╪═════════════════════════════════════════
                     │
┌────────────────────┼─────────────────────────────────────────┐
│                 Nukkit-MOT 服务端                              │
│           FapAchBridge → ClientDataManager → VenusAntiCheat  │
└──────────────────────────────────────────────────────────────┘
```

> ⚠️ **客户端 MOD 代码可被破解修改。客户端数据只能做辅助参考，绝不能作为唯一判定依据。**

---

## 检测项总览（按可靠性排序）

### 第一档：高可靠性（强证据，低误判）

| 检测项 | 采集来源 | 反作弊权重 | 误判可能 | 解决方案 |
|--------|----------|------------|----------|----------|
| **CPS 间隔标准差** | `LeftClickBeforeClientEvent` | ⭐⭐⭐⭐⭐ | 极低 | 人类 > 15ms，宏 < 5ms，界限清晰 |
| **准星目标不匹配率** | `PickFacing()` + `PlayerAttackEntityEvent` | ⭐⭐⭐⭐ | 中（触屏） | 自动检测输入模式，触屏默认模式标记 `aimCheckApplicable=false` |

### 第二档：中可靠性（辅助证据，需结合服务端数据）

| 检测项 | 采集来源 | 反作弊权重 | 误判可能 | 解决方案 |
|--------|----------|------------|----------|----------|
| **速度属性交叉验证** | `GetAttrValue(SPEED)` | ⭐⭐⭐⭐ | 低（药水/附魔） | 同步上报效果列表，排除 speed 药水的合法加速 |
| **状态效果列表** | `GetAllEffects()` | ⭐⭐⭐⭐ | 极低 | 直接获取引擎效果列表，排除合法加速场景 |
| **输入向量 vs 实际速度** | `GetInputVector()` | ⭐⭐⭐ | 低 | 结合 `usingItem`/`sneak` 综合判断 |
| **在地面状态** | `isEntityOnGround()` | ⭐⭐⭐ | 低（刚加载） | 忽略进服后首 2 秒数据 |
| **使用物品状态** | 事件追踪 | ⭐⭐⭐ | 中（瞬间使用） | 三层防护：超时重置 + 切换物品重置 + 字符串传输 |

### 第三档：弱可靠性（参考信息，不能单独判定）

| 检测项 | 采集来源 | 反作弊权重 | 误判可能 | 解决方案 |
|--------|----------|------------|----------|----------|
| **摄像机朝向** | `GetCameraRotation()` | ⭐⭐ | 高（TP 差异） | 分人称统计，合法快速转身不应误判 |
| **视角模式** | `GetPerspective()` | ⭐ | 无 | 仅供参考，区分 FP/TP 基准 |
| **手持物品** | `GetCarriedItem()` | ⭐⭐ | 低 | 辅助判断减速场景 |
| **方块破坏时序** | `StartDestroyBlockClientEvent` | ⭐⭐ | 中（急迫+效率镐） | 用预期时间作基线，仅极快时标记 |
| **FOV 异常** | `GetFov()` | ⭐ | 高（玩家设置） | 仅弱参考，不能单独判定 |

---

## 已实现的功能

### 模块 1：CPS 模式分析（CpsCollector）

**检测目标**：自动连击器、鼠标宏

| 指标 | 说明 | 人类典型值 | 机器人典型值 |
|------|------|------------|--------------|
| `avgCps` | 窗口内平均 CPS | 6~10 | 12~20+ |
| `maxCps` | 最近 1 秒峰值 CPS | 8~12 | 15~25+ |
| `intervalStd` | 点击间隔标准差（毫秒） | > 15ms | < 5ms |
| `intervalMin` | 最短间隔（毫秒） | > 50ms | < 30ms |

**上报频率**：每 2 秒一次（可配置）

---

### 模块 2：准星目标上报（AimCollector）

**检测目标**：KillAura、Reach（范围攻击）、Snap-Aim（瞬间瞄准辅助分析）

```
正常玩家：victimId == pickEntityId → match=true
KillAura：victimId != pickEntityId → match=false
```

**⚠️ 触屏兼容性**：

| 输入模式 | 分离控制 | 准星检测 |
|----------|----------|----------|
| 键鼠 | — | ✅ 适用 |
| 手柄 | — | ✅ 适用 |
| 触屏 + 分离控制 | ✅ | ✅ 适用 |
| 触屏 + 默认模式 | ❌ | ❌ 不适用 |

**v0.0.3 增强字段 — Snap-Aim 分析辅助**：

| 字段 | 来源 | 用途 | 误判场景 |
|------|------|------|----------|
| `camPitch` | `GetCameraRotation()` | 攻击瞬间摄像机 pitch | 第三人称下角度与准星有偏差 |
| `camYaw` | `GetCameraRotation()` | 攻击瞬间摄像机 yaw | 同上 |
| `perspective` | `GetPerspective()` | 视角模式（0=FP/1=TP/2=前视TP） | 需分人称建立基线 |

> ⚠️ **误判说明**：摄像机角度**不能单独作为判定依据**。合法快速转身不应误判为 Snap-Aim。

**上报频率**：每次攻击触发（0.15s 冷却）

---

### 模块 3：移动状态交叉验证（MoveCollector）

**检测目标**：Sprint Hack、NoSlowDown、Fly、Speed

**v0.0.3 增强字段**：

| 字段 | 来源接口 | 用途 | 误判场景与解决 |
|------|----------|------|----------------|
| `effects` | `GetAllEffects()` | 状态效果列表（"speed:1\|strength:0"） | 极低误判。排除 Speed 药水等合法加速 |
| `speedAttr` | `GetAttrValue(SPEED=1)` | 引擎最终移速属性 | 起床战争速度药水正常提速，用 `effects` 交叉验证 |
| `onGround` | `isEntityOnGround()` | 客户端在地面状态 | 刚创建组件默认 True，忽略进服后 2s |
| `carriedItem` | `GetCarriedItem()` | 手持物品标识符 | 辅助 NoSlowDown 判断（拉弓/进食/举盾） |
| `slot` | `GetSlotId()` | 快捷栏槽位 0-8 | 辅助验证手持物品一致性 |
| `lastAction` | `OnLocalPlayerActionClientEvent` | 最近动作枚举值 | 仅记录，不做判定依据 |

**完整采样字段**：

| 字段 | 用途 |
|------|------|
| `pos` [x,y,z] | 位置交叉验证（反飞行/加速） |
| `rot` [yaw,pitch] | 朝向一致性 |
| `inputVec` [x,y] | 移动轮盘输入（反 NoSlowDown） |
| `sprint`/`sneak`/`inWater`/`onLadder`/`gliding`/`usingItem` | 状态标记 |
| **`effects`** | 状态效果列表（排除合法加速） |
| **`speedAttr`** | 引擎移速属性（反 Speed Hack） |
| **`onGround`** | 地面状态（反 Fly） |
| **`carriedItem`** | 手持物品（辅助 NoSlowDown） |
| **`lastAction`** | 最近动作枚举 |

**采样频率**：每 0.5 秒采样，每 2 秒上报一批（最多 8 条）

---

### 模块 4：方块破坏时序（BlockCollector）

**检测目标**：FastBreak（加速破坏）、Nuker（范围破坏）

**采集数据**：开始挖掘时间戳、方块坐标、方块标识符、被敲击面

**⚠️ 误判注意**：
- **急迫 II + 效率 V 镐子**可极快破坏方块，**完全合法**
- 服务端应用 `GetPlayerDestroyTotalTime()` 计算预期时间作基线
- 仅当**显著快于**预期时才标记
- **创造模式下此事件不触发**（方块秒破）

**上报频率**：批量上报，0.5s 冷却

---

### 模块 5：配置同步（ConfigSync）

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `enableCps` / `enableAim` / `enableMove` / `enableBlock` | 'true'/'false' | 各模块开关 |
| `cpsReportInterval` | float | CPS 上报间隔 |
| `aimCooldown` | float | 准星上报冷却 |
| `moveSampleInterval` / `moveReportInterval` | float | 移动采样/上报间隔 |
| `blockReportCooldown` | float | 方块上报冷却 |

---

### 模块 6：FOV 监控

**检测目标**：FOV 修改类作弊

**原理**：每 10 秒检查 FOV，仅当超出正常范围（30°-110°）或剧烈变化（>20°）时上报。

> ⚠️ FOV 异常是**极弱证据**，仅作参考。通过 `FapAchMoveReport` 事件附带 `fovAlert` 字段。

---

## 移动类作弊检测方法论

### 检测架构：三层防线

```
第一层：Nukkit-MOT 引擎服务端权威移动（抓基础飞行/穿墙/超速）
第二层：VenusAntiCheat 服务端启发式（抓速度异常/飞行/状态矛盾）
第三层：FapACH 客户端辅助数据（降误判 + 增精度）
```

### Sprint Hack

**核心：速度方向 vs 疾跑状态的矛盾**

FapACH 补充：`inputVec`（方向数据）+ `speedAttr`（引擎移速值）+ `sprint` 状态

> ⚠️ FapModMain 自动疾跑通过引擎 API `BeginSprinting()` 实现，两端状态一致，不触发检测。

### NoSlowDown

**核心：减速状态下实际速度未降低**

FapACH 采集 `usingItem`（三层防护：事件追踪 + 5s 超时 + 切换物品重置）+ `carriedItem`（判断弓/盾/食物）+ `sneak` 状态

### Fly

**核心价值：降低误判**

| 服务端怀疑 | FapACH 排除 | 结论 |
|------------|-------------|------|
| Y 上升 | `gliding=true` | 鞘翅飞行，合法 ✅ |
| 空中停留 | `onLadder=true` | 在梯子上，合法 ✅ |
| 缓慢下落 | `inWater=true` | 水浮力，合法 ✅ |
| Y 上升 | 全部状态正常 | 确认 Fly ❌ |

### Speed — v0.0.3 增强

```
speedAttr = 0.350, effects = "speed:1" → 速度药水 + 疾跑 → 合法 ✅
speedAttr = 0.350, effects = ""        → 无合法理由    → Speed Hack ❌
```

> ⚠️ **起床战争兼容**：速度药水/跳跃药水是合法效果，`effects` 字段让服务端准确区分。

---

## 使用的技术和 ModSDK 接口

### 核心事件

| 事件 | 说明 |
|------|------|
| `LeftClickBeforeClientEvent` | CPS 采集 |
| `PlayerAttackEntityEvent` | 准星采集 |
| `ClientItemTryUseEvent` / `ItemReleaseUsingClientEvent` | 使用物品状态 |
| `OnCarriedNewItemChangedClientEvent` | 切换主手物品 |
| `OnLocalPlayerActionClientEvent` | 状态转换事件（v0.0.3） |
| `StartDestroyBlockClientEvent` | 方块破坏时序（v0.0.3） |
| `OnScriptTickClient` | 定时调度（30Hz） |
| `UiInitFinished` | UI 初始化完成 |

### 核心接口

| 接口 | 组件 | v0.0.3 新增 |
|------|------|:-----------:|
| `PickFacing()` | `CreateCamera(levelId)` | |
| `GetPos()` / `GetRot()` | `CreatePos` / `CreateRot` | |
| `GetInputVector()` | `CreateActorMotion` | |
| `isSprinting()` / `isSneaking()` / `isInWater()` / `IsOnLadder()` / `isGliding()` | `CreatePlayer` | |
| **`GetAllEffects()`** | `CreateEffect` | ✅ |
| **`GetAttrValue(SPEED)`** | `CreateAttr` | ✅ |
| **`isEntityOnGround()`** | `CreateAttr` | ✅ |
| **`GetCarriedItem()`** / **`GetSlotId()`** | `CreateItem` | ✅ |
| **`GetCameraRotation()`** / **`GetForward()`** / **`GetFov()`** | `CreateCamera` | ✅ |
| **`GetPerspective()`** | `CreatePlayerView` | ✅ |

---

## 项目结构

```
FapAntiCheatHelper/
├── behavior_pack/
│   ├── pack_manifest.json
│   └── FapAchScripts/
│       ├── __init__.py
│       ├── modMain.py            # MOD 入口
│       ├── modConfig.py          # 全局配置 & 事件名
│       ├── clientSystem.py       # 主系统（事件分发 + 上报 + FOV 监控）
│       ├── cpsCollector.py       # 模块1：CPS 模式分析
│       ├── aimCollector.py       # 模块2：准星目标上报
│       ├── moveCollector.py      # 模块3：移动状态交叉验证
│       └── blockCollector.py     # 模块4：方块破坏时序（v0.0.3）
├── resource_pack/
│   └── pack_manifest.json
├── VENUS_INTEGRATION.md
└── README.md
```

---

## PyRpc 通信协议

| 方向 | 事件名 | 频率 |
|------|--------|------|
| C→S | `FapAchClientReady` | 进服 1 次 |
| C→S | `FapAchCpsReport` | 每 2 秒 |
| C→S | `FapAchAimReport` | 每次攻击（0.15s 冷却） |
| C→S | `FapAchMoveReport` | 每 2 秒（含 FOV 异常） |
| C→S | `FapAchBlockReport` | 批量（0.5s 冷却） |
| S→C | `FapAchConfigSync` | 客户端就绪时 |

> namespace: `FapAch` / 客户端系统: `FapAchClient` / 服务端系统: `FapAchServer`
> ⚠️ boolean 必须用字符串 `'true'`/`'false'` 传输

---

## 服务端桥接插件

[FapAchBridge](https://github.com/FunnyArenaPixel/FapAchBridge) — 监听 5 个 PyRpc 事件，存储数据供查询。

管理命令：`/fapach <status|info <player>|list>`

---

## 反作弊插件如何对接本 MOD

```java
FapAchBridge bridge = (FapAchBridge) getServer().getPluginManager().getPlugin("FapAchBridge");
ClientData data = bridge.getDataManager().get(player.getName());
if (data == null) return;  // 未安装 MOD，无数据

// CPS 检测
if (data.cpsMax > 15 && data.cpsIntervalStd < 5.0) {
    flag(player, "AutoClicker");
}

// 准星检测
if (data.aimTotalAttacks > 10 && data.getAimMismatchRate() > 0.3) {
    flag(player, "KillAura");
}

// v0.0.3 增强：Speed 检测（排除药水）
double maxSpeed = baseSpeed;
if (data.moveSprinting) maxSpeed *= 1.3;
if (data.hasSpeedEffect()) maxSpeed *= 1.2;
if (actualSpeed > maxSpeed * 1.1) {
    flag(player, "Speed");
}

// v0.0.3 增强：Fly 检测（排除合法场景）
if (ySpeed > 0 && !data.moveOnGround && !data.moveGliding
        && !data.moveOnLadder && !data.moveInWater) {
    flag(player, "Fly");
}
```

---

## 反作弊插件如何吸收桥接插件（不再单独部署）

<details>
<summary>📖 点击展开整合步骤</summary>

1. 复制 `ClientData.java` + `ClientDataManager.java` 到 VenusAntiCheat 包中
2. 在主类注册 5 个 PyRpc 监听（CpsReport / AimReport / MoveReport / BlockReport / ClientReady）
3. 直接使用 `achDataManager.get(player.getName())` 查询

```java
private ClientDataManager achDataManager = new ClientDataManager();

private void registerAchListeners() {
    String mod = "FapAch", sys = "FapAchClient";
    nm.listenForEvent(mod, sys, "FapAchCpsReport",
        (PyRpcHandler) (p, d) -> achDataManager.updateCps(p.getName(), d));
    nm.listenForEvent(mod, sys, "FapAchAimReport",
        (PyRpcHandler) (p, d) -> achDataManager.updateAim(p.getName(), d));
    nm.listenForEvent(mod, sys, "FapAchMoveReport",
        (PyRpcHandler) (p, d) -> achDataManager.updateMove(p.getName(), d));
    nm.listenForEvent(mod, sys, "FapAchBlockReport",
        (PyRpcHandler) (p, d) -> achDataManager.updateBlock(p.getName(), d));
    nm.listenForEvent(mod, sys, "FapAchClientReady",
        (PyRpcHandler) (p, d) -> { /* markReady + pushConfigSync */ });
}
```

</details>

---

## 性能影响分析

**结论：对服务器性能影响极小。** 纯内存操作，零 I/O。

| 上报类型 | 频率 | 100 人场景 |
|----------|------|------------|
| CPS Report | 2s | ~50 次/s |
| Move Report | 2s | ~50 次/s |
| Aim Report | 0.15s 冷却 | 极端 ~200 次/s |
| Block Report | 0.5s 冷却 | ~50-100 次/s |
| **总计** | | **~150-400 次/s** |

- 每次回调纯内存操作：~1-5 微秒
- 400 次/s × 5μs = **2ms/秒**，占主线程一个 tick（50ms）的 < 4%
- 每玩家 ~300 字节内存，100 人 ≈ **30KB**
- 无数据库 I/O，无外部请求，无主动轮询

所有采样频率和模块开关可通过 `ConfigSync` 动态调整，无需重启。

---

## 安全约束与局限性

1. **MOD 代码可被修改**：作弊者可修改行为包上报假数据或不上报
2. **没有数据 ≠ 作弊**：未安装 MOD 的玩家无数据（null），应跳过，不能判定
3. **数据有延迟**：CPS/移动每 2 秒上报，不能用于实时拦截，只能用于事后分析
4. **数据仅作辅助**：必须与服务端检测配合，不能作为唯一判定依据

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.0.1 | 2026-08-04 | 初始版本：CPS + 准星 + 移动 + 配置同步 |
| v0.0.2 | 2026-08-04 | moveCollector 新增 usingItem 状态采集 |
| v0.0.3 | 2026-08-04 | 增强检测：状态效果直采、速度属性、在地面状态、手持物品、摄像机朝向、视角模式、方块破坏时序、FOV 监控 |

---

## 相关仓库

- **[FapAchBridge](https://github.com/FunnyArenaPixel/FapAchBridge)** — 服务端桥接插件
- **[VenusAntiCheat](https://github.com/FunnyArenaPixel/VenusAntiCheat)** — 反作弊插件本体
- **[FapModMain](https://github.com/FunnyArenaPixel/FapModMain)** — 主功能 MOD（独立项目）
