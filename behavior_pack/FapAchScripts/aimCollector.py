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

上报数据让服务端做交叉验证统计，辅助判定。
"""

import time

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig

_compFactory = clientApi.GetEngineCompFactory()


class AimCollector(object):

    def __init__(self):
        self._levelId = None
        self._cameraComp = None
        self._lastReportTime = 0.0
        self._cooldown = modConfig.AIM_COOLDOWN

    def bind(self, levelId):
        """在 clientSystem 初始化后绑定 levelId 并创建相机组件。"""
        self._levelId = levelId
        if levelId:
            self._cameraComp = _compFactory.CreateCamera(levelId)

    def setCooldown(self, seconds):
        self._cooldown = max(0.05, float(seconds))

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

        report = {
            'timestamp':   round(now * 1000),
            'victimId':    str(victimId),
            'pickType':    pickType,       # Entity / Block / None
            'pickEntityId': str(pickEntityId),
            'match':       'true' if match else 'false',   # boolean 用字符串
            'isCrit':      'true' if args.get('isCrit') else 'false',
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
