# -*- coding: utf-8 -*-
"""
FapACH 客户端主系统

负责：
  1. 初始化三个采集模块（CPS / 准星 / 移动）
  2. 注册引擎事件监听
  3. OnScriptTickClient 定时调度
  4. 接收服务端配置同步（ConfigSync）
  5. 统一封装 NotifyToServer 数据上报
"""

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig
from FapAchScripts.cpsCollector import CpsCollector
from FapAchScripts.aimCollector import AimCollector
from FapAchScripts.moveCollector import MoveCollector


class FapAchClient(clientApi.GetClientSystemCls()):

    def __init__(self, namespace, systemName):
        super(FapAchClient, self).__init__(namespace, systemName)

        # 引擎 ID
        self._playerId = clientApi.GetLocalPlayerId()
        self._levelId = clientApi.GetLevelId()

        # 模块开关
        self._enableCps = modConfig.ENABLE_CPS
        self._enableAim = modConfig.ENABLE_AIM
        self._enableMove = modConfig.ENABLE_MOVE

        # 采集器
        self._cps = CpsCollector()
        self._aim = AimCollector()
        self._move = MoveCollector()

        # 客户端就绪标志
        self._readyNotified = False

        # 输入模式检测（用于准星检测的触屏兼容性）
        # InputMode: 0=Mouse, 1=Touch, 2=GamePad, None=未知
        self._inputMode = None
        self._splitControls = None
        self._inputCheckTick = 0
        # __init__ 时 GetLocalPlayerId() 可能返回 -1，OnUiInitFinished 中重新创建
        self._compPlayerView = clientApi.GetEngineCompFactory().CreatePlayerView(self._playerId)

        self._listenEvents()

        print('[FapACH] Client system initialized. playerId=%s levelId=%s' % (
            self._playerId, self._levelId))

    # ==========================================================
    # 事件注册
    # ==========================================================

    def _listenEvents(self):
        # 引擎事件
        ns = clientApi.GetEngineNamespace()
        sys = clientApi.GetEngineSystemName()

        # UI 初始化完成（获取有效 playerId）
        self.ListenForEvent(ns, sys, 'UiInitFinished', self, self._onUiInitFinished)

        # 脚本刻（定时调度）
        self.ListenForEvent(ns, sys, 'OnScriptTickClient', self, self._onTick)

        # CPS — 左键点击
        if self._enableCps:
            self.ListenForEvent(ns, sys, 'LeftClickBeforeClientEvent', self, self._onLeftClick)

        # 准星 — 攻击实体
        if self._enableAim:
            self.ListenForEvent(ns, sys, 'PlayerAttackEntityEvent', self, self._onAttackEntity)

        # 配置同步（服务端 → 客户端）
        self.ListenForEvent(
            modConfig.mod_name, modConfig.server_system_name,
            modConfig.EVENT_CONFIG_SYNC,
            self, self._onConfigSync
        )

    # ==========================================================
    # 引擎事件回调
    # ==========================================================

    def _onUiInitFinished(self, args):
        """UI 初始化完成，获取有效 playerId 并绑定采集器。"""
        self._playerId = clientApi.GetLocalPlayerId()
        self._levelId = clientApi.GetLevelId()

        # 重新创建 PlayerView 组件（此时 playerId 有效）
        self._compPlayerView = clientApi.GetEngineCompFactory().CreatePlayerView(self._playerId)

        # 绑定采集器
        self._aim.bind(self._levelId)
        self._move.bind(self._playerId)

        # 立即检测一次输入模式
        self._checkInputMode()

        # 通知服务端客户端就绪
        if not self._readyNotified:
            self._readyNotified = True
            self.NotifyToServer(modConfig.EVENT_CLIENT_READY, {
                'playerId': str(self._playerId),
                'version': '0.0.1',
                'modules': {
                    'cps':  'true' if self._enableCps else 'false',
                    'aim':  'true' if self._enableAim else 'false',
                    'move': 'true' if self._enableMove else 'false',
                }
            })
            print('[FapACH] Client ready notified to server')

    def _onTick(self, args):
        """脚本刻回调（每秒 30 次）。"""
        # 输入模式检测（每秒一次 = 每 30 tick）
        self._inputCheckTick += 1
        if self._inputCheckTick >= 30:
            self._inputCheckTick = 0
            self._checkInputMode()

        if self._enableCps:
            self._cps.onTick(self)
        if self._enableMove:
            self._move.onTick(self)

    def _onLeftClick(self, args):
        """左键点击事件 — CPS 采集。"""
        self._cps.recordClick()

    def _onAttackEntity(self, args):
        """攻击实体事件 — 准星目标采集。"""
        self._aim.onAttackEntity(self, args)

    # ==========================================================
    # 输入模式检测（准星检测的触屏兼容性）
    # ==========================================================

    def _checkInputMode(self):
        """
        检测当前输入模式和分离控制开关。
        触屏默认模式（非分离控制）下，玩家直接点击屏幕上的实体来攻击，
        屏幕中心准星不一定指向被攻击的实体，准星检测不适用。
        """
        if not self._compPlayerView:
            return
        try:
            mcEnum = clientApi.GetMinecraftEnum()
            newMode = self._compPlayerView.GetToggleOption(mcEnum.OptionId.INPUT_MODE)
            newSplit = self._compPlayerView.GetToggleOption(mcEnum.OptionId.SPLIT_CONTROLS)
            if newMode != self._inputMode or newSplit != self._splitControls:
                self._inputMode = newMode
                self._splitControls = newSplit
                self._aim.updateInputContext(newMode, newSplit)
                print('[FapACH] Input: mode=%s splitControls=%s' % (newMode, newSplit))
        except Exception as e:
            print('[FapACH] _checkInputMode error: %s' % e)

    # ==========================================================
    # 配置同步回调
    # ==========================================================

    def _onConfigSync(self, args):
        """
        接收服务端配置同步。

        可选字段：
            enableCps / enableAim / enableMove — 模块开关 ('true'/'false')
            cpsReportInterval   — CPS 上报间隔（秒）
            aimCooldown         — 准星上报冷却（秒）
            moveSampleInterval  — 移动采样间隔（秒）
            moveReportInterval  — 移动上报间隔（秒）
        """
        try:
            if 'enableCps' in args:
                self._enableCps = (args['enableCps'] == 'true')
            if 'enableAim' in args:
                self._enableAim = (args['enableAim'] == 'true')
            if 'enableMove' in args:
                self._enableMove = (args['enableMove'] == 'true')
            if 'cpsReportInterval' in args:
                self._cps.setReportInterval(args['cpsReportInterval'])
            if 'aimCooldown' in args:
                self._aim.setCooldown(args['aimCooldown'])
            if 'moveSampleInterval' in args:
                self._move.setSampleInterval(args['moveSampleInterval'])
            if 'moveReportInterval' in args:
                self._move.setReportInterval(args['moveReportInterval'])
            print('[FapACH] ConfigSync received: %s' % args)
        except Exception as e:
            print('[FapACH] ConfigSync error: %s' % e)

    # ==========================================================
    # 数据上报（各采集器调用此方法）
    # ==========================================================

    def sendReport(self, eventName, data):
        """
        统一封装 NotifyToServer，附加 playerId。
        """
        if not self._playerId or self._playerId == -1:
            # playerId 尚未就绪，跳过
            return
        data['playerId'] = str(self._playerId)
        try:
            self.NotifyToServer(eventName, data)
        except Exception as e:
            print('[FapACH] sendReport(%s) error: %s' % (eventName, e))

    # ==========================================================
    # 析构
    # ==========================================================

    def Destroy(self):
        ns = clientApi.GetEngineNamespace()
        sys = clientApi.GetEngineSystemName()
        self.UnListenForEvent(ns, sys, 'UiInitFinished', self, self._onUiInitFinished)
        self.UnListenForEvent(ns, sys, 'OnScriptTickClient', self, self._onTick)
        if self._enableCps:
            self.UnListenForEvent(ns, sys, 'LeftClickBeforeClientEvent', self, self._onLeftClick)
        if self._enableAim:
            self.UnListenForEvent(ns, sys, 'PlayerAttackEntityEvent', self, self._onAttackEntity)
        self.UnListenForEvent(
            modConfig.mod_name, modConfig.server_system_name,
            modConfig.EVENT_CONFIG_SYNC,
            self, self._onConfigSync
        )
        print('[FapACH] Client system destroyed')
