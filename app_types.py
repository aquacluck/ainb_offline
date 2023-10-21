from dataclasses import dataclass
from typing import *


class ConstDottableStringSet(set):  # allows access by `self.foo` if "foo" in self
    def __getattribute__(self, key: str):
            return key if key in self else super().__getattribute__(key)

class ConstDottableDict(dict):  # allows access by `self.foo` if "foo" in self
    def __getattribute__(self, key: str):
            return key if key in self else super().__getattribute__(key)


AppConfigKeys = ConstDottableStringSet({
    "AINB_FILE_INDEX_FILE",
    "APPVAR_PATH",
    "ROMFS_PATH",
    "ZSDIC_FILENAME",
})


AppErrorStrings = ConstDottableDict({
    # `None` is useful and meaningful, never display that to the user when we're not expecting nulls
    # Make it obvious something has broken without a giant error string in the main ui
    "FAILNULL": "__error__",
})


@dataclass
class AinbIndexCacheEntry:  # Basic info for each ainb file
    ainbfile: str # *.ainb, relative to romfs or pack root
    packfile: Optional[str] = None  # romfs relative .pack.zs containing ainbfile


@dataclass
class DeferredNodeLinkCall:
    src_attr: str
    dst_attr: str
    src_node_i: int
    dst_node_i: int
    parent: Union[int, str]
