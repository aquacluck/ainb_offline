from __future__ import annotations
import json
from typing import *

import dearpygui.dearpygui as dpg

from .app_types import *
from .dt_ainb.ainb import AINB


# Core concepts:
# - dt_ainb.AINB.output_dict is our canonical format, no matter the cost.
#   This keeps manual edits, debugging, interop, etc accessible to almost anyone.
# - Mutable types are passed by reference and as long as all mutations are
#   performed in-place, this means we can anchor our objects to specific spots
#   in the json tree without maintaining a copy.
# - However this complicates operations like node insertion, where we must alter
#   a list of mutables without reassigning over any of them, as well as ensuring
#   our List[MutableAinbNode] matches this insertion. So these "json fragment"
#   classes should be short lived, a thin wrapper over the fragment that we throw
#   away after each render, and reinstantiate as needed inside callbacks/etc.
# - (Maintaining a large pool of these fragments objs might help performance for eg
#   continuous slider inputs, we could reassign their reference as needed.)


class MutableAinb:
    @classmethod
    def from_dt_ainb(cls, dt_ainb: AINB, ainb_location: PackIndexEntry) -> MutableAinb:
        ainb = cls()
        ainb.json = dt_ainb.output_dict
        ainb.location = ainb_location
        return ainb

    def get_node_i(self, i: int) -> MutableAinbNode:
        return MutableAinbNode.from_ref(self.json["Nodes"][i])

    def get_global_param_section(self) -> Optional[MutableAinbNodeParamSection]:
        if section := self.json.get(ParamSectionName.GLOBAL):
            return MutableAinbNodeParamSection(section)


class MutableAinbNode:
    @classmethod
    def from_ref(cls, json: dict) -> MutableAinbNode:
        node = cls()
        node.json = json
        return node

    def get_param_section(self, name: ParamSectionName) -> Optional[MutableAinbNodeParamSection]:
        if section := self.json.get(name):
            return MutableAinbNodeParamSection(section)
        return None


class MutableAinbNodeParamSection:
    @classmethod
    def from_ref(cls, json: dict) -> MutableAinbNodeParamSection:
        node = cls()
        node.json = json
        return node


