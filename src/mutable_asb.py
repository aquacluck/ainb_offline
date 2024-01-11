from __future__ import annotations
from datetime import datetime, timedelta
from typing import *
import uuid

import dearpygui.dearpygui as dpg
import orjson

from .app_types import *
from .dt_tools.asb import ASB


class MutableAsb:
    @classmethod
    def from_dt_asb(cls, dt_asb: ASB, asb_location: PackIndexEntry) -> MutableAsb:
        asb = cls()
        asb.json = dt_asb.output_dict
        asb.location = asb_location
        return asb

    def get_command_i(self, i: int) -> MutableAsbCommand:
        return MutableAsbCommand.from_ref(self.json["Commands"][i])

    def get_command_len(self) -> int:
        return len(self.json.get("Commands", []))

    def get_node_i(self, i: int) -> MutableAsbNode:
        return MutableAsbNode.from_ref(self.json["Nodes"][i])

    def get_node_len(self) -> int:
        return len(self.json.get("Nodes", []))

    def get_global_param_section(self) -> Optional[MutableAsbNodeParamSection]:
        if section := self.json.get("Local Blackboard Parameters"):
            return MutableAsbNodeParamSection.from_ref(section, "Local Blackboard Parameters")


class MutableAsbCommand:
    @classmethod
    def from_ref(cls, json: dict) -> MutableAsbCommand:
        cmd = cls()
        cmd.json = json
        return cmd


class MutableAsbNode:
    @classmethod
    def from_ref(cls, json: dict) -> MutableAsbNode:
        node = cls()
        node.json = json
        return node

    def get_param_section(self, name: ParamSectionName) -> Optional[MutableAsbNodeParamSection]:
        if section := self.json.get(name):
            return MutableAsbNodeParamSection.from_ref(section, name)
        return None


class MutableAsbNodeParamSection:
    @classmethod
    def from_ref(cls, json: dict, name: str) -> MutableAsbNodeParamSection:
        section = cls()
        section.json = json
        section.name = name
        return section


class MutableAsbNodeParam:
    @classmethod
    def from_ref(cls, json: dict, node_i: int, param_section_name: ParamSectionName, param_type: str, i_of_type: int) -> MutableAsbNodeParam:
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

    def get_default_value_selector(self) -> AsbEditOperationDefaultValueSelector:
        op_selector = ("Nodes", self.node_i, self.param_section_name, self.param_type, self.i_of_type, self.param_default_name)
        return op_selector


class AsbEditOperationExecutor:
    @classmethod
    def try_merge_history(excls, edit_op: AsbEditOperation, prev_op: AsbEditOperation) -> bool:
        # Reduces consecutive edits into the granularity we want to persist

        # TODO set AsbEditOperation.filehash upon exporting, on window close+confirm, ...
        if edit_op.filehash is not None or prev_op.filehash is not None:
            # Once a point in history has been persisted by user request, don't try to merge anything
            # into it regardless of recency.
            return False

        opcls: OP_IMPL = getattr(excls, edit_op.op_type)
        is_prev_op_amended = opcls.try_merge_history(edit_op, prev_op)
        return is_prev_op_amended

    @classmethod
    def dispatch(excls, asb: MutableAsb, edit_op: AsbEditOperation):
        # resolve the op to one of the classes below and run it on the asb
        opcls: OP_IMPL = getattr(excls, edit_op.op_type)
        opcls.execute(asb, edit_op)

    class OP_IMPL:
        @staticmethod
        def try_merge_history(*_, **__) -> bool:
            # Mutates prev_op to match edit_op when applicable, returning True when this happens
            return False  # Don't merge by default

        @staticmethod
        def execute(asb: MutableAsb, edit_op: AsbEditOperation):
            # Edits asb according to edit_op
            raise NotImplementedError()

    class ADD_NODE(OP_IMPL):
        # No merge
        @staticmethod
        def execute(asb: MutableAsb, edit_op: AsbEditOperation):
            # Duplicate so the caller can't mutate it
            node_json = orjson.loads(orjson.dumps(edit_op.op_value))

            assert node_json.get("Node Type")

            # Mint a guid - could be nice to have I dunno
            if guid := node_json.get("GUID") is None:
                node_json["GUID"] = str(uuid.uuid4())

            # Can this even happen?
            if asb.json.get("Nodes") is None:
                print("it happened")
                asb.json["Nodes"] = []

            # Append + assign index
            asb.json["Nodes"].append(node_json)
            node_json["Node Index"] = len(asb.json["Nodes"]) - 1

            print(f"Added node: {node_json}")

    class REPLACE_JSON(OP_IMPL):
        # No merge, clicking this button feels like saving your json
        @staticmethod
        def execute(asb: MutableAsb, edit_op: AsbEditOperation):
            asb.json.clear()
            asb.json.update(orjson.loads(edit_op.op_value))
            print(f"Overwrote working asb @ {asb.location.fullfile}")

    class PARAM_UPDATE_DEFAULT(OP_IMPL):
        @staticmethod
        def try_merge_history(edit_op: AsbEditOperation, prev_op: AsbEditOperation) -> bool:
            if (edit_op.when - prev_op.when) > timedelta(seconds=2):
                return False  # Too far apart, don't merge
            if edit_op.op_selector != prev_op.op_selector:
                return False  # Different targets, don't merge (this means selectors:targets should be 1:1)

            prev_op.when = edit_op.when  # Bump time, allowing us to keep amending this entry
            prev_op.op_value = edit_op.op_value  # Value may be same or different, doesn't matter here
            return True  # prev_op should be re-persisted, current op is good to execute

        @staticmethod
        def execute(asb: MutableAsb, edit_op: AsbEditOperation):
            #print(f"param default = {edit_op.op_value} @ {edit_op.op_selector}")
            sel = edit_op.op_selector
            if len(sel) != 6 or sel[0] != "Nodes" or sel[-1] not in ("Value", "Default Value"):
                raise AssertionError(f"Cannot parse selector {sel}")

            # The path is guaranteed to exist for this case, so no missing parts
            # aj["Nodes"][i]["Immediate Parameters"][aj_type][i_of_type]["Value"] = op_value
            # aj["Global Parameters"][aj_type][i_of_type]["Default Value"] = op_value

            if sel[1] == -420 and sel[2] == "Local Blackboard Parameters":
                target_params = asb.json["Local Blackboard Parameters"]
            else:
                target_params = asb.json[sel[0]][sel[1]][sel[2]]

            param_type, i_of_type, default_name = sel[3], sel[4], sel[5]
            if param_type == "vec3f":
                x, y, z, _ = edit_op.op_value
                target_params[param_type][i_of_type][default_name][0] = x
                target_params[param_type][i_of_type][default_name][1] = y
                target_params[param_type][i_of_type][default_name][2] = z
            else:
                target_params[param_type][i_of_type][default_name] = edit_op.op_value
