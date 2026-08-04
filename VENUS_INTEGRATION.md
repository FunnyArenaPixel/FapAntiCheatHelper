# FapAchBridge × VenusAntiCheat 对接预留点

> 本文件记录 VenusAntiCheat 需要配合 FapAchBridge 数据的所有接口和预留点。
> **VenusAntiCheat 插件本体完全不修改**——以下均为可选的外部查询接口。

---

## 数据查询入口

VenusAntiCheat 可通过以下方式获取 FapAchBridge 的采集数据：

```java
// 获取 FapAchBridge 插件实例
FapAchBridge bridge = (FapAchBridge) getServer().getPluginManager().getPlugin("FapAchBridge");
if (bridge == null) return; // FapAchBridge 未安装，跳过

// 获取数据管理器
ClientDataManager mgr = bridge.getDataManager();

// 查询指定玩家的数据
ClientData data = mgr.get(player.getName());
if (data == null) return; // 该玩家没有安装客户端 MOD，无数据
```

---

## 预留点 1：CPS 模式分析 → Combat 检测

### 数据字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `data.cpsAvg` | double | 平均 CPS |
| `data.cpsMax` | int | 峰值 CPS（最近 1 秒） |
| `data.cpsIntervalStd` | double | 点击间隔标准差（毫秒），越低越像宏 |
| `data.cpsIntervalMin` | double | 最短间隔（毫秒） |

### 建议判定逻辑
```java
// 自动连击器/宏检测
if (data.cpsMax > 15 && data.cpsIntervalStd < 5.0) {
    // 峰值 CPS 超过 15 且间隔标准差低于 5ms → 高概率自动连击器
    flag(player, "AutoClicker", data.cpsMax, data.cpsIntervalStd);
}
// 人类正常点击的标准差通常 > 15ms
// 宏/连点器的标准差通常 < 5ms（固定间隔）
```

### 预留位置
- VenusAntiCheat 的 Combat 检测模块中，在 `onAttack` / `onEntityDamage` 事件回调里
- 插入上述查询代码作为辅助判定

---

## 预留点 2：准星目标分析 → Combat/KillAura 检测

### ⚠️ 触屏兼容性（v1.1.0 新增）

触屏默认模式（未开启分离控制）下，玩家直接点击屏幕上的实体来攻击，
屏幕中心准星可能完全不指向被攻击的实体。
此模式下 `victimId != pickEntityId` 是**正常的**，不是 KillAura。

| 输入模式 | 分离控制 | 准星检测 | 说明 |
|----------|----------|----------|------|
| 键鼠 (0) | — | ✅ 适用 | 准星固定在屏幕中心 |
| 手柄 (2) | — | ✅ 适用 | 准星固定在屏幕中心 |
| 触屏 (1) | 开 | ✅ 适用 | 摇杆控制准星方向 |
| 触屏 (1) | 关 | ❌ 不适用 | 直接点击屏幕实体攻击 |

客户端会在每次上报中附带 `aimCheckApplicable` 标记，
服务端只在 `aimCheckApplicable=true` 时统计不匹配次数。

### 数据字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `data.aimTotalAttacks` | int | 累计攻击次数（所有输入模式） |
| `data.aimApplicableAttacks` | int | 准星检测适用的攻击次数 |
| `data.aimMismatchedAttacks` | int | 准星不匹配次数（仅统计适用的攻击） |
| `data.getAimMismatchRate()` | double | 不匹配率（0.0~1.0），无适用攻击时返回 -1.0 |
| `data.aimLastMatch` | boolean | 最近一次攻击是否匹配 |
| `data.aimInputMode` | int | 输入模式：-1=未知, 0=键鼠, 1=触屏, 2=手柄 |
| `data.aimSplitControls` | boolean | 分离控制开关 |
| `data.aimCheckApplicable` | boolean | 准星检测是否适用 |

### 建议判定逻辑
```java
// KillAura/Reach 检测（仅对准星检测适用的输入模式有效）
if (data.aimApplicableAttacks > 10) {
    double rate = data.getAimMismatchRate(); // 基于 aimApplicableAttacks
    if (rate > 0.3) {
        // 超过 30% 的攻击没有瞄准目标 → 高概率 KillAura
        flag(player, "KillAura", rate, data.aimApplicableAttacks);
    }
}
// 注意：触屏默认模式玩家 aimApplicableAttacks 为 0，getAimMismatchRate() 返回 -1.0
// 应跳过判定，不要将 -1.0 误认为 100% 不匹配
```

### 预留位置
- VenusAntiCheat 的 Combat/KillAura 检测模块中
- 在攻击事件回调里查询准星不匹配率作为辅助判定

---

## 预留点 3：移动状态交叉验证 → Moving/Fly 检测

### 数据字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `data.moveX/Y/Z` | double | 客户端报告的位置 |
| `data.moveRotX/Y` | double | 客户端旋转角度 |
| `data.moveSprinting` | boolean | 客户端是否疾跑 |
| `data.moveSneaking` | boolean | 客户端是否潜行 |
| `data.moveInWater` | boolean | 客户端是否在水中 |
| `data.moveOnLadder` | boolean | 客户端是否在梯子上 |
| `data.moveGliding` | boolean | 客户端是否鞘翅飞行 |
| `data.moveUsingItem` | boolean | 客户端是否正在使用物品（NoSlowDown 检测） |
| `data.moveInputX/Y` | double | 移动轮盘输入向量（方向，非速度） |

### Sprint Hack 检测

