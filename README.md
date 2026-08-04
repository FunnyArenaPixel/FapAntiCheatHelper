# FapACH — FAPIXEL 反作弊辅助客户端 MOD

> **Fap**ixel **A**nti**C**heat **H**elper
>
> 我的世界中国版客户端行为包 + 资源包，运行在玩家本地客户端，
> 采集 CPS、准星目标、移动状态等反作弊关键数据，
> 通过 PyRpc 上报给服务端桥接插件，供反作弊系统辅助判定。

---

## 目录

- [核心原理](#核心原理)
- [已实现的功能](#已实现的功能)
- [移动类作弊检测方法论](#移动类作弊检测方法论)
- [使用的技术和 ModSDK 接口](#使用的技术和-modsdk-接口)
- [项目结构](#项目结构)
- [PyRpc 通信协议](#pyrpc-通信协议)
- [服务端桥接插件](#服务端桥接插件)
- [反作弊插件如何对接本 MOD](#反作弊插件如何对接本-mod)
- [反作弊插件如何吸收桥接插件（不再单独部署）](#反作弊插件如何吸收桥接插件不再单独部署)
- [安全约束与局限性](#安全约束与局限性)
- [版本历史](#版本历史)

---

## 核心原理

### 为什么需要客户端辅助反作弊？

服务端反作弊有一个先天盲区：**服务端只能看到结果，看不到过程**。

举几个例子：

| 场景 | 服务端能看到什么 | 服务端看不到什么 |
|------|------------------|------------------|
| KillAura（自动攻击） | 玩家攻击了某实体 | 玩家准星是否瞄准了该实体 |
| 自动连击器/宏 | 玩家 CPS 很高 | 点击间隔是否异常均匀（机器人特征） |
| Sprint Hack | 玩家在移动 | 玩家是否真的按了疾跑键 |
| NoSlowDown | 玩家在移动 | 移动轮盘输入向量与实际速度是否匹配 |

客户端 MOD 运行在玩家本地，可以拿到这些**过程数据**，然后上报给服务端做交叉验证。

### 数据流架构

```
┌──────────────────────────────────────────────────────────────┐
│                        玩家客户端                              │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                 │
│  │ CPS 采集 │   │ 准星采集 │   │ 移动采集 │                 │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘                 │
│       │              │              │                        │
│       └──────────────┼──────────────┘                        │
│                      ▼                                       │
│              FapAchClient (统一上报)                          │
│                      │                                       │
│                      │  NotifyToServer (PyRpc)               │
└──────────────────────┼───────────────────────────────────────┘
                       │
═══════════════════════╪═══════════════════════════════════════
                    网络（WaterdogPE 透明转发）
═══════════════════════╪═══════════════════════════════════════
                       │
┌──────────────────────┼───────────────────────────────────────┐
│                 Nukkit-MOT 服务端                              │
│                      ▼                                       │
│           FapAchBridge (桥接插件)                              │
│                      │                                       │
│                      ▼                                       │
│           ClientDataManager (内存存储)                        │
│                      │                                       │
│                      ▼                                       │
│    VenusAntiCheat 外部查询 getDataManager().get(playerName)   │
└──────────────────────────────────────────────────────────────┘
```

### 核心约束

> ⚠️ **客户端 MOD 代码可被破解修改。客户端数据只能做辅助参考，绝不能作为唯一判定依据。**

客户端 MOD 不是可信环境。作弊者可以：
1. 修改 MOD 代码，使其不上报数据
2. 修改上报的数据值，伪造正常数据
3. 不安装 MOD

因此，**没有上报数据的玩家（null）不应被判定为作弊**，只是缺少辅助信息。

---

## 已实现的功能

### 模块 1：CPS 模式分析（CpsCollector）

**检测目标**：自动连击器、鼠标宏

**原理**：人类点击有天然的随机性，每次点击间隔不完全相同。自动连击器/宏的点击间隔极其均匀，通过统计学指标可以区分。

**采集数据**：

| 指标 | 说明 | 人类典型值 | 机器人典型值 |
|------|------|------------|--------------|
| `avgCps` | 窗口内平均 CPS | 6~10 | 12~20+ |
| `maxCps` | 最近 1 秒峰值 CPS | 8~12 | 15~25+ |
| `intervalStd` | 点击间隔标准差（毫秒） | > 15ms | < 5ms |
| `intervalMin` | 最短间隔（毫秒） | > 50ms | < 30ms |

> `intervalStd` 是检测宏的核心指标。人类即使试图快速连点，每次间隔也有 ±15ms 以上的随机波动；而宏的间隔几乎固定，标准差通常 < 5ms。

**上报频率**：每 2 秒一次（可配置）

---

### 模块 2：准星目标上报（AimCollector）

**检测目标**：KillAura、Reach（范围攻击）

**原理**：正常玩家必须用准星瞄准目标才能攻击。KillAura 修改了攻击逻辑，可以攻击不在准星上的实体。在攻击发生的瞬间，调用 `PickFacing()` 获取准星实际指向的目标，与被攻击的实体对比。

```
正常玩家：victimId == pickEntityId → match=true
KillAura：victimId != pickEntityId → match=false（攻击了准星没瞄准的实体）
```

**⚠️ 触屏兼容性**：

触屏默认模式（未开启分离控制）下，玩家直接点击屏幕上的实体来攻击，屏幕中心准星可能完全不指向被攻击的实体。此时 `match=false` 是**正常的**，不是 KillAura。

| 输入模式 | 分离控制 | 准星检测 | 说明 |
|----------|----------|----------|------|
| 键鼠 | — | ✅ 适用 | 准星固定在屏幕中心 |
| 手柄 | — | ✅ 适用 | 准星固定在屏幕中心 |
| 触屏 + 开启分离控制 | ✅ | ✅ 适用 | 摇杆控制准星方向 |
| 触屏 + 默认模式 | ❌ | ❌ 不适用 | 直接点击屏幕实体攻击 |

客户端自动检测输入模式（`OptionId.INPUT_MODE`）和分离控制开关（`OptionId.SPLIT_CONTROLS`），在每次上报中附带 `aimCheckApplicable` 标记。服务端只在 `aimCheckApplicable=true` 时统计不匹配次数。

**采集数据**：

| 指标 | 说明 |
|------|------|
| `victimId` | 被攻击实体 ID |
| `pickType` | 准星指向类型（Entity / Block / None） |
| `pickEntityId` | 准星指向的实体 ID |
| `match` | victimId 是否等于 pickEntityId |
| `isCrit` | 是否暴击 |
| `inputMode` | 输入模式（0=键鼠, 1=触屏, 2=手柄, -1=未知） |
| `splitControls` | 是否开启分离控制 |
| `aimCheckApplicable` | 准星检测是否适用当前输入模式 |

**服务端聚合指标**：

| 指标 | 说明 | 正常玩家 | KillAura |
|------|------|----------|----------|
| 不匹配率 | match=false 的比例（仅统计适用攻击） | < 5% | > 30% |

> 触屏默认模式玩家：`aimApplicableAttacks` 为 0，`getAimMismatchRate()` 返回 -1.0（不适用），应跳过判定。

**上报频率**：每次攻击时触发（0.15s 冷却防止刷屏）

> `PickFacing()` 返回的 hitPosXYZ 在实体指向时是实体脚底中心坐标，不是射线与碰撞箱的实际交点。但 entityId 是准确的，所以准星检测不受影响。

---

### 模块 3：移动状态交叉验证（MoveCollector）

**检测目标**：Sprint Hack、NoSlowDown、Fly

**原理**：定期采样客户端本地的玩家状态（位置、旋转、输入向量、疾跑/潜行/水中等），上报给服务端，与服务端自己计算的状态做交叉验证。

**采样数据（每次）**：

| 字段 | 来源接口 | 用途 |
|------|----------|------|
| `pos` [x, y, z] | `PosComponentClient.GetPos()` | 位置交叉验证（反飞行/加速） |
| `rot` [yaw, pitch] | `RotComponentClient.GetRot()` | 朝向一致性 |
| `inputVec` [x, y] | `ActorMotionComponentClient.GetInputVector()` | 移动轮盘输入（反 NoSlowDown） |
| `sprint` | `PlayerCompClient.isSprinting()` | 疾跑状态（反 Sprint Hack） |
| `sneak` | `PlayerCompClient.isSneaking()` | 潜行状态 |
| `inWater` | `PlayerCompClient.isInWater()` | 水中状态（速度计算） |
| `onLadder` | `PlayerCompClient.IsOnLadder()` | 梯子上（速度计算） |
| `gliding` | `PlayerCompClient.isGliding()` | 鞘翅飞行 |

**采样频率**：每 0.5 秒采样一次，每 2 秒上报一批（最多 8 条）

**服务端交叉验证示例**：

```
SprintHack 检测：
  服务端 player.isSprinting() != 客户端 data.moveSprinting → 状态不一致

NoSlowDown 检测：
  inputVec 幅度大（玩家在推摇杆），但实际速度不降 → 可能在使用物品/潜行时不减速
```

> 📖 移动类作弊的详细检测原理见下方 [移动类作弊检测方法论](#移动类作弊检测方法论) 章节。

---

## 移动类作弊检测方法论

> 本章节详细说明移动相关的各种作弊类型的检测原理，以及 FapACH 客户端数据在其中的具体作用。

### 检测架构：三层防线

```
第一层：Nukkit-MOT 引擎服务端权威移动
├── 引擎内置位置验证，超出物理预期就橡皮筋回拉
├── 能抓：最基础的飞行、穿墙、超速
└── 抓不了：绕过引擎逻辑的状态篡改

第二层：VenusAntiCheat 服务端启发式（主力）
├── 在引擎之上做统计分析：位移/秒、包频率、状态转移合法性
├── 能抓：速度异常、飞行、sprint 状态矛盾
└── 困难：看不清客户端真实输入和引擎状态

第三层：FapACH 客户端辅助数据（本 MOD）
├── 提供服务端拿不到的数据：输入向量、引擎状态、环境信息
├── 用途：降误判（排除合法场景）+ 增精度（补充新维度）
└── 约束：客户端代码可被破解，数据只能做辅助参考
```

---

### Sprint Hack（疾跑作弊）

#### 作弊者做什么

| 变种 | 原版限制 | 外挂绕过方式 |
|------|----------|-------------|
| 全向疾跑 | 只能向前疾跑 | 任意方向都享受疾跑速度 |
| 无声疾跑 | 疾跑额外消耗饥饿值 | 不消耗饥饿值 |
| 强制疾跑 | 需双击或按键触发 | 强制锁定疾跑状态 |
| 疾跑+潜行 | 潜行时不能疾跑 | 同时触发两种状态 |

#### 服务端检测原理

**核心：速度向量 vs 疾跑状态的矛盾**

```
正常玩家：
  移动方向 = 前方 → 疾跑速度 ≈ 5.6 格/秒
  移动方向 = 侧/后 → 非疾跑速度 ≈ 4.3 格/秒

SprintHack（全向疾跑）：
  玩家向侧面/后方移动，但速度 = 疾跑速度（5.6）
  → 方向和速度不匹配 → 异常
```

服务端追踪每个移动包的位移向量和水平速度，对比 `PlayerActionEvent`（StartSprinting=9 / StopSprinting=10）和实际速度。

#### FapACH 能补充什么

```
场景：服务端看到玩家在疾跑速度移动，但 PlayerActionEvent 中没有 StartSprinting

没有 FapACH：服务端只能怀疑是 sprint hack（但也可能是网络丢包导致的状态包丢失）

有 FapACH：
  inputVec = (0.0, 0.87)   ← 玩家确实推轮盘向前了
  sprint   = true           ← 引擎确认确实在疾跑
  → 引擎层面的真实疾跑，非状态包伪造
  → 进一步查 inputVec 方向是否合法（是否向前）
```

#### ⚠️ FapModMain 自动疾跑兼容性

FAPIXEL 服务器的 FapModMain MOD 有自动疾跑功能（按键切换，按前进键自动触发疾跑）。
该功能通过引擎 API `BeginSprinting()` 实现，走的是**原版疾跑逻辑**：

- 客户端 `isSprinting()` → `true`
- 服务端 `player.isSprinting()` → `true`
- 两端始终一致，**不会触发 SprintHack 检测**

自动疾跑改变的是「怎么触发」疾跑（一键 vs 双击），但触发后引擎对两端报告的是同一个状态。只有绕过引擎直接伪造 sprint 状态的外挂才会造成两端不一致。

---

### NoSlowDown（不减速作弊）

#### 作弊者做什么

原版 MC 中，以下行为会**减速到正常的 ~35%**：

| 行为 | 正常减速 | NoSlowDown 绕过 |
|------|----------|-----------------|
| 进食/喝药水 | 移动速度 ×0.35 | 保持正常速度 |
| 拉弓（弓/三叉戟） | 移动速度 ×0.35 | 保持正常速度 |
| 举盾格挡 | 移动速度 ×0.35 | 保持正常速度 |
| 潜行 | 移动速度 ×0.3 | 保持正常速度 |
| 在灵魂沙/蛛网上 | 移动速度 ×0.4 | 保持正常速度 |

#### 服务端检测原理

**核心：位移速度 vs 当前活动状态的矛盾**

```java
// VenusAntiCheat 检测逻辑（简化）
double speed = calculateHorizontalSpeed(player);

if (player.isSneaking()) {
    double expectedMax = baseSpeed * 0.3;
    if (speed > expectedMax * tolerance) {
        flag(player, "NoSlowDown");
    }
}
// 潜行状态 → 期望速度降低，实际速度没降 → 异常
```

**服务端困难点**：Nukkit-MOT 能通过数据包推断玩家是否「正在使用物品」，但精度有限、有延迟。

#### FapACH 当前数据 vs 缺口

**已采集**：`sprint` / `sneak` / `inWater` / `onLadder` / `gliding` — 可检测潜行不减速、水中异常速度等。

**⚠️ 缺口**：是否正在使用物品（拉弓/进食/举盾）。

ModSDK 没有直接的 `isUsingItem()` 查询接口，但有相关事件可监听：

| 事件 | 用途 |
|------|------|
| `ClientItemTryUseEvent` | 玩家右键尝试使用物品时触发 |
| `ItemReleaseUsingClientEvent` | 释放使用中的物品时触发 |

> 补充 `usingItem` 状态采集是 FapACH 的一个待办改进点。加上之后 NoSlowDown 检测链路就完整了。

---

### Fly / Survival Fly（飞行作弊）

#### 作弊者做什么

| 变种 | 原理 | 检测难度 |
|------|------|----------|
| Vanilla Fly | 直接修改 Y 轴位置，无视重力 | 最基础，引擎层可抓 |
| Jetpack | 每帧给微小向上速度 | 较隐蔽，需持续监控 |
| AirJump | 空中再次跳跃 | 类似二段跳 |
| Glide | 降低下落速度，模拟鞘翅 | 最难抓 |
| NoFall | 伪造落地包取消掉落伤害 | 不影响位置，只影响伤害 |

#### 服务端检测原理（多维度交叉）

**维度 1：Y 轴速度**

```
正常：空中时 Y 速度持续下降（受重力约束）
异常：Y 速度 > 0 且不在跳跃/鞘翅/漂浮/骑乘状态 → 飞行
```

**维度 2：滞空时间**

```java
if (airTime > maxAirTimeForJumpHeight &&
    !player.isGliding() &&
    !hasEffect(LEVITATION)) {
    flag(player, "SurvivalFly", airTime);
}
```

**维度 3：连续 Y 变化模式**

```
正常跳跃：↑↑↑（递减上升）→ 顶点 → ↓↓↓（加速下落）
Fly：↑↑↑↑↑（持续上升）或 →→→（水平悬停）
```

**维度 4：落地包验证（NoFall）**

```
正常：落地时发送正确 fallDistance，引擎据此计算伤害
NoFall：发送 fallDistance=0 或取消落地事件
检测：服务端自己追踪 Y 轴下落距离，与客户端声称的对比
```

#### FapACH 能补充什么

**核心价值：降低误判**

服务端怀疑飞行时，FapACH 的数据可以排除合法场景：

```
场景 1：服务端看到 Y 持续上升 → 怀疑 Fly
  FapACH：gliding=true（鞘翅飞行中）→ 合法，排除 ✅

场景 2：服务端看到空中停留很久 → 怀疑 Fly
  FapACH：onLadder=true（在梯子上）→ 合法，排除 ✅

场景 3：服务端看到缓慢下落 → 怀疑 Glide
  FapACH：inWater=true（在水中）→ 水的浮力，合法，排除 ✅

场景 4：服务端看到 Y 上升 → 怀疑 Fly
  FapACH：gliding=false, onLadder=false, inWater=false
  → 没有任何合法理由 → 确认 Fly ❌
```

当前 FapACH 已采集所有需要的环境状态（`inWater`/`onLadder`/`gliding`），对 Fly 检测的误判降低非常有价值。

---

### Speed（超速）

#### 作弊者做什么

直接修改移动速度倍率，让角色移动速度超过合法上限。

#### 服务端检测原理

```java
// 每个 tick 计算
double horizontalSpeed = Math.sqrt(dx*dx + dz*dz) / deltaTime;

// 计算合法最大速度
double maxSpeed = baseSpeed;         // ≈ 4.3 格/秒
if (player.isSprinting()) maxSpeed *= 1.3;  // ≈ 5.6
if (hasSpeedEffect)       maxSpeed *= 1.0 + 0.2 * amplifier;
if (player.isFlying())    maxSpeed *= 2.0;
maxSpeed *= 1.1;  // 10% 容差（防网络延迟误判）

if (horizontalSpeed > maxSpeed) {
    flag(player, "Speed");
}
```

#### FapACH 能补充什么

```
服务端计算：实际速度 = 7.2 格/秒（超过 sprint 上限 5.6）
FapACH 上报：inputVec = (0.0, 1.0)  ← 满力向前
              sprint = true
              → inputVec 方向 = 位移方向（没有推力篡改）
              → sprint = true（疾跑速度合法）
              → 但实际速度 > 疾跑上限 → 外挂修改了移动倍率
```

---

### 其他移动作弊

| 作弊 | 原理 | 服务端检测 | FapACH 补充 |
|------|------|------------|-------------|
| Step（自动上台阶） | 不跳跃直接走上 1 格高方块 | Y 突变 + 无跳跃事件 | `OnLocalPlayerStartJumpClientEvent` 验证是否真的跳了 |
| Spider（爬墙） | 沿垂直墙壁上升 | Y 增加 + 接触墙壁 + 非 `onLadder` | `onLadder=false` 确认不在梯子上 |
| Jesus（水上行走） | 在水面不下沉 | Y 在水面 + 非 `inWater` + 非 `isSwimming` | `inWater=false` 确认不在水中 |

---

### 客户端 vs 服务端分工总结

| 检测项 | 服务端独自 | + FapACH 辅助 |
|--------|-----------|---------------|
| 基础 Fly / Speed | ✅ 能抓 | 降误判（排除合法场景） |
| SprintHack（方向矛盾） | ⚠️ 间接推断 | ⭐ `inputVec` 提供方向数据 |
| NoSlowDown | ⚠️ 精度低 | ⭐ 需补充 `usingItem` 状态后大幅提升 |
| Glide 误判排除 | ⚠️ 经常误判 | ⭐ `inWater`/`onLadder`/`gliding` 排除合法场景 |
| NoFall | ⚠️ 依赖落地包 | ⚠️ 客户端可伪造落地距离 |

---

### 模块 4：配置同步（ConfigSync）

服务端可通过 PyRpc 向客户端动态推送配置：

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `enableCps` | 'true'/'false' | CPS 模块开关 |
| `enableAim` | 'true'/'false' | 准星模块开关 |
| `enableMove` | 'true'/'false' | 移动模块开关 |
| `cpsReportInterval` | float | CPS 上报间隔（秒） |
| `aimCooldown` | float | 准星上报冷却（秒） |
| `moveSampleInterval` | float | 移动采样间隔（秒） |
| `moveReportInterval` | float | 移动上报间隔（秒） |

在客户端就绪时（`FapAchClientReady`），服务端自动推送一次默认配置。

---

## 使用的技术和 ModSDK 接口

### 技术栈

| 层 | 技术 |
|----|------|
| 运行环境 | 我的世界中国版客户端 ModSDK（Python 2.7） |
| 通信协议 | PyRpc（Nukkit-MOT 内置的客户端↔服务端消息桥） |
| 定时调度 | `OnScriptTickClient` 引擎脚本刻（30 Hz） |

### 核心事件

| 事件 | 方向 | 说明 |
|------|------|------|
| `LeftClickBeforeClientEvent` | 引擎→客户端 | 攻击键按下，CPS 采集的触发点 |
| `PlayerAttackEntityEvent` | 引擎→客户端 | 本地玩家攻击实体，准星采集的触发点 |
| `OnScriptTickClient` | 引擎→客户端 | 脚本刻（每秒 30 次），定时调度 |
| `UiInitFinished` | 引擎→客户端 | UI 初始化完成，获取有效 playerId |

### 核心接口

| 接口 | 组件 | 用途 |
|------|------|------|
| `PickFacing()` | `CameraComponentClient` | 获取准星指向的实体/方块 |
| `GetPos()` | `PosComponentClient` | 获取玩家位置 |
| `GetRot()` | `RotComponentClient` | 获取玩家旋转角度 |
| `GetInputVector()` | `ActorMotionComponentClient` | 获取移动轮盘输入向量 |
| `isSprinting()` | `PlayerCompClient` | 是否疾跑 |
| `isSneaking()` | `PlayerCompClient` | 是否潜行 |
| `isInWater()` | `PlayerCompClient` | 是否在水中 |
| `IsOnLadder()` | `PlayerCompClient` | 是否在梯子上 |
| `isGliding()` | `PlayerCompClient` | 是否鞘翅飞行 |
| `NotifyToServer()` | `ClientSystem` | 向服务端发送 PyRpc 事件 |
| `ListenForEvent()` | `ClientSystem` | 监听引擎/自定义事件 |
| `GetLocalPlayerId()` | `clientApi` | 获取本地玩家 ID |
| `GetLevelId()` | `clientApi` | 获取关卡 ID（创建 Camera 组件用） |

---

## 项目结构

```
FapAntiCheatHelper/
├── behavior_pack/
│   ├── pack_manifest.json        # 行为包清单（UUID: ea6986a9-...）
│   └── FapAchScripts/
│       ├── __init__.py
│       ├── modMain.py            # MOD 入口，注册客户端系统
│       ├── modConfig.py          # 全局配置常量 & PyRpc 事件名
│       ├── clientSystem.py       # 客户端主系统（事件分发 + 上报统一出口）
│       ├── cpsCollector.py       # 模块1：CPS 模式分析采集器
│       ├── aimCollector.py       # 模块2：准星目标上报采集器
│       └── moveCollector.py      # 模块3：移动状态交叉验证采集器
├── resource_pack/
│   └── pack_manifest.json        # 资源包清单（UUID: 9bb55178-...）
└── VENUS_INTEGRATION.md          # VenusAntiCheat 对接预留点文档
```

---

## PyRpc 通信协议

### 事件名一览

| 方向 | 事件名 | 频率 | 触发条件 |
|------|--------|------|----------|
| C→S | `FapAchClientReady` | 进服 1 次 | 客户端 UI 初始化完成 |
| C→S | `FapAchCpsReport` | 每 2 秒 | CPS 统计窗口到期 |
| C→S | `FapAchAimReport` | 每次攻击（0.15s 冷却） | 玩家攻击实体 |
| C→S | `FapAchMoveReport` | 每 2 秒 | 移动采样缓冲区到期 |
| S→C | `FapAchConfigSync` | 客户端就绪时 | 推送采集参数配置 |

### namespace / systemName

```
MOD 名称:   FapAch
客户端系统:  FapAchClient
服务端系统:  FapAchServer（虚拟，仅用于服务端→客户端发事件时的 target）
```

### ⚠️ PyRpc 序列化注意事项

- **boolean 值必须用字符串 `'true'`/`'false'` 传输**（PyRpc 对 Python bool 序列化不可靠）
- 所有 dict key/value 均为基础类型（str/int/float/list）

---

## 服务端桥接插件

客户端采集的数据由 **[FapAchBridge](https://github.com/FunnyArenaPixel/FapAchBridge)** 插件接收和存储。

```
FapAchBridge (Nukkit-MOT 插件)
├── 监听 4 个 PyRpc 事件（CpsReport / AimReport / MoveReport / ClientReady）
├── 数据存储在 ClientDataManager（ConcurrentHashMap，线程安全）
├── 提供公开 API getDataManager() 供其他插件查询
└── 管理命令 /fapach <status|info <player>|list>
```

详见 FapAchBridge 仓库的 README。

---

## 反作弊插件如何对接本 MOD

### 步骤 1：部署 FapAchBridge

将 `FapAchBridge-x.x.x.jar` 放入服务端 `plugins/` 目录。确保 `NukkitMaster` 已安装。

### 步骤 2：在反作弊插件中查询数据

```java
// 获取 FapAchBridge 实例
FapAchBridge bridge = (FapAchBridge) getServer().getPluginManager().getPlugin("FapAchBridge");
if (bridge == null) return;  // FapAchBridge 未安装，跳过

ClientDataManager mgr = bridge.getDataManager();
ClientData data = mgr.get(player.getName());
if (data == null) return;    // 玩家没有安装客户端 MOD，无数据（不能判作弊）
```

### 步骤 3：在你的检测逻辑中使用数据

```java
// ========== CPS 模式分析 → 自动连击器检测 ==========
if (data.cpsMax > 15 && data.cpsIntervalStd < 5.0) {
    // 峰值 CPS > 15 且间隔标准差 < 5ms → 高概率自动连击器
    flag(player, "AutoClicker", data.cpsMax, data.cpsIntervalStd);
}

// ========== 准星分析 → KillAura 检测 ==========
if (data.aimTotalAttacks > 10 && data.getAimMismatchRate() > 0.3) {
    // 30% 以上的攻击没瞄准目标 → 高概率 KillAura
    flag(player, "KillAura", data.getAimMismatchRate(), data.aimTotalAttacks);
}

// ========== 移动交叉验证 → Sprint Hack 检测 ==========
boolean serverSprinting = player.isSprinting();
if (data.moveSprinting != serverSprinting) {
    // 客户端报告的疾跑状态与服务端不一致
    flag(player, "SprintHack", serverSprinting, data.moveSprinting);
}
```

---

## 反作弊插件如何吸收桥接插件（不再单独部署）

如果你不想在服务器上额外部署一个 `FapAchBridge` 插件，可以把它的功能直接**整合进 VenusAntiCheat**。以下是完整步骤：

### 方案概述

将 FapAchBridge 的三个核心类（`ClientData`、`ClientDataManager`、PyRpc 监听逻辑）复制到 VenusAntiCheat 的包结构中，让 VenusAntiCheat 自己注册 PyRpc 监听、自己存储数据、自己查询。

### 具体步骤

#### 1. 复制数据类

把以下两个文件复制到 VenusAntiCheat 的源码包中（例如 `cn.ElysianArena.VenusAntiCheat.ach`）：

- `ClientData.java` — 单玩家数据快照（不需修改）
- `ClientDataManager.java` — 数据管理器（不需修改）

#### 2. 在 VenusAntiCheat 主类中注册 PyRpc 监听

在 `onEnable()` 中添加：

```java
private NukkitMaster nm;
private ClientDataManager achDataManager = new ClientDataManager();

@Override
public void onEnable() {
    // ... 你原有的初始化代码 ...

    // 获取 NukkitMaster
    nm = (NukkitMaster) getServer().getPluginManager().getPlugin("NukkitMaster");
    if (nm == null || !nm.isEnabled()) {
        getLogger().warning("NukkitMaster not found, FapACH data collection disabled.");
    } else {
        registerAchListeners();
    }
}

private void registerAchListeners() {
    String modName = "FapAch";
    String clientSystem = "FapAchClient";

    nm.listenForEvent(modName, clientSystem, "FapAchCpsReport",
            (PyRpcHandler) (player, data) -> {
                achDataManager.updateCps(player.getName(), data);
            });

    nm.listenForEvent(modName, clientSystem, "FapAchAimReport",
            (PyRpcHandler) (player, data) -> {
                achDataManager.updateAim(player.getName(), data);
            });

    nm.listenForEvent(modName, clientSystem, "FapAchMoveReport",
            (PyRpcHandler) (player, data) -> {
                achDataManager.updateMove(player.getName(), data);
            });

    nm.listenForEvent(modName, clientSystem, "FapAchClientReady",
            (PyRpcHandler) (player, data) -> {
                // 解析 modules 字段
                String version = String.valueOf(data.getOrDefault("version", ""));
                Object modules = data.get("modules");
                boolean cps = false, aim = false, move = false;
                if (modules instanceof Map) {
                    Map<?, ?> mod = (Map<?, ?>) modules;
                    cps  = "true".equalsIgnoreCase(String.valueOf(mod.get("cps")));
                    aim  = "true".equalsIgnoreCase(String.valueOf(mod.get("aim")));
                    move = "true".equalsIgnoreCase(String.valueOf(mod.get("move")));
                }
                achDataManager.markReady(player.getName(), version, cps, aim, move);

                // 推送配置同步
                Map<String, Object> payload = new HashMap<>();
                payload.put("enableCps", "true");
                payload.put("enableAim", "true");
                payload.put("enableMove", "true");
                nm.notifyToClient(player, "FapAch", "FapAchServer", "FapAchConfigSync", payload);
            });

    getLogger().info("FapACH PyRpc listeners registered (4 events).");
}
```

#### 3. 在玩家退出时清理数据

```java
@EventHandler
public void onPlayerQuit(PlayerQuitEvent event) {
    achDataManager.remove(event.getPlayer().getName());
    // ... 你原有的退出处理 ...
}
```

#### 4. 在检测逻辑中直接查询（无需跨插件调用）

```java
ClientData data = achDataManager.get(player.getName());
if (data != null) {
    // 直接使用 data.cpsIntervalStd / data.getAimMismatchRate() / data.moveSprinting 等
}
```

#### 5. 在 pom.xml 中添加 NukkitMaster 依赖

```xml
<dependency>
    <groupId>com.neteasemc</groupId>
    <artifactId>nukkitmaster</artifactId>
    <version>1.0.0</version>
    <scope>provided</scope>
</dependency>
```

> 如果 VenusAntiCheat 的 `pom.xml` 中已有 `server-1.0.0.jar`（Nukkit-MOT 核心），NukkitMaster 的 `PyRpcHandler` 接口也在其中，无需额外依赖。

### 吸收后 vs 独立部署对比

| | 独立部署 FapAchBridge | 吸收进 VenusAntiCheat |
|---|---|---|
| 插件数量 | +1 个 jar | 0（合并） |
| 跨插件调用 | 需要 `getPlugin("FapAchBridge")` | 直接访问 `achDataManager` |
| 数据查询 | `bridge.getDataManager().get(name)` | `achDataManager.get(name)` |
| 维护成本 | 两个仓库分别维护 | 一个仓库统一维护 |
| 代码量 | ClientData + ClientDataManager + FapAchBridge 主类 | 只需 ClientData + ClientDataManager（约 250 行） |

---

## 安全约束与局限性

### 客户端数据不可信

1. **MOD 代码可被修改**：作弊者可以反编译、修改行为包，使其上报假数据或不上报
2. **没有数据 ≠ 作弊**：未安装 MOD 的玩家不会有数据（`get()` 返回 null），此时应跳过，不能判定
3. **数据有延迟**：CPS/移动每 2 秒上报一次，不能用于实时拦截，只能用于事后分析/标记
4. **数据仅作辅助**：必须与服务端自身的检测逻辑配合，不能作为唯一判定依据

### 建议的使用方式

```
客户端数据（辅助参考） + 服务端检测（主要依据） → 综合判定
```

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.0.1 | 2026-08-04 | 初始版本：CPS 模式分析 + 准星目标上报 + 移动状态交叉验证 + 配置同步 |
| v0.0.1 (文档) | 2026-08-04 | README 新增移动类作弊检测方法论章节（Sprint Hack / NoSlowDown / Fly / Speed 详解） |

---

## 相关仓库

- **[FapAchBridge](https://github.com/FunnyArenaPixel/FapAchBridge)** — 服务端桥接插件（接收和存储采集数据）
- **[VenusAntiCheat](https://github.com/FunnyArenaPixel/VenusAntiCheat)** — FAPIXEL 反作弊插件本体
- **[FapModMain](https://github.com/FunnyArenaPixel/FapModMain)** — FAPIXEL 主功能 MOD（独立项目，与本 MOD 无依赖关系）
