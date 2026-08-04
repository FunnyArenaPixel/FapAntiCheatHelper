# -*- coding: utf-8 -*-
"""
准星目标上报采集器

监听本地玩家攻击实体事件（PlayerAttackEntityEvent 客户端版），
在攻击发生的瞬间调用 PickFacing() 获取准星实际指向的目标，
对比攻击目标 victimId 与准星指向实体。

核心检测逻辑：
  正常玩家：准星必须瞄准目标才能攻击 → victimId == pickEntityId
  KillAura/Reach：攻击了不在准星上的实体   → victimId != pickEntityId
                  或准星指向方块/空         → pickType != 'Entity'

⚠️ 触屏兼容性：
  触屏默认模式（未开启分离控制）下，玩家直接点击屏幕上的实体来攻击，
  屏幕中心准星可能完全不指向被攻击的实体。
  这种模式下 victimId != pickEntityId 是正常的，不是 KillAura。
  → 上报 aimCheckApplicable='false'，服务端据此跳过准星不匹配判定。

  触屏 + 分离控制：用摇杆控制准星方向，攻击准星指向的目标 → 准星检测有效。
  键鼠 / 手柄：准星固定在屏幕中心 → 准星检测有效。
"""

import time

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig

_compFactory = clientApi.GetEngineCompFactory()

# InputMode 枚举值（mod.common.minecraftEnum.InputMode）
_TOUCH = 1  # Touch


class AimCollector(object):

    def __init__(self):
        self._levelId = None
        self._cameraComp = None
        self._lastReportTime = 0.0
        self._cooldown = modConfig.AIM_COOLDOWN
        # 输入模式上下文（由 clientSystem 推送）
        # inputMode: None / 0(Mouse) / 1(Touch) / 2(GamePad)
        self._inputMode = None
        self._splitControls = None

    def bind(self, levelId):
        """在 clientSystem 初始化后绑定 levelId 并创建相机组件。"""
        self._levelId = levelId
        if levelId:
            self._cameraComp = _compFactory.CreateCamera(levelId)

    def setCooldown(self, seconds):
        self._cooldown = max(0.05, float(seconds))

    def updateInputContext(self, inputMode, splitControls):
        """接收 clientSystem 推送的输入模式和分离控制状态。"""
        self._inputMode = inputMode
        self._splitControls = splitControls

    # ----------------------------------------------------------
    # 公开方法
    # ----------------------------------------------------------

    def onAttackEntity(self, client, args):
        """
        PlayerAttackEntityEvent 客户端回调。

        args:
            playerId: str  — 攻击者（本地玩家）
            victimId: str  — 被攻击实体
            damage:   float — 伤害值（只读）
            isCrit:   bool — 是否暴击
        """
        now = time.time()
        # 冷却限制，防止高频攻击刷屏
        if now - self._lastReportTime < self._cooldown:
            return
        self._lastReportTime = now

        victimId = args.get('victimId', '')

        # 获取准星指向
        pickData = self._getPickFacing()

        pickType = pickData.get('type', 'None') if pickData else 'None'
        pickEntityId = pickData.get('entityId', '') if pickData else ''

        # 判定准星是否瞄准了被攻击的实体
        match = (pickType == 'Entity' and pickEntityId == victimId)

        # 判断准星检测是否适用于当前输入模式
        # 触屏默认模式（非分离控制）→ 不适用
        isTouch = (self._inputMode == _TOUCH)
        splitOn = (self._splitControls is True)
        aimCheckApplicable = not (isTouch and not splitOn)

        report = {
            'timestamp':        round(now * 1000),
            'victimId':         str(victimId),
            'pickType':         pickType,       # Entity / Block / None
            'pickEntityId':     str(pickEntityId),
            'match':            'true' if match else 'false',
            'isCrit':           'true' if args.get('isCrit') else 'false',
            'inputMode':        str(self._inputMode) if self._inputMode is not None else '-1',
            'splitControls':    'true' if self._splitControls else 'false',
            'aimCheckApplicable': 'true' if aimCheckApplicable else 'false',
        }

        client.sendReport(modConfig.EVENT_AIM_REPORT, report)

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _getPickFacing(self):
        """安全调用 PickFacing()。"""
        if not self._cameraComp:
            return None
        try:
            return self._cameraComp.PickFacing()
        except Exception as e:
            print('[FapACH] PickFacing error: %s' % e)
            return None
