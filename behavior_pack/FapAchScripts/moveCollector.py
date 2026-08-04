# -*- coding: utf-8 -*-
"""
移动状态交叉验证采集器

定期采样本地玩家的位置、旋转、运动状态和输入向量，
上报给服务端用于交叉验证。

核心用途（服务端分析）：
  - 位置/速度验证：客户端位置 vs 服务端计算位置是否一致（反飞行/加速）
  - 状态验证：客户端 isSprinting vs 服务端 sprint 状态（反 sprint hack）
  - 输入验证：GetInputVector 是否与实际移动方向匹配（反 no-slowdown）
"""

import time

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig

_compFactory = clientApi.GetEngineCompFactory()

# usingItem 超时自动重置（秒）
# 瞬间使用物品（如扔药水）只触发 ClientItemTryUseEvent 不触发 ItemReleaseUsingClientEvent，
# 会导致 usingItem 卡在 true。超时后自动重置。
# 正常进食 ≈ 1.6s，拉弓最长蓄力 ≈ 3s，留 5s 余量。
_USING_ITEM_TIMEOUT = 5.0


class MoveCollector(object):

    def __init__(self):
        self._playerId = None
        self._compPlayer = None
        self._compPos = None
        self._compRot = None
        self._compMotion = None

        # 采样参数
        self._sampleTicks = int(modConfig.MOVE_SAMPLE_INTERVAL * 30)
        self._reportTicks = int(modConfig.MOVE_REPORT_INTERVAL * 30)
        self._maxBuffer = modConfig.MOVE_MAX_BUFFER

        # tick 计数
        self._sampleCount = 0
        self._reportCount = 0

        # 物品使用状态追踪
        # ClientItemTryUseEvent → True，ItemReleaseUsingClientEvent → False
        self._usingItem = False
        self._usingItemStartTime = 0.0

        # 采样缓冲区
        self._buffer = []

    def bind(self, playerId):
        """在 clientSystem 初始化后绑定 playerId 并创建组件。"""
        self._playerId = playerId
        if playerId and playerId != -1:
            self._compPlayer = _compFactory.CreatePlayer(playerId)
            self._compPos = _compFactory.CreatePos(playerId)
            self._compRot = _compFactory.CreateRot(playerId)
            self._compMotion = _compFactory.CreateActorMotion(playerId)

    def setSampleInterval(self, seconds):
        self._sampleTicks = max(1, int(float(seconds) * 30))

    def setReportInterval(self, seconds):
        self._reportTicks = max(1, int(float(seconds) * 30))

    def setUsingItem(self, using):
        """由 clientSystem 在物品使用事件中调用。"""
        self._usingItem = using
        if using:
            self._usingItemStartTime = time.time()

    # ----------------------------------------------------------
    # 公开方法
    # ----------------------------------------------------------

    def onTick(self, client):
        """每脚本刻调用（每秒 30 次）。"""
        self._sampleCount += 1
        self._reportCount += 1

        # 采样
        if self._sampleCount >= self._sampleTicks:
            self._sampleCount = 0
            self._doSample()

        # 上报
        if self._reportCount >= self._reportTicks:
            self._reportCount = 0
            self._doReport(client)

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _doSample(self):
        """采样一次玩家状态并存入缓冲区。"""
        if not self._compPlayer or not self._compPos:
            return

        try:
            pos = self._compPos.GetPos()
            rot = self._compRot.GetRot() if self._compRot else (0.0, 0.0)
            inputVec = self._compMotion.GetInputVector() if self._compMotion else (0.0, 0.0)

            isSprinting = self._compPlayer.isSprinting()
            isSneaking = self._compPlayer.isSneaking()
            isInWater = self._compPlayer.isInWater()
            isOnLadder = self._compPlayer.IsOnLadder()
            isGliding = self._compPlayer.isGliding()

            # 物品使用状态（含超时自动重置）
            if self._usingItem and (time.time() - self._usingItemStartTime > _USING_ITEM_TIMEOUT):
                self._usingItem = False

            sample = {
                't':           round(time.time() * 1000),  # 毫秒时间戳
                'pos':         [round(pos[0], 3), round(pos[1], 3), round(pos[2], 3)],
                'rot':         [round(rot[0], 1), round(rot[1], 1)],
                'inputVec':    [round(inputVec[0], 3), round(inputVec[1], 3)],
                # boolean 用字符串传输（PyRpc 序列化安全）
                'sprint':      'true' if isSprinting else 'false',
                'sneak':       'true' if isSneaking else 'false',
                'inWater':     'true' if isInWater else 'false',
                'onLadder':    'true' if isOnLadder else 'false',
                'gliding':     'true' if isGliding else 'false',
                'usingItem':   'true' if self._usingItem else 'false',
            }
            self._buffer.append(sample)
            # 限制缓冲区大小
            if len(self._buffer) > self._maxBuffer:
                self._buffer = self._buffer[-self._maxBuffer:]
        except Exception as e:
            print('[FapACH] MoveSample error: %s' % e)

    def _doReport(self, client):
        """聚合缓冲区数据并上报。"""
        if not self._buffer:
            return
        report = {
            'samples': self._buffer[:],   # 拷贝
            'count':   len(self._buffer),
        }
        self._buffer = []
        client.sendReport(modConfig.EVENT_MOVE_REPORT, report)