**作弊变种**：全向疾跑（侧面/后方享受疾跑速度）、无声疾跑（不消耗饥饿值）、强制疾跑、疾跑+潜行同时触发。

**服务端检测核心**：速度向量 vs 疾跑状态的矛盾。服务端追踪每个移动包的位移向量和水平速度，对比 `PlayerActionEvent`（StartSprinting=9 / StopSprinting=10）和实际速度。

```java
// Sprint Hack 检测（服务端 sprint 状态 vs 客户端 sprint 状态）
boolean serverSprinting = player.isSprinting();
if (data.moveSprinting != serverSprinting) {
    // 状态不一致 → 可能使用了 sprint hack
    flag(player, "SprintHack", serverSprinting, data.moveSprinting);
}

// 全向疾跑检测（inputVec 方向 vs 位移方向）
// 正常疾跑只能向前，如果 inputVec 是侧/后方向但速度 = 疾跑速度 → 异常
double speed = calculateHorizontalSpeed(player);
double inputForward = data.moveInputY;  // inputVec 第二项 = 向前大小
boolean movingForward = inputForward > 0.5;
if (serverSprinting && !movingForward && speed > 4.5) {
    // 疾跑状态但没向前推轮盘 → 全向疾跑 hack
    flag(player, "SprintHack-Omni", speed, inputForward);
}
```

> ⚠️ **FapModMain 自动疾跑兼容性**：FAPIXEL 服务器的 FapModMain MOD 有自动疾跑功能（按键切换，
> 按前进键自动触发疾跑）。该功能通过引擎 API `BeginSprinting()` 实现，走的是原版疾跑逻辑，
> 客户端 `isSprinting()` 和服务端 `player.isSprinting()` 始终一致，**不会触发此检测**。
> 此检测只能抓到绕过引擎直接伪造 sprint 状态的外挂。

### NoSlowDown 检测

**作弊变种**：进食/拉弓/举盾/潜行时不减速，保持正常移动速度。

**服务端检测核心**：位移速度 vs 当前活动状态的矛盾。原版中进食/拉弓/举盾时移动速度降为 ~35%，潜行降为 ~30%。

```java
double speed = calculateHorizontalSpeed(player);

// 使用物品不减速检测（FapACH v0.0.2+ 已采集 usingItem）
if (data.moveUsingItem && speed > baseSpeed * 0.35 * tolerance) {
    flag(player, "NoSlowDown-Item", speed, baseSpeed * 0.35);
}

// 潜行不减速检测
if (data.moveSneaking && speed > baseSpeed * 0.3 * tolerance) {
    flag(player, "NoSlowDown-Sneak", speed, baseSpeed * 0.3);
}
```

**`usingItem` 状态采集原理**：
- 客户端通过 `ClientItemTryUseEvent`（右键使用物品）→ 标记 `usingItem=true`
- `ItemReleaseUsingClientEvent`（释放物品）→ 标记 `usingItem=false`
- `OnCarriedNewItemChangedClientEvent`（切换物品）→ 重置为 false
- 超时自动重置（5 秒，防止瞬间使用物品如扔药水不触发释放事件导致卡在 true）

### Fly / Survival Fly 检测（降低误判）

**服务端检测**：Y 轴速度、滞空时间、Y 变化模式、落地包验证（多维度交叉）。

**FapACH 核心价值**：排除合法场景，降低误判率。

```java
// 服务端怀疑飞行（Y 异常）时，查 FapACH 数据排除合法场景
if (疑似飞行(player)) {
    if (data.moveGliding) {
        // 鞘翅飞行 → 合法，排除
        return;
    }
    if (data.moveOnLadder) {
        // 在梯子上 → 合法，排除
        return;
    }
    if (data.moveInWater) {
        // 在水中（浮力）→ 合法，排除
        return;
    }
    // 没有任何合法理由 → 确认 Fly
    flag(player, "SurvivalFly");
}
```

### Speed 检测

**服务端检测**：每个 tick 计算水平位移速度，与当前状态的合法上限对比（疾跑 ×1.3、速度药水 ×1.2、飞行 ×2.0 等），留 10% 容差。

**FapACH 补充**：`inputVec` 方向与位移方向交叉验证，`sprint` 状态确认疾跑合法性。

### 预留位置
- VenusAntiCheat 的 Moving 检测模块中
- 在移动事件回调里查询客户端报告的状态进行交叉验证
- 详见 FapAntiCheatHelper README 的「[移动类作弊检测方法论](https://github.com/FunnyArenaPixel/FapAntiCheatHelper#移动类作弊检测方法论)」章节

---

## ⚠️ 重要约束

1. **VenusAntiCheat 插件本体完全不修改**
2. 以上所有代码均为 VenusAntiCheat 在自己的检测逻辑中**外部查询** FapAchBridge 数据
3. 客户端 MOD 代码可被破解修改，客户端数据只能做**辅助参考**，不能作为唯一判定依据
4. 没有安装 FapAch MOD 的玩家不会有数据（`mgr.get()` 返回 null），此时应跳过而非判定
5. 数据有延迟（CPS 每 2 秒上报，移动每 0.5 秒采样/2 秒上报），不能用于实时拦截，只能用于事后分析/标记

---

## 版本信息
- FapAchBridge: v1.1.0
- FapACH MOD: v0.0.1
- 客户端 MOD UUID: ea6986a9-4fde-41be-a718-0cdca2607695 (BP) / 9bb55178-696e-4f8f-8881-52957253f3a0 (RP)
