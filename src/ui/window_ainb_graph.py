from __future__ import annotations
from datetime import datetime
import functools
import json
import pathlib
from typing import *
from collections import defaultdict

import dearpygui.dearpygui as dpg

from ..app_ainb_cache import scoped_pack_lookup
from ..edit_context import EditContext
from ..mutable_ainb import MutableAinb, MutableAinbNodeParam
from .. import db, pack_util
from ..app_types import *


# Legend:
# _nnn per-mode-per-type counter on params, like ainb indexing
# @ flags and node meta
ParamSectionLegend = {
    ParamSectionName.GLOBAL: "$",
    ParamSectionName.IMMEDIATE: "#",
    ParamSectionName.INPUT: "I",
    ParamSectionName.OUTPUT: "O",
}
ParamSectionDpgAttrType = {
    ParamSectionName.GLOBAL: dpg.mvNode_Attr_Static,
    ParamSectionName.IMMEDIATE: dpg.mvNode_Attr_Static,
    ParamSectionName.INPUT: dpg.mvNode_Attr_Input,
    ParamSectionName.OUTPUT: dpg.mvNode_Attr_Output,
}
#
# All dpg.node contents must be inside a dpg.node_attribute, which can make things weird.
# dpg "nodes" are just the graph ui elements, although they do map to ainb nodes and this is a confusing coincidence
#
# ainb tag tree:
#     /node{int}: Map<int, node_tag_ns>, a namespace for each node
#     /Globals: namespace for a fake ainb node (real dpg node) holding global params
#
# Each node tag tree/ns contains:
#     /Node: dpg.node
#     /LinkTarget: dpg.node_attribute, used by flow control nodes to reference nodes they operate on
#     /Params/Immediate Parameters/{str}: Map<str, dpg.node_attribute>
#     /Params/Input Parameters/{str}: Map<str, dpg.node_attribute>
#     /Params/Output Parameters/{str}: Map<str, dpg.node_attribute>
#     optional /stdlink{int}: Map<int, dpg.node_attribute>, Standard Link
#     optional /reslink{int}: Map<int, dpg.node_attribute>, Resident Update Link


def prettydate(d: datetime) -> str:
    # https://stackoverflow.com/a/5164027
    delta = datetime.now() - d
    s = delta.seconds
    if delta.days > 7 or delta.days < 0:
        return d.strftime('%d %b %y')
    elif delta.days == 1:
        return '1 day ago'
    elif delta.days > 1:
        return '{} days ago'.format(delta.days)
    elif s <= 1:
        return 'just now'
    elif s < 60:
        return '{} seconds ago'.format(s)
    elif s < 120:
        return '1 minute ago'
    elif s < 3600:
        return '{} minutes ago'.format(s/60)
    elif s < 7200:
        return '1 hour ago'
    else:
        return '{} hours ago'.format(s/3600)


@functools.cache
def make_node_theme_for_hue(hue: AppColor):
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(dpg.mvNodeCol_TitleBar, hue.set_hsv(s=0.5, v=0.4).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_TitleBarHovered, hue.set_hsv(s=0.5, v=0.5).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_TitleBarSelected, hue.set_hsv(s=0.4, v=0.55).to_rgb24(), category=dpg.mvThemeCat_Nodes)

            dpg.add_theme_color(dpg.mvNodeCol_NodeBackground, hue.set_hsv(s=0.15, v=0.3).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundHovered, hue.set_hsv(s=0.1, v=0.35).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundSelected, hue.set_hsv(s=0.1, v=0.35).to_rgb24(), category=dpg.mvThemeCat_Nodes)
    return theme


