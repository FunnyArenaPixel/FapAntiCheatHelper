# -*- coding: utf-8 -*-
"""
移动状态交叉验证采集器

定期采样本地玩家的位置、旋转、运动状态和输入向量，
上报给服务端用于交叉验证。

核心用途（服务端分析）：
  - 位置/速度验证：客户端位置 vs 服务端计算位置是否一致（反飞行/加速）
  - 状态验证：客户端 isSprinting vs 服务端 sprint 状态（反 sprint hack）
  - 输入验证：GetInputVector 是否与实际移动方向匹配（反 no-slowdown）
  - 效果/属性：当前状态效果列表 + 速度属性，降低 Speed/NoSlowDown 误判
  - 落地状态：onGround 交叉验证（反 Fly）
  - 手持物品：辅助判断减速场景（拉弓/进食/举盾）
"""

import time

import mod.client.extraClientApi as clientApi

from FapAchScripts import modConfig

_compFactory = clientApi.GetEngineCompFactory()

# usingItem 超时自动重置（秒）
_USING_ITEM_TIMEOUT = 5.0

# AttrType.SPEED 常量（避免每帧查枚举）
_ATTR_SPEED = 1


class MoveCollector(object):

    def __init__(self):
        self._playerId = None
        self._compPlayer = None
        self._compPos = None
        self._compRot = None
        self._compMotion = None
        self._compEffect = None
        self._compAttr = None
        self._compItem = None

        # 采样参数
        self._sampleTicks = int(modConfig.MOVE_SAMPLE_INTERVAL * 30)
        self._reportTicks = int(modConfig.MOVE_REPORT_INTERVAL * 30)
        self._maxBuffer = modConfig.MOVE_MAX_BUFFER

        # tick 计数
        self._sampleCount = 0
        self._reportCount = 0

        # 物品使用状态追踪
        self._usingItem = False
        self._usingItemStartTime = 0.0

        # 上次动作事件（由 clientSystem 推送）
        # actionType: PlayerActionType 枚举值
        self._lastAction = -1
        self._lastActionTime = 0.0

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
            self._compEffect = _compFactory.CreateEffect(playerId)
            self._compAttr = _compFactory.CreateAttr(playerId)
            self._compItem = _compFactory.CreateItem(playerId)

    def setSampleInterval(self, seconds):
        self._sampleTicks = max(1, int(float(seconds) * 30))

    def setReportInterval(self, seconds):
        self._reportTicks = max(1, int(float(seconds) * 30))

    def setUsingItem(self, using):
        self._usingItem = using
        if using:
            self._usingItemStartTime = time.time()

    def setLastAction(self, actionType):
        """由 clientSystem 在 OnLocalPlayerActionClientEvent 中调用。"""
        self._lastAction = actionType
        self._lastActionTime = time.time()

    # ----------------------------------------------------------
    # 公开方法
    # ----------------------------------------------------------

    def onTick(self, client):
        self._sampleCount += 1
        self._reportCount += 1

        if self._sampleCount >= self._sampleTicks:
            self._sampleCount = 0
            self._doSample()

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

            # ---- 增强字段 ----

            # 状态效果列表（扁平化为 "name:amp|name:amp" 格式，PyRpc 安全）
            effectsStr = self._getEffectsStr()

            # 速度属性（引擎最终值，含 buff/附魔修正）
            speedAttr = self._getSpeedAttr()

            # 是否在地面
            onGround = self._getOnGround()

            # 手持物品标识 + 快捷栏槽位
            carriedItem, slotId = self._getCarriedItemInfo()

            sample = {
                't':           round(time.time() * 1000),
                'pos':         [round(pos[0], 3), round(pos[1], 3), round(pos[2], 3)],
                'rot':         [round(rot[0], 1), round(rot[1], 1)],
                'inputVec':    [round(inputVec[0], 3), round(inputVec[1], 3)],
                'sprint':      'true' if isSprinting else 'false',
                'sneak':       'true' if isSneaking else 'false',
                'inWater':     'true' if isInWater else 'false',
                'onLadder':    'true' if isOnLadder else 'false',
                'gliding':     'true' if isGliding else 'false',
                'usingItem':   'true' if self._usingItem else 'false',
                'effects':     effectsStr,
                'speedAttr':   round(speedAttr, 4),
                'onGround':    'true' if onGround else 'false',
                'carriedItem': carriedItem,
                'slot':        slotId if slotId is not None else -1,
                'lastAction':  self._lastAction if self._lastAction >= 0 else -1,
            }
            self._buffer.append(sample)
            if len(self._buffer) > self._maxBuffer:
                self._buffer = self._buffer[-self._maxBuffer:]
        except Exception as e:
            print('[FapACH] MoveSample error: %s' % e)

    def _getEffectsStr(self):
        """获取当前状态效果，扁平化为字符串。"""
        if not self._compEffect:
            return ''
        try:
            effs = self._compEffect.GetAllEffects()
            if not effs:
                return ''
            parts = []
            for e in effs:
                name = e.get('effectName', '')
                amp = e.get('amplifier', 0)
                if name:
                    parts.append('%s:%d' % (name, amp))
            return '|'.join(parts)
        except:
            return ''

    def _getSpeedAttr(self):
        """获取引擎移速属性值。"""
        if not self._compAttr:
            return 0.0
        try:
            val = self._compAttr.GetAttrValue(_ATTR_SPEED)
            if val is None or val < 0:
                return 0.0
            return float(val)
        except:
            return 0.0

    def _getOnGround(self):
        """获取客户端在地面状态。"""
        if not self._compAttr:
            return True
        try:
            return self._compAttr.isEntityOnGround()
        except:
            return True

    def _getCarriedItemInfo(self):
        """获取手持物品标识和快捷栏槽位。"""
        if not self._compItem:
            return '', -1
        itemStr = ''
        slot = -1
        try:
            itemDict = self._compItem.GetCarriedItem()
            if itemDict:
                itemStr = itemDict.get('newItemName', '') or itemDict.get('itemName', '')
        except:
            pass
        try:
            slot = self._compItem.GetSlotId()
        except:
            pass
        return itemStr, slot

    def _doReport(self, client):
        """聚合缓冲区数据并上报。"""
        if not self._buffer:
            return
        report = {
            'samples': self._buffer[:],
            'count':   len(self._buffer),
        }
        self._buffer = []
        client.sendReport(modConfig.EVENT_MOVE_REPORT, report)
