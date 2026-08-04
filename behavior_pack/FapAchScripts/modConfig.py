# -*- coding: utf-8 -*-
# ============================================================
# FapACH — FAPIXEL AntiCheat Helper 配置常量
# ============================================================

# MOD 注册信息
mod_name = 'FapAch'
client_system_name = 'FapAchClient'
client_class_path = 'FapAchScripts.clientSystem.FapAchClient'
# 虚拟服务端系统名 — Nukkit-MOT PyRpc 向客户端发事件时使用此名称
server_system_name = 'FapAchServer'

# ============================================================
# PyRpc 事件名称
# ============================================================

# 客户端 → 服务端
EVENT_CPS_REPORT   = 'FapAchCpsReport'    # CPS 模式分析上报
EVENT_AIM_REPORT   = 'FapAchAimReport'    # 准星目标上报
EVENT_MOVE_REPORT  = 'FapAchMoveReport'   # 移动状态采样上报
EVENT_BLOCK_REPORT = 'FapAchBlockReport'  # 方块破坏时序上报
EVENT_CLIENT_READY = 'FapAchClientReady'  # 客户端就绪通知

# 服务端 → 客户端
EVENT_CONFIG_SYNC  = 'FapAchConfigSync'   # 配置同步

# ============================================================
# 采集参数（默认值，可被服务端 ConfigSync 覆盖）
# ============================================================

# CPS 模块
CPS_REPORT_INTERVAL = 2.0      # CPS 上报间隔（秒）
CPS_WINDOW_SECONDS  = 3.0      # CPS 计算窗口（秒，保留最近N秒的点击）

# 准星模块
AIM_COOLDOWN = 0.15            # 准星上报冷却（秒，防止刷屏）

# 移动模块
MOVE_SAMPLE_INTERVAL = 0.5     # 移动采样间隔（秒）
MOVE_REPORT_INTERVAL = 2.0     # 移动上报间隔（秒）
MOVE_MAX_BUFFER = 8            # 移动采样缓冲区最大条数

# 方块模块
BLOCK_REPORT_COOLDOWN = 0.5    # 方块破坏上报冷却（秒）

# FOV 监控
FOV_CHECK_INTERVAL = 10.0      # FOV 检查间隔（秒）
FOV_NORMAL_MIN = 30.0          # FOV 正常下限（度）
FOV_NORMAL_MAX = 110.0         # FOV 正常上限（度）

# ============================================================
# 模块开关（默认值，可被服务端 ConfigSync 覆盖）
# ============================================================

ENABLE_CPS   = True
ENABLE_AIM   = True
ENABLE_MOVE  = True
ENABLE_BLOCK = True
