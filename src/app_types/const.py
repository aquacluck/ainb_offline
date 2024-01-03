import dearpygui.dearpygui as dpg

from .types import *


class TitleVersion(str):
    NAMES = ConstDottableStringSet({
        "TOTK_100",
        "TOTK_110",
        "TOTK_111",
        "TOTK_112",
        "TOTK_120",
        "TOTK_121",
        "WONDER_100",
        "WONDER_101",
    })

    AI_GLOBAL_PACK = ConstDottableDict({
        NAMES.TOTK_100: "Pack/AI.Global.Product.100.pack.zs",
        NAMES.TOTK_110: "Pack/AI.Global.Product.110.pack.zs",
        NAMES.TOTK_111: "Pack/AI.Global.Product.110.pack.zs",
        NAMES.TOTK_112: "Pack/AI.Global.Product.110.pack.zs",
        NAMES.TOTK_120: "Pack/AI.Global.Product.120.pack.zs",
        NAMES.TOTK_121: "Pack/AI.Global.Product.120.pack.zs",
        NAMES.WONDER_100: "Pack/AIGameCommon.pack.zs",
        NAMES.WONDER_101: "Pack/AIGameCommon.pack.zs",
    })

    IDENTIFYING_FILE = ConstDottableDict({
        NAMES.TOTK_100: "Pack/AI.Global.Product.100.pack.zs",
        NAMES.TOTK_110: "RSDB/LoadingTips.Product.110.rstbl.byml.zs",
        NAMES.TOTK_111: "RSDB/LoadingTips.Product.111.rstbl.byml.zs",
        NAMES.TOTK_112: "RSDB/LoadingTips.Product.112.rstbl.byml.zs",
        NAMES.TOTK_120: "RSDB/LoadingTips.Product.120.rstbl.byml.zs",
        NAMES.TOTK_121: "RSDB/LoadingTips.Product.121.rstbl.byml.zs",
        NAMES.WONDER_100: "RSDB/StageInfo.Product.100.rstbl.byml.zs",
        NAMES.WONDER_101: "RSDB/StageInfo.Product.101.rstbl.byml.zs",  # XXX guessed
    })

    ROOT_PACK_DIRS = ConstDottableDict({
        NAMES.TOTK_100: ("AI", "Logic", "Sequence"),
        NAMES.TOTK_110: ("AI", "Logic", "Sequence"),
        NAMES.TOTK_111: ("AI", "Logic", "Sequence"),
        NAMES.TOTK_112: ("AI", "Logic", "Sequence"),
        NAMES.TOTK_120: ("AI", "Logic", "Sequence"),
        NAMES.TOTK_121: ("AI", "Logic", "Sequence"),
        NAMES.WONDER_100: ("AI",),
        NAMES.WONDER_101: ("AI",),
    })

    ZSDIC_PACK = ConstDottableDict({
        NAMES.TOTK_100: "Pack/ZsDic.pack.zs",
        NAMES.TOTK_110: "Pack/ZsDic.pack.zs",
        NAMES.TOTK_111: "Pack/ZsDic.pack.zs",
        NAMES.TOTK_112: "Pack/ZsDic.pack.zs",
        NAMES.TOTK_120: "Pack/ZsDic.pack.zs",
        NAMES.TOTK_121: "Pack/ZsDic.pack.zs",
        # NAMES.WONDER_* do not use zstd dicts
    })

    @classmethod
    def all(cls) -> "List[TitleVersion]":
        return [cls.lookup(v) for v in cls.NAMES]

    @classmethod
    def get(cls) -> "TitleVersion":
        # not const uh oh
        return cls.lookup(dpg.get_value(AppConfigKeys.TITLE_VERSION))

    @classmethod
    def lookup(cls, v: str) -> "TitleVersion":
        if v in cls.NAMES:
            return cls(v)
        raise ValueError(f"Unsupported TitleVersion: {v}")

    @property
    def is_totk(self) -> bool:
        return self.startswith("TOTK_")

    @property
    def is_wonder(self) -> bool:
        return self.startswith("WONDER_")

    @property
    def ai_global_pack(self) -> str:
        return self.AI_GLOBAL_PACK.get(str(self))

    @property
    def identifying_file(self) -> str:
        return self.IDENTIFYING_FILE.get(str(self))

    @property
    def root_pack_dirs(self) -> str:
        return self.ROOT_PACK_DIRS.get(str(self))

    @property
    def zsdic_pack(self) -> Optional[str]:
        return self.ZSDIC_PACK.get(str(self))


AppErrorStrings = ConstDottableDict({
    # `None` is useful and meaningful, never display that to the user when we're not expecting nulls
    # Make it obvious something has broken without a giant error string in the main ui
    "FAILNULL": "__error__",
})


AppStyleColors = ConstDottableDict({
    "ERRTEXT": AppColor.from_rgb24([128, 0, 0]),
    "GRAPH_COMMAND_HUE": AppColor.from_rgb24([128, 0, 255]),
    "GRAPH_GLOBALS_HUE": AppColor.from_rgb24([0, 255, 0]),
    "GRAPH_MODULE_HUE": AppColor.from_rgb24([255, 160, 0]),
    "LIST_ENTRY_SEPARATOR": AppColor.from_hsv([0, 0, 0.5]),

    # blue tint needed for contrast against orange node_types, desaturating this makes them blur together too much
    "NEW_NODE_PICKER_PARAM_DETAILS": AppColor.from_hsv([0.5, 0.1, 0.66]),
})
