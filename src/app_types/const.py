from .types import *


TitleVersionAiGlobalPack = ConstDottableDict({
    TitleVersions.TOTK_100: "Pack/AI.Global.Product.100.pack.zs",
    TitleVersions.TOTK_110: "Pack/AI.Global.Product.110.pack.zs",
    TitleVersions.TOTK_111: "Pack/AI.Global.Product.110.pack.zs",
    TitleVersions.TOTK_112: "Pack/AI.Global.Product.110.pack.zs",
    TitleVersions.TOTK_120: "Pack/AI.Global.Product.120.pack.zs",
    TitleVersions.TOTK_121: "Pack/AI.Global.Product.120.pack.zs",
    TitleVersions.WONDER_100: "Pack/AIGameCommon.pack.zs",
    TitleVersions.WONDER_101: "Pack/AIGameCommon.pack.zs",
})


TitleVersionIdentifyingFiles = ConstDottableDict({
    TitleVersions.TOTK_100: "Pack/AI.Global.Product.100.pack.zs",
    TitleVersions.TOTK_110: "RSDB/LoadingTips.Product.110.rstbl.byml.zs",
    TitleVersions.TOTK_111: "RSDB/LoadingTips.Product.111.rstbl.byml.zs",
    TitleVersions.TOTK_112: "RSDB/LoadingTips.Product.112.rstbl.byml.zs",
    TitleVersions.TOTK_120: "RSDB/LoadingTips.Product.120.rstbl.byml.zs",
    TitleVersions.TOTK_121: "RSDB/LoadingTips.Product.121.rstbl.byml.zs",
    TitleVersions.WONDER_100: "RSDB/StageInfo.Product.100.rstbl.byml.zs",
    TitleVersions.WONDER_101: "RSDB/StageInfo.Product.101.rstbl.byml.zs",  # XXX guessed
})


TitleVersionRootPackDirs = ConstDottableDict({
    TitleVersions.TOTK_100: ("AI", "Logic", "Sequence"),
    TitleVersions.TOTK_110: ("AI", "Logic", "Sequence"),
    TitleVersions.TOTK_111: ("AI", "Logic", "Sequence"),
    TitleVersions.TOTK_112: ("AI", "Logic", "Sequence"),
    TitleVersions.TOTK_120: ("AI", "Logic", "Sequence"),
    TitleVersions.TOTK_121: ("AI", "Logic", "Sequence"),
    TitleVersions.WONDER_100: ("AI",),
    TitleVersions.WONDER_101: ("AI",),
})


TitleVersionZsDicPack = ConstDottableDict({
    TitleVersions.TOTK_100: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_110: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_111: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_112: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_120: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_121: "Pack/ZsDic.pack.zs",
    # TitleVersions.WONDER_* do not use zstd dicts
})


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
})
