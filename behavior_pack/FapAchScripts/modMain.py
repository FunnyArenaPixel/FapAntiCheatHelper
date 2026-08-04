# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as clientApi
from FapAchScripts import modConfig


@Mod.Binding(name=modConfig.mod_name, version='0.0.1')
class FapAchMod(object):
    """FapACH 反作弊辅助客户端 MOD 入口。"""

    def __init__(self):
        pass

    @Mod.InitClient()
    def InitClient(self):
        clientApi.RegisterSystem(
            modConfig.mod_name,
            modConfig.client_system_name,
            modConfig.client_class_path
        )
