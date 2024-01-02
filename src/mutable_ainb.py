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
# - MutableAinb.json holds all ainb state, AinbGraph* reads from here to render ui,
#   ui dispatches AinbEditOperations to EditContext, EditContext stores AinbEditOperations
#   as history before sending them back to MutableAinb to execute, then ui may re-render.
#   Simple edits may not need to re-render, this is up to EditContext to determine.


class MutableAinb:
    @classmethod
    def from_dt_ainb(cls, dt_ainb: AINB, ainb_location: PackIndexEntry) -> MutableAinb:
        ainb = cls()
        ainb.json = dt_ainb.output_dict
        ainb.location = ainb_location
        return ainb

    def get_command_i(self, i: int) -> MutableAinbCommand:
        return MutableAinbCommand.from_ref(self.json["Commands"][i])

    def get_command_len(self) -> int:
        return len(self.json.get("Commands", []))

    def get_node_i(self, i: int) -> MutableAinbNode:
        return MutableAinbNode.from_ref(self.json["Nodes"][i])

    def get_node_len(self) -> int:
        return len(self.json["Nodes"])

    def get_global_param_section(self) -> Optional[MutableAinbNodeParamSection]:
        if section := self.json.get(ParamSectionName.GLOBAL):
            return MutableAinbNodeParamSection.from_ref(section, ParamSectionName.GLOBAL)


class MutableAinbCommand:
    @classmethod
    def from_ref(cls, json: dict) -> MutableAinbCommand:
        cmd = cls()
        cmd.json = json
        return cmd


class MutableAinbNode:
    @classmethod
    def from_ref(cls, json: dict) -> MutableAinbNode:
        node = cls()
        node.json = json
        return node

    def get_param_section(self, name: ParamSectionName) -> Optional[MutableAinbNodeParamSection]:
        if section := self.json.get(name):
            return MutableAinbNodeParamSection.from_ref(section, name)
        return None


class MutableAinbNodeParamSection:
    @classmethod
    def from_ref(cls, json: dict, name: str) -> MutableAinbNodeParamSection:
        section = cls()
        section.json = json
        section.name = name  # XXX subclass on name, globals/imm/in/out unique logic?
        return section


class MutableAinbNodeParam:
    @classmethod
    def from_ref(cls, json: dict, node_i: int, param_section_name: ParamSectionName, param_type: str, i_of_type: int) -> MutableAinbNodeParam:
        param = cls()
        param.json = json
        param.node_i = node_i
        param.param_section_name = param_section_name
        param.param_type = param_type
        param.i_of_type = i_of_type
        return param

    @property
    def param_default_name(self) -> str:
        return "Default Value" if self.param_section_name == ParamSectionName.GLOBAL else "Value"

    @property
    def name(self) -> str:
        return self.json.get("Name", AppErrorStrings.FAILNULL)

    def get_default_value_selector(self) -> AinbEditOperationDefaultValueSelector:
        op_selector = ("Nodes", self.node_i, self.param_section_name, self.param_type, self.i_of_type, self.param_default_name)
        return op_selector
