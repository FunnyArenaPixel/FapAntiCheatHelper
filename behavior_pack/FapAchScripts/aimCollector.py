# -*- coding: utf-8 -*-
"""
准星目标上报采集器

监听本地玩家攻击实体事件（PlayerAttackEntityEvent 客户端版），
在攻击发生的瞬间调用 PickFacing() 获取准星实际指向的目标，
对比攻击目标 victimId 与准星指向实体。

增强字段（v0.0.3）：
  - 摄像机朝向（camPitch/camYaw）：攻击瞬间的摄像机角度，
    用于 Aimbot/Snap-Aim 分析。正常玩家攻击时准星角度应朝向目标方向；
    Aimbot 可能出现身体朝向与摄像机朝向不一致、或极短时间内大角度跳变。
  - 视角模式（perspective）：第一/第三人称，影响准星检测的判定逻辑。

⚠️ 触屏兼容性：
  触屏默认模式（未开启分离控制）下，准星检测不适用，标记 aimCheckApplicable=false。
  摄像机数据在所有模式下均有效，但触屏的摄像机控制方式不同（触摸旋转 vs 鼠标），
  服务端分析时需结合 inputMode 综合判断。

⚠️ 误判注意：
  - 摄像机角度本身不能单独作为判定依据，只是辅助参考
  - 第三人称模式下摄像机角度与第一人称有差异，需分开统计
  - 合法的快速转身（180°转身攻击）不应误判为 Snap-Aim
"""

import time

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig

_compFactory = clientApi.GetEngineCompFactory()

_TOUCH = 1  # InputMode.Touch


class AimCollector(object):

    def __init__(self):
        self._levelId = None
        self._playerId = None
        self._cameraComp = None
        self._playerViewComp = None
        self._lastReportTime = 0.0
        self._cooldown = modConfig.AIM_COOLDOWN
        self._inputMode = None
        self._splitControls = None

    def bind(self, levelId, playerId):
        """在 clientSystem 初始化后绑定。"""
        self._levelId = levelId
        self._playerId = playerId
        if levelId:
            self._cameraComp = _compFactory.CreateCamera(levelId)
        if playerId and playerId != -1:
            self._playerViewComp = _compFactory.CreatePlayerView(playerId)

    def setCooldown(self, seconds):
        self._cooldown = max(0.05, float(seconds))

    def updateInputContext(self, inputMode, splitControls):
        self._inputMode = inputMode
        self._splitControls = splitControls

    # ----------------------------------------------------------

    def onAttackEntity(self, client, args):
        now = time.time()
        if now - self._lastReportTime < self._cooldown:
            return
        self._lastReportTime = now

        victimId = args.get('victimId', '')

        # 获取准星指向
        pickData = {'type': 'None'}
        if self._cameraComp:
            try:
                result = self._cameraComp.PickFacing()
                if result:
                    pickData = result
            except:
                pass

        pickType = pickData.get('type', 'None')
        pickEntityId = pickData.get('entityId', '')
        match = (pickType == 'Entity' and pickEntityId == victimId)

        # 判断准星检测是否适用于当前输入模式
        aimCheckApplicable = True
        if self._inputMode == _TOUCH and not self._splitControls:
            aimCheckApplicable = False

        # 摄像机朝向（攻击瞬间）
        camPitch = 0.0
        camYaw = 0.0
        if self._cameraComp:
            try:
                camRot = self._cameraComp.GetCameraRotation()
                if camRot and len(camRot) >= 2:
                    camPitch = round(camRot[0], 1)
                    camYaw = round(camRot[1], 1)
            except:
                pass

        # 视角模式（0=第一人称, 1=第三人称, 2=前视第三人称）
        perspective = -1
        if self._playerViewComp:
            try:
                perspective = self._playerViewComp.GetPerspective()
            except:
                pass

        report = {
            'timestamp':  round(now * 1000),
            'victimId':   victimId,
            'pickType':   pickType,
            'pickEntityId': str(pickEntityId),
            'match':      'true' if match else 'false',
            'inputMode':  self._inputMode if self._inputMode is not None else -1,
            'splitControls': 'true' if self._splitControls else 'false',
            'aimCheckApplicable': 'true' if aimCheckApplicable else 'false',
            'camPitch':   camPitch,
            'camYaw':     camYaw,
            'perspective': perspective,
        }
        client.sendReport(modConfig.EVENT_AIM_REPORT, report)
