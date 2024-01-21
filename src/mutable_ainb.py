from __future__ import annotations
from datetime import datetime, timedelta
from typing import *
import uuid

import dearpygui.dearpygui as dpg
import orjson

from .app_types import *
from .dt_tools.ainb import AINB
from .jsonpath import JSONPath


# - dt_tools.ainb.AINB.output_dict is our canonical format, no matter the cost.
#   This keeps manual edits, debugging, interop, etc accessible to almost anyone.
# - Mutable types are accessed by reference and as long as all mutations are
#   performed in-place, this means we can query->mutate at specific spots in the
#   json tree without maintaining a copy.
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

    @property
    def commands(self) -> List[MutableAinbCommand]:
        path = JSONPath(["Commands", "*"], {"command_i": 1})
        return [MutableAinbCommand(self, p) for p in path.glob(self.json)]

    @property
    def nodes(self) -> List[MutableAinbNode]:
        path = JSONPath(["Nodes", "*"], {"node_i": 1})
        return [MutableAinbNode(self, p) for p in path.glob(self.json)]

    @property
    def global_params(self) -> List[MutableAinbParam]:
        path = JSONPath([ParamSectionName.GLOBAL, '**', '*'], {"param_section_name": 0, "param_type": 1, "i_of_type": 2})
        return [MutableAinbParam(self, p) for p in path.glob(self.json)]


class MutableAinbCommand:
    def __init__(self, ainb: MutableAinb, path: JSONPath):
        self.ainb = ainb
        self.path = path

    @property
    def json(self):
        return self.path.get_one(self.ainb.json)


class MutableAinbNode:
    def __init__(self, ainb: MutableAinb, path: JSONPath):
        self.ainb = ainb
        self.path = path

    @property
    def json(self):
        return self.path.get_one(self.ainb.json)

    @property
    def all_params(self) -> List[MutableAinbParam]:
        out = []
        idx_next = len(self.path.path)
        for sname in [ParamSectionName.IMMEDIATE, ParamSectionName.INPUT, ParamSectionName.OUTPUT]:
            path = self.path.copy()
            path.path += [sname, '**', '*']
            path.names["param_section_name"] = idx_next
            path.names["param_type"] = idx_next + 1
            path.names["i_of_type"] = idx_next + 2
            out += [MutableAinbParam(self.ainb, p) for p in path.glob(self.ainb.json)]
        return out

    @property
    def all_links(self) -> List[MutableAinbLink]:
        out = []
        idx_next = len(self.path.path)
        path = self.path.copy()
        path.path += ["Linked Nodes", '**', '*']
        path.names["link_type"] = idx_next + 1
        path.names["i_of_link_type"] = idx_next + 2
        out += [MutableAinbLink(self.ainb, p) for p in path.glob(self.ainb.json)]
        return out


class MutableAinbParam:
    def __init__(self, ainb: MutableAinb, path: JSONPath):
        self.ainb = ainb
        self.path = path

    @property
    def json(self):
        return self.path.get_one(self.ainb.json)

    @property
    def param_section_name(self) -> str:
        return self.path.segment_by_name("param_section_name")

    @property
    def param_type(self) -> str:
        return self.path.segment_by_name("param_type")

    @property
    def i_of_type(self) -> int:
        return self.path.segment_by_name("i_of_type")

    @property
    def node_i(self) -> int:
        if self.param_section_name == ParamSectionName.GLOBAL:
            return -420  # lol
        return self.path.segment_by_name("node_i")

    @property
    def param_default_name(self) -> str:
        return "Default Value" if self.param_section_name == ParamSectionName.GLOBAL else "Value"

    @property
    def name(self) -> str:
        return self.json.get("Name", AppErrorStrings.FAILNULL)

    def get_default_value_selector(self) -> JSONPath:
        path = self.path.copy()
        path.path.append(self.param_default_name)
        path.names["param_default_name"] = len(path.path) - 1
        return path


class MutableAinbLink:
    def __init__(self, ainb: MutableAinb, path: JSONPath):
        self.ainb = ainb
        self.path = path

    @property
    def json(self):
        return self.path.get_one(self.ainb.json)

    @property
    def link_type(self) -> str:
        return self.path.segment_by_name("link_type")

    @property
    def i_of_link_type(self) -> int:
        return self.path.segment_by_name("i_of_link_type")


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
            node_json = orjson.loads(orjson.dumps(edit_op.op_value))

            assert node_json.get("Node Type")

            # Mint a guid - could be nice to have I dunno
            if guid := node_json.get("GUID") is None:
                node_json["GUID"] = str(uuid.uuid4())

            # This can happen
            if ainb.json.get("Nodes") is None:
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
            ainb.json.update(orjson.loads(edit_op.op_value))
            print(f"Overwrote working ainb @ {ainb.location.fullfile}")

    class PARAM_UPDATE_DEFAULT(OP_IMPL):
        @staticmethod
        def try_merge_history(edit_op: AinbEditOperation, prev_op: AinbEditOperation) -> bool:
            if (edit_op.when - prev_op.when) > timedelta(seconds=2):
                return False  # Too far apart, don't merge
            if edit_op.op_type != prev_op.op_type:
                return False
            if edit_op.op_selector.path != prev_op.op_selector.path:
                return False  # Different targets, don't merge (this means selectors:targets should be 1:1)

            prev_op.when = edit_op.when  # Bump time, allowing us to keep amending this entry
            prev_op.op_value = edit_op.op_value  # Value may be same or different, doesn't matter here
            return True  # prev_op should be re-persisted, current op is good to execute

        @staticmethod
        def execute(ainb: MutableAinb, edit_op: AinbEditOperation):
            # The path is guaranteed to exist for this case, so no missing parts
            # aj["Nodes"][i]["Immediate Parameters"][aj_type][i_of_type]["Value"] = op_value
            # aj["Global Parameters"][aj_type][i_of_type]["Default Value"] = op_value

            #print(f"param default = {edit_op.op_value} @ {edit_op.op_selector}")
            path: JSONPath = edit_op.op_selector

            if path.segment_by_name("param_type") == "vec3f":
                lhs = path.get_one(ainb.json)
                x, y, z, _ = edit_op.op_value
                lhs[0] = x  # Mutate components in-place
                lhs[1] = y
                lhs[2] = z
            else:
                path.update_one(ainb.json, edit_op.op_value)
