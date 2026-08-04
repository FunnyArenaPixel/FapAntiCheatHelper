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

### 数据字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `data.aimTotalAttacks` | int | 累计攻击次数 |
| `data.aimMismatchedAttacks` | int | 准星不匹配次数 |
| `data.getAimMismatchRate()` | double | 不匹配率（0.0~1.0） |
| `data.aimLastMatch` | boolean | 最近一次攻击是否匹配 |

### 建议判定逻辑
```java
// KillAura/Reach 检测
if (data.aimTotalAttacks > 10) {
    double rate = data.getAimMismatchRate();
    if (rate > 0.3) {
        // 超过 30% 的攻击没有瞄准目标 → 高概率 KillAura
        flag(player, "KillAura", rate, data.aimTotalAttacks);
    }
}
// 正常玩家几乎所有攻击都瞄准了目标（不匹配率 < 5%）
// KillAura 攻击不在准星上的实体（不匹配率 > 30%）
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
| `data.moveInputX/Y` | double | 移动轮盘输入向量 |

### 建议判定逻辑
```java
// Sprint Hack 检测（服务端 sprint 状态 vs 客户端 sprint 状态）
boolean serverSprinting = player.isSprinting();
if (data.moveSprinting != serverSprinting) {
    // 状态不一致 → 可能使用了 sprint hack
    flag(player, "SprintHack", serverSprinting, data.moveSprinting);
}

// NoSlowDown 检测（输入向量 vs 实际速度）
// 正常潜行/使用物品时速度会降低
// 如果输入向量很大但速度也很大 → 可能 no-slowdown
```

### 预留位置
- VenusAntiCheat 的 Moving 检测模块中
- 在移动事件回调里查询客户端报告的状态进行交叉验证

---

## ⚠️ 重要约束

1. **VenusAntiCheat 插件本体完全不修改**
2. 以上所有代码均为 VenusAntiCheat 在自己的检测逻辑中**外部查询** FapAchBridge 数据
3. 客户端 MOD 代码可被破解修改，客户端数据只能做**辅助参考**，不能作为唯一判定依据
4. 没有安装 FapAch MOD 的玩家不会有数据（`mgr.get()` 返回 null），此时应跳过而非判定
5. 数据有延迟（CPS 每 2 秒上报，移动每 0.5 秒采样/2 秒上报），不能用于实时拦截，只能用于事后分析/标记

---

## 版本信息
- FapAchBridge: v1.0.0
- FapACH MOD: v0.0.1
- 客户端 MOD UUID: ea6986a9-4fde-41be-a718-0cdca2607695 (BP) / 9bb55178-696e-4f8f-8881-52957253f3a0 (RP)
