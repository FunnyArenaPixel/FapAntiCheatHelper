# -*- coding: utf-8 -*-
"""
方块破坏时序采集器

监听 StartDestroyBlockClientEvent，记录玩家开始挖掘方块的时间戳和方块信息。
服务端结合自身的破坏完成事件，可检测 FastBreak（加速破坏）和 Nuker（范围破坏）。

⚠️ 创造模式下此事件不触发（方块秒破）。

⚠️ 误判注意：
  - 急迫 II + 效率 V 镐子可以极快地破坏方块，这是合法的
  - 服务端应使用 GetPlayerDestroyTotalTime() 计算预期破坏时间作为基线
  - 仅当实际破坏速度显著快于预期时才标记可疑
  - 网络延迟可能导致时间戳偏差，不应用于精确判定
"""

import time

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig

_compFactory = clientApi.GetEngineCompFactory()


class BlockCollector(object):

    def __init__(self):
        self._playerId = None
        self._lastReportTime = 0.0
        self._cooldown = modConfig.BLOCK_REPORT_COOLDOWN
        # 最近破坏开始记录（供上报）
        self._pendingStarts = []

    def bind(self, playerId):
        self._playerId = playerId

    def setCooldown(self, seconds):
        self._cooldown = max(0.1, float(seconds))

    def onStartDestroy(self, client, args):
        """StartDestroyBlockClientEvent 回调。

        args:
            pos:        (x, y, z) 方块坐标
            blockName:  str       方块标识符
            auxValue:   int       附加值
            face:       int       被敲击面
        """
        now = time.time()
        pos = args.get('pos', (0, 0, 0))
        blockName = args.get('blockName', '')
        face = args.get('face', 0)

        self._pendingStarts.append({
            't':         round(now * 1000),
            'pos':       [int(pos[0]), int(pos[1]), int(pos[2])],
            'blockName': blockName,
            'face':      face,
        })

        # 冷却控制：攒一批后上报
        if now - self._lastReportTime >= self._cooldown and self._pendingStarts:
            self._doReport(client)

    def onTick(self, client):
        """定期上报积攒的破坏记录。"""
        if not self._pendingStarts:
            return
        now = time.time()
        if now - self._lastReportTime >= 1.0:
            self._doReport(client)

    def _doReport(self, client):
        if not self._pendingStarts:
            return
        self._lastReportTime = time.time()
        report = {
            'starts':    self._pendingStarts[:],
            'count':     len(self._pendingStarts),
            'timestamp': round(time.time() * 1000),
        }
        self._pendingStarts = []
        client.sendReport(modConfig.EVENT_BLOCK_REPORT, report)
