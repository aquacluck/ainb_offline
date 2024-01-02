from __future__ import annotations
from datetime import datetime, timedelta
import json
from typing import *
import uuid

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
#   ui sends AinbEditOperations to EditContext, EditContext stores AinbEditOperations as
#   history before sending them to AinbEditOperationExecutor to run, then ui may re-render.
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
        return len(self.json.get("Nodes", []))

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


class AinbEditOperationExecutor:
    @classmethod
    def try_merge_history(excls, edit_op: AinbEditOperation, prev_op: AinbEditOperation) -> bool:
        # Reduces consecutive edits into the granularity we want to persist

        # TODO set AinbEditOperation.filehash upon exporting, on window close+confirm, ...
        if edit_op.filehash is not None or prev_op.filehash is not None:
            # Once a point in history has been persisted by user request, don't try to merge anything
            # into it regardless of recency.
            return False

        opcls: OP_IMPL = getattr(excls, edit_op.op_type)
        is_prev_op_amended = opcls.try_merge_history(edit_op, prev_op)
        return is_prev_op_amended

    @classmethod
    def dispatch(excls, ainb: MutableAinb, edit_op: AinbEditOperation):
        # resolve the op to one of the classes below and run it on the ainb
        opcls: OP_IMPL = getattr(excls, edit_op.op_type)
        opcls.execute(ainb, edit_op)

    class OP_IMPL:
        @staticmethod
        def try_merge_history(*_, **__) -> bool:
            # Mutates prev_op to match edit_op when applicable, returning True when this happens
            return False  # Don't merge by default

        @staticmethod
        def execute(ainb: MutableAinb, edit_op: AinbEditOperation):
            # Edits ainb according to edit_op
            raise NotImplementedError()

    class ADD_NODE(OP_IMPL):
        # No merge
        @staticmethod
        def execute(ainb: MutableAinb, edit_op: AinbEditOperation):
            # Duplicate so the caller can't mutate it
            node_json = json.loads(json.dumps(edit_op.op_value))

            assert node_json.get("Node Type")

            # Mint a guid - could be nice to have I dunno
            if guid := node_json.get("GUID") is None:
                node_json["GUID"] = str(uuid.uuid4())

            # Can this even happen?
            if ainb.json.get("Nodes") is None:
                print("it happened")
                ainb.json["Nodes"] = []

            # Append + assign index
            ainb.json["Nodes"].append(node_json)
            node_json["Node Index"] = len(ainb.json["Nodes"]) - 1

            print(f"Added node: {node_json}")

    class REPLACE_JSON(OP_IMPL):
        # No merge, clicking this button feels like saving your json
        @staticmethod
        def execute(ainb: MutableAinb, edit_op: AinbEditOperation):
            ainb.json.clear()
            ainb.json.update(json.loads(edit_op.op_value))
            print(f"Overwrote working ainb @ {ainb.location.fullfile}")

    class PARAM_UPDATE_DEFAULT(OP_IMPL):
        @staticmethod
        def try_merge_history(edit_op: AinbEditOperation, prev_op: AinbEditOperation) -> bool:
            if (edit_op.when - prev_op.when) > timedelta(seconds=2):
                return False  # Too far apart, don't merge
            if edit_op.op_selector != prev_op.op_selector:
                return False  # Different targets, don't merge (this means selectors:targets should be 1:1)

            prev_op.when = edit_op.when  # Bump time, allowing us to keep amending this entry
            prev_op.op_value = edit_op.op_value  # Value may be same or different, doesn't matter here
            return True  # prev_op should be re-persisted, current op is good to execute

        @staticmethod
        def execute(ainb: MutableAinb, edit_op: AinbEditOperation):
            #print(f"param default = {edit_op.op_value} @ {edit_op.op_selector}")
            sel = edit_op.op_selector
            if len(sel) != 6 or sel[0] != "Nodes" or sel[-1] not in ("Value", "Default Value"):
                raise AssertionError(f"Cannot parse selector {sel}")

            # The path is guaranteed to exist for this case, so no missing parts
            # aj["Nodes"][i]["Immediate Parameters"][aj_type][i_of_type]["Value"] = op_value
            # aj["Global Parameters"][aj_type][i_of_type]["Default Value"] = op_value

            if sel[1] == -420 and sel[2] == ParamSectionName.GLOBAL:
                target_params = ainb.json[ParamSectionName.GLOBAL]
            else:
                target_params = ainb.json[sel[0]][sel[1]][sel[2]]

            param_type, i_of_type, default_name = sel[3], sel[4], sel[5]
            if param_type == "vec3f":
                x, y, z, _ = edit_op.op_value
                target_params[param_type][i_of_type][default_name][0] = x
                target_params[param_type][i_of_type][default_name][1] = y
                target_params[param_type][i_of_type][default_name][2] = z
            else:
                target_params[param_type][i_of_type][default_name] = edit_op.op_value