class WindowAinbGraph:
    def __init__(self, ainb_location: PackIndexEntry, ectx: EditContext):
        print(f"Opening {ainb_location.fullfile}")
        self.ectx = ectx
        self.ainb = self.ectx.load_ainb(ainb_location)

    @property
    def history_entries_tag(self) -> DpgTag:
        return f"{self.tag}/tabs/history/entries"

    @property
    def node_editor(self) -> DpgTag:
        return f"{self.tag}/tabs/graph/editor"

    @property
    def json_textbox(self) -> DpgTag:
        return f"{self.tag}/tabs/json/textbox"

    def create(self, **window_kwargs) -> DpgTag:
        category, ainbfile = pathlib.Path(self.ainb.location.internalfile).parts
        if self.ainb.location.packfile == "Root":
            window_label = f"[{category}] {ainbfile}"
        else:
            window_label = f"[{category}] {ainbfile} [from {self.ainb.location.packfile}]"

        self.tag = dpg.add_window(
            label=window_label,
            on_close=lambda: self.ectx.close_ainb_window(self.ainb.location),
            **window_kwargs,
        )
        self.render_contents()
        return self.tag

    def redump_json_textbox(self):
        # Replace json textbox with working ainb (possibly dirty)
        ainb_json_str = json.dumps(self.ainb.json, indent=4)
        dpg.set_value(self.json_textbox, ainb_json_str)

    def rerender_graph_from_json(self):
        user_json_str = dpg.get_value(self.json_textbox)

        # Send event to edit ctx
        edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.REPLACE_JSON, op_value=user_json_str)
        self.ectx.perform_new_edit_operation(self.ainb, edit_op)

        # Re-render editor TODO this belongs in AinbGraphEditor?
        dpg.delete_item(self.node_editor)
        self.editor.render_contents()

    def rerender_history(self):
        dpg.delete_item(self.history_entries_tag, children_only=True)
        # history is stored+appended with time asc, but displayed with time desc
        for edit_op in reversed(self.ectx.edit_histories.get(self.ainb.location.fullfile, [])):
            with dpg.group(parent=self.history_entries_tag):
                with dpg.group():
                    selector = f"@ {edit_op.op_selector}" if edit_op.op_selector else ""
                    dpg.add_text(f"{prettydate(edit_op.when)}: {edit_op.op_type} {selector}")
                    dpg.add_text(str(edit_op.op_value))
                    dpg.add_separator()

    def render_contents(self):
        def _tab_change(sender, data, app_data):
            entered_tab = dpg.get_item_alias(data)
            is_autodump = True  # dpg.get_value(f"{self.tag}/tabs/json/autodump")
            if entered_tab == f"{self.tag}/tabs/json" and is_autodump:
                self.redump_json_textbox()
            if entered_tab == f"{self.tag}/tabs/history" and is_autodump:
                self.rerender_history()

        with dpg.tab_bar(tag=f"{self.tag}/tabs", parent=self.tag, callback=_tab_change):
            # dpg.add_tab_button(label="[max]", callback=dpg.maximize_viewport)  # works at runtime, fails at init?
            # dpg.add_tab_button(label="wipe cache")
            with dpg.tab(tag=f"{self.tag}/tabs/graph", label="Node Graph"):
                with dpg.child_window(autosize_x=True, autosize_y=True) as graph_window:
                    self.editor = AinbGraphEditor.create(tag=self.node_editor, parent=graph_window, ainb=self.ainb)

            with dpg.tab(tag=f"{self.tag}/tabs/json", label="Parsed JSON"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    with dpg.group(horizontal=True):
                        #dpg.add_button(label="Refresh JSON", callback=self.redump_json_textbox)
                        #dpg.add_checkbox(label="(Always refresh)", tag=f"{self.tag}/tabs/json/autodump", default_value=True)
                        dpg.add_button(label="Apply Changes", callback=self.rerender_graph_from_json)
                        #      dpg.add_button(label="Overwrite AINB") duh
                        #      dpg.add_button(label="Open JSON in: ", source="jsdfl/opencmd")
                        #      dpg.add_input_text(default_value='$EDITOR "%s"', tag="jsdfl/opencmd")
                    dpg.add_input_text(tag=self.json_textbox, default_value="any slow dumps?", width=-1, height=-1, multiline=True, tab_input=True, readonly=False)
                    self.redump_json_textbox()

            with dpg.tab(tag=f"{self.tag}/tabs/history", label="Edit History"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    dpg.add_group(tag=self.history_entries_tag)
                    self.rerender_history()

            save_ainb = lambda: self.ectx.save_ainb(self.ainb)
            dpg.add_tab_button(label="Save to modfs", callback=save_ainb)


class AinbGraphEditor:
    @classmethod
    def create(cls, tag: DpgTag, parent: DpgTag, ainb: MutableAinb) -> AinbGraphEditor:
        editor = cls(tag=tag, parent=parent)
        editor.set_ainb(ainb)
        return editor

    def __init__(self, tag: DpgTag, parent: DpgTag):
        self.tag = tag
        self.parent = parent

    def set_ainb(self, ainb: MutableAinb) -> None:
        self.ainb = ainb
        # TODO clear contents?
        self.render_contents()

    def render_contents(self):
        # sludge for now
        def _link_callback(sender, app_data):
            dpg.add_node_link(app_data[0], app_data[1], parent=sender)
        def _delink_callback(sender, app_data):
            dpg.delete_item(app_data)

        with dpg.group(horizontal=True, parent=self.parent):
            dpg.add_button(label=f"Add Node")
            # TODO manually managed popup we can close/destroy/etc
            # TODO sections for elements + userdefined + module nodes
            # TODO actually insert the node
            with dpg.popup(dpg.last_item(), mousebutton=dpg.mvMouseButton_Left, min_size=(1024, 768), max_size=(1024, 768)):
                file_cat = self.ainb.json["Info"]["File Category"]
                node_usages = db.AinbFileParamNameUsageIndex.get_node_types(db.Connection.get(), file_cat)

                fset = dpg.generate_uuid()
                finput = dpg.add_input_text(hint="Node Type...", callback=lambda s, a: dpg.set_value(fset, a))
                with dpg.filter_set(tag=fset):
                    for (node_type, param_names_json) in node_usages:
                        with dpg.group(horizontal=True, filter_key=node_type, user_data=param_names_json):
                            dpg.add_text(node_type)
                            dpg.add_text(param_names_json)

                dpg.focus_item(finput)


        # TODO top bar, might replace tabs?
        # - "jump to" node list dropdown
        # - add node button with searchable popup for node type
        # - save to modfs button, dirty indicator
        # - "{}" json button?

        # Main graph ui + rendering nodes
        dpg.add_node_editor(
            tag=self.tag,
            parent=self.parent,
            callback=_link_callback,
            delink_callback=_delink_callback,
            minimap=True,
            minimap_location=dpg.mvNodeMiniMap_Location_BottomRight
        )

        self.render_ainb_nodes()

    def render_ainb_nodes(self):
        aj = self.ainb.json  # ainb json. we call him aj
        category, _ainbfile = pathlib.Path(self.ainb.location.internalfile).parts

        # TODO special layout+style for globals node (and move node nearby when hovering on a consuming param?)
        # TODO globals links, eg <Assassin_Senior.action.interuptlargedamage.module>.nodes[0].#ASCommand["Global Parameters Index"] == 0 points to $ASName="LargeDamagge"
        # Render globals as a type of node? Not sure if dumb, we do need to link/associate globals into nodes anyways somehow
        if mutable_globals_section := self.ainb.get_global_param_section():
            globals_node = AinbGraphEditorGlobalsNode(editor=self, section=mutable_globals_section)
            globals_node.render()

        graph_nodes = [
            AinbGraphEditorNode(editor=self, node=self.ainb.get_node_i(i))
            for i in range(self.ainb.get_node_len())
        ]

        # We can't link nodes that don't exist yet
        deferred_link_calls: List[DeferredNodeLinkCall] = []
        for node in graph_nodes:
            deferred_link_calls += node.render()

        # All nodes+attributes exist, now we can link them
        self.render_links_and_layout(deferred_link_calls)

    def render_links_and_layout(self, link_calls: List[DeferredNodeLinkCall]):
        # Add links
        node_i_links = defaultdict(set)
        for link in link_calls:
            # print(link, flush=True)
            # breakpoint()
            dpg.add_node_link(link.src_attr, link.dst_attr, parent=link.parent)
            node_i_links[link.src_node_i].add(link.dst_node_i)

        # For panning to commands on open
        NamedCoordDict = Dict[str, Tuple[int, int]]
        command_named_coords: NamedCoordDict = {}

        # TODO at least centralize some of the layout numbers
        LAYOUT_X_SPACING = 800
        LAYOUT_Y_SPACING = 500
        CORNER_PAD = 10  # Distance from top left corner for root

        # Determine each node's depth = x coord
        node_max_depth_map = defaultdict(int)  # commands start at 0
        for command_i in range(self.ainb.get_command_len()):
            command = self.ainb.get_command_i(command_i)
            node_i = command.json["Left Node Index"]
            if node_i == -1:
                continue

            # FIXME something in Sequence/Amiibo.module.ainb is going infinite, it was bound to happen
            def walk_for_depth_map(node_i, walk_depth):
                cur_max_depth = node_max_depth_map[node_i]
                if walk_depth > cur_max_depth:
                    node_max_depth_map[node_i] = walk_depth
                for edge_i in node_i_links[node_i]:
                    if node_i not in node_i_links[edge_i]:
                        walk_for_depth_map(edge_i, walk_depth+1)
                    else:
                        # don't attempt to count depth inside cycles,
                        # but inherit its depth if we've already seen it deeper than this walk.
                        edge_max_depth = node_max_depth_map[edge_i]
                        if edge_max_depth > node_max_depth_map[node_i]:
                            node_max_depth_map[node_i] = edge_max_depth
                        else:
                            node_max_depth_map[edge_i] = node_max_depth_map[node_i]
            walk_for_depth_map(node_i, 0)
            command_named_coords[command.json["Name"]] = (0 * LAYOUT_X_SPACING, command_i * LAYOUT_Y_SPACING)

        # Pan to entry point by subtracting the destination coords, putting them at effectively [0, 0]
        # cuz i dunno how to scroll the graph editor region itself
        entry_point_offset = [0, 0]
        open_to_command = "Root"  # take as input?
        for cmd_name, cmd_coord in command_named_coords.items():
            entry_point_offset = cmd_coord  # We'll take anything meaningful, don't assume [0, 0] isn't void space
            if cmd_name == open_to_command:
                break  # Exact match
        entry_point_offset = [entry_point_offset[0] - CORNER_PAD, entry_point_offset[1] - CORNER_PAD]

        # Layout
        node_y_at_depth = defaultdict(int)
        for node_i, max_depth in node_max_depth_map.items():
            node_tag = f"{self.tag}/node{node_i}/Node"
            x = LAYOUT_X_SPACING * max_depth - entry_point_offset[0]
            y = LAYOUT_Y_SPACING * node_y_at_depth[max_depth] - entry_point_offset[1]
            node_y_at_depth[max_depth] += 1
            pos = [x, y]
            # print(node_tag, pos)
            dpg.set_item_pos(node_tag, pos)


class AinbGraphEditorNode:
    def __init__(self, editor: AinbGraphEditor, node: MutableAinbNode):
        self.editor = editor
        self.node = node

    @property
    def node_i(self) -> int:
        return self.node.json["Node Index"]

    @property
    def node_json(self) -> dict:
        return self.node.json

    @property
    def tag(self) -> DpgTag:
        # TODO AinbGraphEditor.get_node_json(i) instead?
        return f"{self.editor.tag}/node{self.node_i}"

    def render(self) -> List[DeferredNodeLinkCall]:
        output_attr_links: List[DeferredNodeLinkCall] = []

        node_type = self.node_json["Node Type"]
        node_name = self.node_json["Name"]
        if node_type == "UserDefined":
            label = f"{node_name} ({self.node_i})"
        else:
            label = f"{node_type} ({self.node_i})"

        rh = AinbGraphEditorRenderHelpers
        with dpg.node(tag=f"{self.tag}/Node", label=label, parent=self.editor.tag):
            rh.node_topmeta(self)
            if section := self.node.get_param_section(ParamSectionName.IMMEDIATE):
                rh.node_param_section(self, section)
            if section := self.node.get_param_section(ParamSectionName.INPUT):
                rh.node_param_section(self, section)
            if section := self.node.get_param_section(ParamSectionName.OUTPUT):
                rh.node_param_section(self, section)

            for aj_link_type, aj_links in self.node_json.get("Linked Nodes", {}).items():
                for i_of_link_type, aj_link in enumerate(aj_links):
                    #print(aj_link_type, aj_link)
                    if aj_link_type == "Output/bool Input/float Input Link": # 0
                        output_attr_links += rh.link_bidirectional_lookup(self, aj_link, i_of_link_type)
                    elif aj_link_type == "Standard Link": # 2
                        output_attr_links += rh.link_standard(self, aj_link, i_of_link_type)
                    elif aj_link_type == "Resident Update Link": # 3
                        output_attr_links += rh.link_resident_update(self, aj_link, i_of_link_type)
                    elif aj_link_type == "String Input Link": # 4
                        pass # output_attr_links += process_ainb_node_link__string_input_link(self, aj_link, i_of_link_type)
                    elif aj_link_type == "int Input Link": # 5 the opposite direction of type 0? TODO learn things
                        pass # output_attr_links += process_ainb_node_link__int_input_link(self, aj_link, i_of_link_type)
                    else:
                        print(f"Unsupported link type {aj_link_type}")
                        breakpoint()
                        continue

        return output_attr_links


class AinbGraphEditorGlobalsNode(AinbGraphEditorNode):
    def __init__(self, editor: AinbGraphEditor, section: MutableAinbNodeParamSection):
        self.editor = editor
        self.section = section

    @property
    def node_i(self) -> int:
        return -420  # lol

    @property
    def node_json(self) -> dict:
        return self.editor.ainb.json

    @property
    def tag(self) -> DpgTag:
        return f"{self.editor.tag}/Globals"

    def render(self):
        globals_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_GLOBALS_HUE)
        with dpg.node(tag=f"{self.tag}/Node", label=ParamSectionName.GLOBAL, parent=self.editor.tag):
            AinbGraphEditorRenderHelpers.node_param_section(self, self.section)
        dpg.bind_item_theme(f"{self.tag}/Node", globals_node_theme)


class AinbGraphEditorRenderHelpers:
    @staticmethod
    def node_topmeta(node: AinbGraphEditorNode) -> None:
        with dpg.node_attribute(tag=f"{node.tag}/LinkTarget", attribute_type=dpg.mvNode_Attr_Input):
            # TODO editor.commands: List[AinbGraphEditorCommand]
            # editor.get_command_json(name: str) -> dict
            for command_i, command in enumerate(node.editor.ainb.json.get("Commands", [])):
                if node.node_i == command["Left Node Index"]:
                    cmd_name = command["Name"]
                    dpg.add_text(f"@ Command[{cmd_name}]")
                    command_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_COMMAND_HUE)
                    dpg.bind_item_theme(f"{node.tag}/Node", command_node_theme)


            for aj_flag in node.node_json.get("Flags", []):
                if aj_flag == "Is External AINB":
                    for aref in node.editor.ainb.json["Embedded AINB Files"]:
                        if aref["File Path"] != node.node_json["Name"] + ".ainb":
                            continue

                        #print(aref["Count"]) ...instance/link count? TODO

                        dest_ainbfile = aref["File Category"] + '/' + aref["File Path"]
                        dest_location = scoped_pack_lookup(PackIndexEntry(internalfile=dest_ainbfile, packfile=node.editor.ainb.location.packfile, extension="ainb"))
                        with dpg.group(horizontal=True):
                            dpg.add_text(f'@ ExternalAINB[{aref["File Category"]}] {aref["File Path"]}')
                            dpg.add_button(
                                label="Open AINB",
                                #user_data=dest_location,
                                # XXX ideally plumb in ectx
                                callback=lambda: EditContext.get().open_ainb_window(dest_location),
                                arrow=True,
                                direction=dpg.mvDir_Right,
                            )

                        external_ainb_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_MODULE_HUE)
                        dpg.bind_item_theme(f"{node.tag}/Node", external_ainb_theme)
                else:
                    dpg.add_text(f"@ {aj_flag}")


    # TODO lol whats an attachment (runtime node replacement...?)
    # TODO Global/EXB Index, Flags
    # if entry["Node Index"] <= -100 and entry["Node Index"] >= -8192:
    #     entry["Multi Index"] = -100 - entry["Node Index"]
    #     entry["Multi Count"] = entry["Parameter Index"]
    # AI/PhantomGanon.metaai.root.json node 33 is its own precon?
    # TODO Set Pointer Flag Bit Zero, maybe more
    @staticmethod
    def node_param_section(node: AinbGraphEditorNode, param_section: MutableAinbNodeParamSection):
        typed_params: Dict[str, List[Dict]] = param_section.json
        for aj_type, aj_params in typed_params.items():
            i_of_type = -1
            for aj_param in aj_params:
                i_of_type += 1
                # TODO allow editing names, although this will break links? higher level rename for that might be better
                # TODO displaying nulls + ui for nulling values
                param = MutableAinbNodeParam.from_ref(aj_param, node.node_i, param_section.name, aj_type, i_of_type)
                AinbGraphEditorRenderHelpers.node_param_render(node, param)


    @staticmethod
    def node_param_render(node: AinbGraphEditorNode, param: MutableAinbNodeParam):
        # Some dpg inputs (eg int) blow up when given a null, so we awkwardly omit any null arg
        v = param.json.get(param.param_default_name)
        dpg_default_value_kwarg = {"default_value": v} if v is not None else {}

        ui_label = f"{ParamSectionLegend[param.param_section_name]} {param.param_type} {param.i_of_type}: {param.name}"
        op_selector = param.get_default_value_selector()

        def on_edit(sender, data, op_selector):
            # XXX ideally plumb in ectx, or send this up through the editor?
            edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.PARAM_UPDATE_DEFAULT, op_value=data, op_selector=op_selector)
            EditContext.get().perform_new_edit_operation(node.editor.ainb, edit_op)

        node_attr_tag_ns = f"{node.tag}/Params/{param.param_section_name}/{param.name}"
        ui_input_tag = f"{node_attr_tag_ns}/ui_input"
        with dpg.node_attribute(tag=node_attr_tag_ns, parent=f"{node.tag}/Node", attribute_type=ParamSectionDpgAttrType[param.param_section_name]):
            if param.param_section_name == ParamSectionName.OUTPUT:
                # not much to show unless we're planning to execute the graph?
                dpg.add_text(ui_label)

            elif param.param_type == "int":
                dpg.add_input_int(tag=ui_input_tag, label=ui_label, width=80, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
            elif param.param_type == "bool":
                dpg.add_checkbox(tag=ui_input_tag, label=ui_label, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
            elif param.param_type == "float":
                dpg.add_input_float(tag=ui_input_tag, label=ui_label, width=100, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
            elif param.param_type == "string":
                dpg.add_input_text(tag=ui_input_tag, label=ui_label, width=150, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
            elif param.param_type == "vec3f":
                with dpg.group(horizontal=True):
                    dpg.add_drag_floatx(tag=ui_input_tag, label=ui_label, width=300, user_data=op_selector, callback=on_edit, size=3, **dpg_default_value_kwarg)

                    # dpg creates hidden popup windows for every vec3f which don't get cleaned up when the ainb window closes.
                    # It's not worth leaking this much, TODO clean these up
                    """
                    if TitleVersion.get().is_totk:
                        # invisible input that maintains a flipped north/south axis
                        ui_input_inverted = f"{ui_input_tag}/mapviz/inverted"
                        do_map_inversion = lambda d: (d[0], d[1], -1 * d[2], d[3])

                        def on_edit_inverted(sender, data, op_selector):
                            # update real input and send real
                            data = do_map_inversion(data)
                            dpg.set_value(ui_input_tag, data)
                            on_edit(sender, data, op_selector)

                        def on_edit_do_invert(sender, data, op_selector):
                            # update inverted input and send real
                            dpg.set_value(ui_input_inverted, do_map_inversion(data))
                            on_edit(sender, data, op_selector)

                        # Initialize linked inputs
                        dpg.add_drag_floatx(tag=ui_input_tag, label=ui_label, width=300, user_data=op_selector, callback=on_edit_do_invert, size=3, **dpg_default_value_kwarg)
                        dpg.add_drag_floatx(tag=ui_input_inverted, show=False, size=3)
                        dpg.set_value(ui_input_inverted, do_map_inversion(dpg.get_value(ui_input_tag)))

                        # TODO lil map button or globe or something
                        dpg.add_button(label=f"{node_attr_tag_ns}/mapvizbutton", arrow=True, direction=dpg.mvDir_Right)
                        with dpg.popup(dpg.last_item(), mousebutton=dpg.mvMouseButton_Left, min_size=(250, 260), max_size=(250, 260)):
                            dpg.add_3d_slider(
                                tag=f"{node_attr_tag_ns}/mapviz",
                                source=ui_input_inverted,
                                callback=on_edit_inverted,
                                user_data=op_selector,
                                # not desirable, i just don't see how to make the ui render otherwise
                                label="(north-south negated like ingame)",
                                min_x = -6000.0,  # west
                                min_y = -3500.0,  # far down, i dunno
                                min_z = -5000.0,  # north (but shown positive in game+mapviz)
                                max_x = +6000.0,  # east
                                max_y = +3500.0,  # a bit above sky limit?
                                max_z = +5000.0,  # south (but shown negative in game+mapviz)
                            )
                            dpg.add_image(AppStaticTextureKeys.TOTK_MAP_PICKER_250, pos=(0,0))
                    """

            elif param.param_type == "userdefined":
                dpg.add_input_text(tag=ui_input_tag, label=ui_label, width=300, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
            else:
                err_label = f"bruh typo in ur type {param.param_type}"
                dpg.add_text(tag=ui_input_tag, label=err_label, width=300, **dpg_default_value_kwarg)


    @staticmethod
    def link_bidirectional_lookup(node: AinbGraphEditorNode, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
        # XXX idk if its a good name yet, just wanted something simpler for now
        aj_link_type = "Output/bool Input/float Input Link"
        output_attr_links = []

        remote_i = aj_link["Node Index"]
        local_param_name = aj_link["Parameter"]  # May be input or output

        # Find the local param being linked
        local_type = None
        local_param_direction = None  # "Output Parameters" or "Input Parameters"
        local_i_of_type = None
        parameter_index = None
        local_param_node_index = None

        for _local_type, local_params in node.node_json.get("Input Parameters", {}).items():
            for _i_of_type, local_param in enumerate(local_params):
                if local_param["Name"] == local_param_name:
                    local_type = _local_type
                    local_param_direction = "Input Parameters"
                    remote_param_direction = "Output Parameters"
                    local_i_of_type = _i_of_type
                    local_param_node_index = local_param["Node Index"]

                    if local_param_node_index in [-100, -110]:
                        # Always multibool?
                        len_of_nodeparams = local_param["Parameter Index"]  # unused?
                        list_of_nodeparams = local_param["Sources"]
                        for multi_item in list_of_nodeparams:
                            multi_i = multi_item["Node Index"]
                            multi_item_param_name = node.editor.ainb.json["Nodes"][multi_i]["Output Parameters"][local_type][multi_item["Parameter Index"]]["Name"]
                            remote_multi_attr_tag = f"{node.editor.tag}/node{multi_i}/Params/Output Parameters/{multi_item_param_name}"
                            my_attr_tag = f"{node.tag}/Params/Input Parameters/{local_param_name}"
                            output_attr_links.append(DeferredNodeLinkCall(
                                src_attr=remote_multi_attr_tag,
                                dst_attr=my_attr_tag,
                                src_node_i=multi_i,
                                dst_node_i=node.node_i,
                                parent=node.editor.tag,
                            ))
                        return output_attr_links  # Return multi links

                    elif local_param_node_index < 0:
                        # grabbing globals/exb???
                        print(f"Unhandled {local_param_node_index} source node in Input Parameters - {aj_link_type}")
                        return output_attr_links  # TODO Return nothing for now

                    else:
                        if local_param_node_index != remote_i:
                            # FIXME loop+segfault in AI/EquipEventNPC.event.root.ainb, and some Bool business
                            # Unhandled local_param_node_index 269 != remote_i 268
                            print(f"Unhandled local_param_node_index {local_param_node_index} != remote_i {remote_i}")
                            # breakpoint()
                            return output_attr_links # XXX Return nothing? I'm doing something wrong lol, get examples
                        parameter_index = local_param["Parameter Index"]  # can this still be a multi?

        for _local_type, local_params in node.node_json.get("Output Parameters", {}).items():
            for _i_of_type, local_param in enumerate(local_params):
                if local_param["Name"] == local_param_name:
                    local_type = _local_type
                    local_param_direction = "Output Parameters"
                    remote_param_direction = "Input Parameters"
                    local_i_of_type = _i_of_type

        # Remote is the opposite direction
        assert local_type is not None and local_param_direction is not None and local_i_of_type is not None
        remote_type = local_type

        # Resolve whatever the param is called in the remote node, we need this for visually linking to the remote
        remote_param_name = None
        remote_params = node.editor.ainb.json["Nodes"][remote_i].get(remote_param_direction, {}).get(remote_type, [])
        if parameter_index is not None and parameter_index >= len(remote_params):
            # TODO Something from multis leaking, or some other lookup...?
            # FIXME AI/PhantomGanon.metaai.root.ainb, and Bool business
            # off by one? `parameter_index 0 too long for remote_params [] in remote node 78`
            print(f"parameter_index {parameter_index} too long for remote_params {remote_params} in remote node {remote_i}")
        elif parameter_index is not None:
            remote_param = remote_params[parameter_index]
            remote_param_name = remote_param["Name"]
        else:
            for remote_param in remote_params:
                # Pointing to our node?
                if remote_param.get("Node Index") != node.node_i:
                    continue

                # Correct index into per-type param list?
                if remote_param.get("Parameter Index") != local_i_of_type:
                    continue

                remote_param_name = remote_param["Name"]

        my_attr_tag = f"{node.tag}/Params/{local_param_direction}/{local_param_name}"
        if remote_param_name is None and (local_param_node_index or 0) > -1:
            # XXX is this right
            print(f"No remote param found for {my_attr_tag} in {aj_link}")
        else:
            remote_attr_tag = f"{node.editor.tag}/node{remote_i}/Params/{remote_param_direction}/{remote_param_name}"

            # XXX is there anything more for when flags are precon, or was I just confused again
            if local_param_direction == "Output Parameters":
                output_attr_links.append(DeferredNodeLinkCall(
                    src_attr=my_attr_tag,
                    dst_attr=remote_attr_tag,
                    src_node_i=node.node_i,
                    dst_node_i=remote_i,
                    parent=node.editor.tag
                ))
            else:
                output_attr_links.append(DeferredNodeLinkCall(
                    src_attr=remote_attr_tag,
                    dst_attr=my_attr_tag,
                    src_node_i=remote_i,
                    dst_node_i=node.node_i,
                    parent=node.editor.tag
                ))
        return output_attr_links


    @staticmethod
    def link_standard(node: AinbGraphEditorNode, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
        aj_link_type = "Standard Link"
        output_attr_links = []

        # refs to entire nodes for stuff like simultaneous, selectors.
        # make new node attributes to support links to children.
        dst_i = aj_link["Node Index"]
        my_attr_tag = f"{node.tag}/stdlink{i_of_link_type}"
        dst_attr_tag = f"{node.editor.tag}/node{dst_i}/LinkTarget"

        with dpg.node_attribute(tag=my_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
            labels = []
            if cname := aj_link.get("Connection Name"):
                labels.append(cname)
            if cond := aj_link.get("Condition"):
                labels.append(f"Condition: {cond}")
            label = ", ".join(labels) or f"[{aj_link_type}]"
            dpg.add_text(label)

        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=my_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=node.node_i,
            dst_node_i=dst_i,
            parent=node.editor.tag
        ))
        return output_attr_links


    @staticmethod
    def link_resident_update(node: AinbGraphEditorNode, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
        aj_link_type = "Resident Update Link"
        output_attr_links = []

        # pointers to params owned by other nodes? idk
        # pulling in references to other nodes? idk
        dst_i = aj_link["Node Index"]
        my_attr_tag = f"{node.tag}/reslink{i_of_link_type}"

        # print(aj_link)

        dst_attr_tag = f"{node.editor.tag}/node{dst_i}/LinkTarget" # TODO learn some things
        # if dst_param_name := aj_link["Update Info"].get("String"):
        #     # dst_attr_tag = f"{node.editor.tag}/node{dst_i}/Params/Input Parameters/{dst_param_name}"
        #     # I don't understand how this String works, just point to the node for now.
        #     dst_attr_tag = f"{node.editor.tag}/node{dst_i}/LinkTarget"
        # else:
        #     # Pointing into things like Element_Sequential or UDT @Is External AINB
        #     # seem to not specify a String, so we'll just point at the node itself until
        #     # this default/lhs/internal/??? param is better understood.
        #     # The ResUpdate flags usually include "Is Valid Update" when this happens.
        #     dst_attr_tag = f"{node.editor.tag}/node{dst_i}/LinkTarget"

        with dpg.node_attribute(tag=my_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
            flags = aj_link["Update Info"]["Flags"]
            flags = "|".join((" ".join(flags)).split())  # bad ainb parse?
            label = f"[ResUpdate] ({flags})" if flags else "[ResUpdate]"
            dpg.add_text(label)

        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=my_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=node.node_i,
            dst_node_i=dst_i,
            parent=node.editor.tag
        ))
        return output_attr_links
