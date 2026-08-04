# -*- coding: utf-8 -*-
"""
CPS 模式分析采集器

监听客户端攻击键按下事件，记录精确的时间戳，
计算 CPS 值并分析点击模式（间隔方差、规则性指标）。

服务端可利用以下指标识别自动连击器/宏：
  - maxCps:     窗口内最大 CPS
  - avgCps:     窗口内平均 CPS
  - intervalStd: 点击间隔标准差（毫秒），越低越像机器人
  - intervalMin: 最短间隔（毫秒）
"""

import time

from FapAchScripts import modConfig


class CpsCollector(object):

    def __init__(self):
        # 点击时间戳列表（unix 秒）
        self._clicks = []
        # 上报间隔（秒），可被服务端 ConfigSync 覆盖
        self._reportInterval = modConfig.CPS_REPORT_INTERVAL
        # CPS 计算窗口（秒）
        self._windowSeconds = modConfig.CPS_WINDOW_SECONDS
        # tick 计数
        self._tickCount = 0
        # 上报间隔（tick），30 tick = 1 秒
        self._reportTicks = int(self._reportInterval * 30)

    # ----------------------------------------------------------
    # 公开方法
    # ----------------------------------------------------------

    def setReportInterval(self, seconds):
        self._reportInterval = max(1.0, float(seconds))
        self._reportTicks = int(self._reportInterval * 30)

    def recordClick(self):
        """记录一次点击（由 clientSystem 在 LeftClickBeforeClientEvent 中调用）。"""
        self._clicks.append(time.time())

    def onTick(self, client):
        """
        每脚本刻调用（每秒 30 次）。
        每到上报间隔时聚合数据并调用 client.sendReport。
        """
        self._tickCount += 1
        if self._tickCount >= self._reportTicks:
            self._tickCount = 0
            report = self._buildReport()
            if report:
                client.sendReport(modConfig.EVENT_CPS_REPORT, report)

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _buildReport(self):
        """构建 CPS 上报数据。"""
        now = time.time()
        cutoff = now - self._windowSeconds
        # 只保留窗口内的点击
        self._clicks = [t for t in self._clicks if t >= cutoff]
        recent = self._clicks

        if not recent:
            # 没有点击也要上报（表示玩家当前没有点击）
            return None

        clickCount = len(recent)
        duration = max(0.001, now - cutoff)
        avgCps = round(clickCount / duration, 1)

        # 计算间隔（毫秒）
        intervals = []
        for i in range(1, len(recent)):
            dt = (recent[i] - recent[i - 1]) * 1000.0
            intervals.append(round(dt, 1))

        intervalMin = min(intervals) if intervals else 0.0
        intervalMax = max(intervals) if intervals else 0.0

        # 标准差（衡量规律性）
        intervalStd = 0.0
        if len(intervals) > 1:
            mean = sum(intervals) / len(intervals)
            variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
            intervalStd = round(variance ** 0.5, 1)

        # 短窗口峰值 CPS（最近 1 秒）
        oneSecondCutoff = now - 1.0
        recentOneSec = [t for t in recent if t >= oneSecondCutoff]
        maxCps = len(recentOneSec)

        return {
            'timestamp':   round(now * 1000),   # 毫秒时间戳
            'clickCount':  clickCount,
            'avgCps':      avgCps,
            'maxCps':      maxCps,
            'intervalMin': intervalMin,
            'intervalMax': intervalMax,
            'intervalStd': intervalStd,
            'windowSec':   self._windowSeconds,
        }
