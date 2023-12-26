from dataclasses import dataclass
from typing import *


class ConstDottableStringSet(set):  # allows access by `self.foo` if "foo" in self
    def __getattribute__(self, key: str):
        return key if key in self else super().__getattribute__(key)


class ConstDottableDict(dict):  # allows access by `self.foo` if "foo" in self
    def __getattribute__(self, key: str):
        return self[key] if key in self else super().__getattribute__(key)


TitleVersionIsTotk = lambda s: s.startswith("TOTK_")
TitleVersionIsWonder = lambda s: s.startswith("WONDER_")
TitleVersions = ConstDottableStringSet({
    "TOTK_100",
    "TOTK_110",
    "TOTK_111",
    "TOTK_112",
    "TOTK_120",
    "TOTK_121",
    "WONDER_100",
    "WONDER_101",
})


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


TitleVersionZsDicPack = ConstDottableDict({
    TitleVersions.TOTK_100: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_110: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_111: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_112: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_120: "Pack/ZsDic.pack.zs",
    TitleVersions.TOTK_121: "Pack/ZsDic.pack.zs",
    # TitleVersions.WONDER_* do not use zstd dicts
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


AppConfigKeys = ConstDottableStringSet({
    "AINB_FILE_INDEX_FILE",
    "APPVAR_PATH",
    "MODFS_PATH",
    "ROMFS_PATH",
    "TITLE_VERSION",
})


AppErrorStrings = ConstDottableDict({
    # `None` is useful and meaningful, never display that to the user when we're not expecting nulls
    # Make it obvious something has broken without a giant error string in the main ui
    "FAILNULL": "__error__",
})


PARAM_SECTION_NAME = ConstDottableDict({
    "GLOBAL": "Global Parameters",
    "IMMEDIATE": "Immediate Parameters",
    "INPUT": "Input Parameters",
    "OUTPUT": "Output Parameters",
})


AppStaticTextureKeys = ConstDottableStringSet({
    "TOTK_MAP_PICKER_250",
})


@dataclass
class AinbIndexCacheEntry:  # Basic info for each ainb file
    ainbfile: str # *.ainb, relative to romfs or pack root
    packfile: Optional[str] = None  # romfs relative .pack.zs containing ainbfile

    @property
    def fullfile(self) -> str:
        return f"{self.packfile}:{self.ainbfile}"


@dataclass
class DeferredNodeLinkCall:
    src_attr: str
    dst_attr: str
    src_node_i: int
    dst_node_i: int
    parent: Union[int, str]


# These represent mutations for the AINB.output_dict json dict
AinbEditOperationTypes = ConstDottableStringSet({
    "REPLACE_JSON",  # Overwrite entire ainb with `op_value: str` json
    "PARAM_UPDATE_DEFAULT",  # Set the "Value" to op_value for a param found with op_selector
})


@dataclass
class AinbEditOperation:
    op_type: AinbEditOperationTypes
    op_value: Any
    op_selector: Any = None
