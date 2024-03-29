from __future__ import annotations
import colorsys
from dataclasses import dataclass, field
from datetime import datetime
from typing import *
import pathlib


class ConstDottableDict(dict):
    # Allows access by `self.foo` if "foo" in self: ConstDottableDict({"nice": 69}).nice == 69
    def __getattribute__(self, key: str):
        return self[key] if key in self else super().__getattribute__(key)


class ConstDottableStringSet(set):
    # Allows access by `self.foo` if "foo" in self: ConstDottableStringSet({"foo", "bar"}).foo == "foo"
    def __getattribute__(self, key: str):
        return key if key in self else super().__getattribute__(key)


# dpg can identify items by alias or int id, and accepts these interchangeably. However we need to be
# aware of which we have when constructing nested aliases, and eg sender args can introduce ints.
# Use dpg.get_item_alias(id) to normalize.
DpgTag = Union[int, str]


# dpg callbacks cannot await to spawn window coros etc (dpg is all sync), but we can intercept these requests in our main loop to do whatever we want.
# This sucks but the lack of async lambdas is too punishing with dpg callbacks.
class CallbackReq:
    """
    async def some_work(): pass

    dpg.add_button(callback=CallbackReq.SpawnCoro(some_work))
    # is piped into:
    await curio.spawn(some_work())

    # we could make another request type just await idk:
    dpg.add_button(callback=CallbackReq.AwaitCoro(some_work, [], {"quiet": True}))
    # is piped into:
    await some_work(dpg_args=(s,a,u), quiet=True)

    callbacks may return another callback to be immediately dispatched, which I use to handle extracting
    choices from ui+events, which main loop can use to schedule a coroutine handling only the relevant args.
    """

    @dataclass
    class Base:
        func: callable
        args: list = field(default_factory=list)
        kwargs: dict = field(default_factory=dict)
        def __call__(self, *dpg_args) -> Optional[CallbackReq.Base]:
            return self.func(*self.args, dpg_args=dpg_args, **self.kwargs)

    @dataclass  # func must be an awaitable callable, ie asyncio.iscoroutine
    class SpawnCoro(Base): pass

    @dataclass  # func must be an awaitable callable, ie asyncio.iscoroutine
    class AwaitCoro(Base): pass


RomfsFileTypes = ConstDottableStringSet({
    "AINB",
    "ASB",
})
def _get_romfsfiletype_from_filename(f: Union[str, pathlib.Path]) -> Optional["RomfsFileTypes"]:
    f = str(f)
    if f.endswith(".ainb"):
        return RomfsFileTypes.AINB
    if f.endswith(".asb") or f.endswith(".asb.zs"):
        return RomfsFileTypes.ASB
RomfsFileTypes.get_from_filename = _get_romfsfiletype_from_filename
RomfsFileTypes.all = lambda: [str(t) for t in RomfsFileTypes]


# Pending ui representation of node links gathered while rendering an ainb graph's nodes.
# The nodes are visually linked up only after they're all rendered, dpg requires this.
@dataclass
class DeferredNodeLinkCall:
    src_attr: str
    dst_attr: str
    src_node_i: int
    dst_node_i: int
    parent: DpgTag


# These represent mutations for the dt_tools.ainb.AINB.output_dict json dict
AinbEditOperationTypes = ConstDottableStringSet({
    "ADD_NODE",  # Use `op_value: dict` as node json, executor assigns the Node Index
    "REPLACE_JSON",  # Overwrite entire ainb with `op_value: str` json
    "PARAM_UPDATE_DEFAULT",  # Set the "Value" to op_value for a param found with op_selector
})


# These represent mutations for the dt_tools.asb.ASB.output_dict json dict
AsbEditOperationTypes = ConstDottableStringSet({
    "ADD_NODE",  # Use `op_value: dict` as node json, executor assigns the Node Index
    "REPLACE_JSON",  # Overwrite entire asb with `op_value: str` json
    "PARAM_UPDATE_DEFAULT",  # Set the "Value" to op_value for a param found with op_selector
})


AinbEditOperationDefaultValueSelector = Tuple[Union[str, int]]  # TODO better typing
AsbEditOperationDefaultValueSelector = Tuple[Union[str, int]]  # TODO better typing


@dataclass
class AinbEditOperation:
    op_type: AinbEditOperationTypes
    op_value: Any
    op_selector: Optional["JSONPath"] = None
    when: datetime = field(default_factory=datetime.now)
    filehash = None  # TODO this should be set on certain persist+export events


@dataclass
class AsbEditOperation:
    op_type: AsbEditOperationTypes
    op_value: Any
    op_selector: Union[AsbEditOperationDefaultValueSelector] = None
    when: datetime = field(default_factory=datetime.now)
    filehash = None  # TODO this should be set on certain persist+export events


@dataclass(frozen=True)
class AppColor:
    # hsv storage: 3 floats should be higher depth than 24b? And ui adjustments are nicer in hsv.
    # But rgb is nicer than a hue float for choosing pure hues, so we often create from rgb anyways.
    h: float
    s: float
    v: float

    @classmethod
    def from_hsv(cls, hsv: List[float]):
        return cls(*hsv)

    @classmethod
    def from_rgb24(cls, rgb: List[int]):
        hsv = colorsys.rgb_to_hsv(*[x/255. for x in rgb])
        return cls(*hsv)

    def to_rgb24(self) -> List[int]:
        rgb: List[float] = colorsys.hsv_to_rgb(self.h, self.s, self.v)
        return [int(x*255) for x in rgb]

    def to_rgba32(self, a: float = 1.0) -> List[int]:
        rgb: List[float] = colorsys.hsv_to_rgb(self.h, self.s, self.v)
        return [int(x*255) for x in rgb] + [int(a*255)]

    def set_hsv(self, h=None, s=None, v=None):
        return AppColor(h or self.h, s or self.s, v or self.v)


# Corresponding to globals held in dpg.get_value(), although storage should maybe be EditContext instead?
AppConfigKeys = ConstDottableStringSet({
    "APPVAR_PATH",
    "MODFS_PATH",
    "ROMFS_PATH",
    "TITLE_VERSION",
})


AppStaticTextureKeys = ConstDottableStringSet({
    "TOTK_MAP_PICKER_250",
})


# This is how files are usually located + identified
@dataclass
class PackIndexEntry:
    internalfile: str  # relative to packfile
    packfile: str  # romfs relative .pack.zs containing internalfile, or "Root"
    extension: RomfsFileTypes

    def __post_init__(self):
        self.internalfile = self.fix_backslashes(self.internalfile)
        self.packfile = self.fix_backslashes(self.packfile)

    @property
    def fullfile(self) -> str:
        return f"{self.packfile}:{self.internalfile}"

    # Intended to normalize short relative paths so db files are compatible, Root pack vs real pack lookup consistency, etc
    @staticmethod
    def fix_backslashes(file: Union[str, pathlib.Path]) -> str:
        f = str(file)
        if "\\" not in f:
            return f
        return str(pathlib.PurePosixPath(*pathlib.PureWindowsPath(file).parts))


# Major ainb json keys
ParamSectionName = ConstDottableDict({
    "GLOBAL": "Global Parameters",
    "IMMEDIATE": "Immediate Parameters",
    "INPUT": "Input Parameters",
    "OUTPUT": "Output Parameters",
    # "LINK": "Linked Nodes"
})
