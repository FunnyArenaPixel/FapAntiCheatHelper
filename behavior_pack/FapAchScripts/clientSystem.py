# -*- coding: utf-8 -*-
"""
FapACH 客户端主系统

负责：
  1. 初始化采集模块（CPS / 准星 / 移动 / 方块）
  2. 注册引擎事件监听
  3. OnScriptTickClient 定时调度
  4. 接收服务端配置同步（ConfigSync）
  5. FOV 异常监控
  6. 统一封装 NotifyToServer 数据上报
"""

import time

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig
from FapAchScripts.cpsCollector import CpsCollector
from FapAchScripts.aimCollector import AimCollector
from FapAchScripts.moveCollector import MoveCollector
from FapAchScripts.blockCollector import BlockCollector

_MOD_VERSION = '0.0.3'


class FapAchClient(clientApi.GetClientSystemCls()):

    def __init__(self, namespace, systemName):
        super(FapAchClient, self).__init__(namespace, systemName)

        self._playerId = clientApi.GetLocalPlayerId()
        self._levelId = clientApi.GetLevelId()

        # 模块开关
        self._enableCps = modConfig.ENABLE_CPS
        self._enableAim = modConfig.ENABLE_AIM
        self._enableMove = modConfig.ENABLE_MOVE
        self._enableBlock = modConfig.ENABLE_BLOCK

        # 采集器
        self._cps = CpsCollector()
        self._aim = AimCollector()
        self._move = MoveCollector()
        self._block = BlockCollector()

        # 客户端就绪标志
        self._readyNotified = False

        # 输入模式检测
        self._inputMode = None
        self._splitControls = None
        self._inputCheckTick = 0
        self._compPlayerView = clientApi.GetEngineCompFactory().CreatePlayerView(self._playerId)

        # FOV 监控
        self._fovCheckTick = 0
        self._fovCheckTicks = int(modConfig.FOV_CHECK_INTERVAL * 30)
        self._lastFov = 0.0
        self._compCamera = clientApi.GetEngineCompFactory().CreateCamera(self._levelId)

        self._listenEvents()

        print('[FapACH] Client system initialized. playerId=%s levelId=%s' % (
            self._playerId, self._levelId))

    # ==========================================================
    # 事件注册
    # ==========================================================

    def _listenEvents(self):
        ns = clientApi.GetEngineNamespace()
        sys = clientApi.GetEngineSystemName()

        self.ListenForEvent(ns, sys, 'UiInitFinished', self, self._onUiInitFinished)
        self.ListenForEvent(ns, sys, 'OnScriptTickClient', self, self._onTick)

        if self._enableCps:
            self.ListenForEvent(ns, sys, 'LeftClickBeforeClientEvent', self, self._onLeftClick)

        if self._enableAim:
            self.ListenForEvent(ns, sys, 'PlayerAttackEntityEvent', self, self._onAttackEntity)

        if self._enableMove:
            self.ListenForEvent(ns, sys, 'ClientItemTryUseEvent', self, self._onItemTryUse)
            self.ListenForEvent(ns, sys, 'ItemReleaseUsingClientEvent', self, self._onItemReleaseUsing)
            self.ListenForEvent(ns, sys, 'OnCarriedNewItemChangedClientEvent', self, self._onCarriedItemChanged)
            self.ListenForEvent(ns, sys, 'OnLocalPlayerActionClientEvent', self, self._onPlayerAction)

        if self._enableBlock:
            self.ListenForEvent(ns, sys, 'StartDestroyBlockClientEvent', self, self._onStartDestroyBlock)

        self.ListenForEvent(
            modConfig.mod_name, modConfig.server_system_name,
            modConfig.EVENT_CONFIG_SYNC,
            self, self._onConfigSync
        )

    # ==========================================================
    # 引擎事件回调
    # ==========================================================

    def _onUiInitFinished(self, args):
        self._playerId = clientApi.GetLocalPlayerId()
        self._levelId = clientApi.GetLevelId()

        self._compPlayerView = clientApi.GetEngineCompFactory().CreatePlayerView(self._playerId)
        self._compCamera = clientApi.GetEngineCompFactory().CreateCamera(self._levelId)

        # 绑定采集器
        self._aim.bind(self._levelId, self._playerId)
        self._move.bind(self._playerId)
        self._block.bind(self._playerId)

        self._checkInputMode()

        if not self._readyNotified:
            self._readyNotified = True
            self.NotifyToServer(modConfig.EVENT_CLIENT_READY, {
                'playerId': str(self._playerId),
                'version': _MOD_VERSION,
                'modules': {
                    'cps':   'true' if self._enableCps else 'false',
                    'aim':   'true' if self._enableAim else 'false',
                    'move':  'true' if self._enableMove else 'false',
                    'block': 'true' if self._enableBlock else 'false',
                }
            })
            print('[FapACH] Client ready notified to server (v%s)' % _MOD_VERSION)

    def _onTick(self, args):
        # 输入模式检测（每秒一次）
        self._inputCheckTick += 1
        if self._inputCheckTick >= 30:
            self._inputCheckTick = 0
            self._checkInputMode()

        # FOV 监控（每 10 秒）
        self._fovCheckTick += 1
        if self._fovCheckTick >= self._fovCheckTicks:
            self._fovCheckTick = 0
            self._checkFov()

        if self._enableCps:
            self._cps.onTick(self)
        if self._enableMove:
            self._move.onTick(self)
        if self._enableBlock:
            self._block.onTick(self)

    def _onLeftClick(self, args):
        self._cps.recordClick()

    def _onAttackEntity(self, args):
        self._aim.onAttackEntity(self, args)

    def _onItemTryUse(self, args):
        self._move.setUsingItem(True)

    def _onItemReleaseUsing(self, args):
        self._move.setUsingItem(False)

    def _onCarriedItemChanged(self, args):
        self._move.setUsingItem(False)

    def _onPlayerAction(self, args):
        """玩家动作事件 — 记录状态转换（疾跑/潜行/飞行/游泳等）。"""
        actionType = args.get('actionType', -1)
        if actionType >= 0:
            self._move.setLastAction(actionType)

    def _onStartDestroyBlock(self, args):
        """开始挖方块 — 方块破坏时序采集。"""
        self._block.onStartDestroy(self, args)

    # ==========================================================
    # 输入模式检测
    # ==========================================================

    def _checkInputMode(self):
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
    # FOV 监控
    # ==========================================================

    def _checkFov(self):
        """
        定期检查 FOV 值。仅当超出正常范围时上报。

        ⚠️ 误判注意：
          - 部分玩家合法使用较高 FOV（如 90-110）
          - 某些显卡驱动 / 显示设置可能导致 FOV 读数偏差
          - FOV 异常是弱证据，不能单独作为判定依据
          - 仅上报异常值，服务端应结合其他指标综合分析
        """
        if not self._compCamera:
            return
        try:
            fov = self._compCamera.GetFov()
            if fov is None:
                return
            fov = float(fov)
            # 只在超出正常范围或与上次变化超过 20° 时上报
            abnormal = (fov < modConfig.FOV_NORMAL_MIN or fov > modConfig.FOV_NORMAL_MAX)
            bigChange = abs(fov - self._lastFov) > 20.0
            if abnormal or bigChange:
                self._lastFov = fov
                self.sendReport(modConfig.EVENT_MOVE_REPORT, {
                    'fovAlert': round(fov, 1),
                    'timestamp': round(time.time() * 1000),
                    'samples': [],
                    'count': 0,
                })
        except:
            pass

    # ==========================================================
    # 配置同步回调
    # ==========================================================

    def _onConfigSync(self, args):
        try:
            if 'enableCps' in args:
                self._enableCps = (args['enableCps'] == 'true')
            if 'enableAim' in args:
                self._enableAim = (args['enableAim'] == 'true')
            if 'enableMove' in args:
                self._enableMove = (args['enableMove'] == 'true')
            if 'enableBlock' in args:
                self._enableBlock = (args['enableBlock'] == 'true')
            if 'cpsReportInterval' in args:
                self._cps.setReportInterval(args['cpsReportInterval'])
            if 'aimCooldown' in args:
                self._aim.setCooldown(args['aimCooldown'])
            if 'moveSampleInterval' in args:
                self._move.setSampleInterval(args['moveSampleInterval'])
            if 'moveReportInterval' in args:
                self._move.setReportInterval(args['moveReportInterval'])
            if 'blockReportCooldown' in args:
                self._block.setCooldown(args['blockReportCooldown'])
            print('[FapACH] ConfigSync received: %s' % args)
        except Exception as e:
            print('[FapACH] ConfigSync error: %s' % e)

    # ==========================================================
    # 数据上报
    # ==========================================================

    def sendReport(self, eventName, data):
        if not self._playerId or self._playerId == -1:
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
        if self._enableMove:
            self.UnListenForEvent(ns, sys, 'ClientItemTryUseEvent', self, self._onItemTryUse)
            self.UnListenForEvent(ns, sys, 'ItemReleaseUsingClientEvent', self, self._onItemReleaseUsing)
            self.UnListenForEvent(ns, sys, 'OnCarriedNewItemChangedClientEvent', self, self._onCarriedItemChanged)
            self.UnListenForEvent(ns, sys, 'OnLocalPlayerActionClientEvent', self, self._onPlayerAction)
        if self._enableBlock:
            self.UnListenForEvent(ns, sys, 'StartDestroyBlockClientEvent', self, self._onStartDestroyBlock)
        self.UnListenForEvent(
            modConfig.mod_name, modConfig.server_system_name,
            modConfig.EVENT_CONFIG_SYNC,
            self, self._onConfigSync
        )
        print('[FapACH] Client system destroyed')
