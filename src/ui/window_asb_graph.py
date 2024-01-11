from __future__ import annotations
from datetime import datetime
import functools
import pathlib
from typing import *
from collections import defaultdict

import dearpygui.dearpygui as dpg
import orjson

from ..app_ainb_cache import scoped_pack_lookup
from ..edit_context import EditContext
from ..mutable_asb import MutableAsb, MutableAsbNodeParam, MutableAsbTransition
from .. import db, pack_util
from ..app_types import *


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
def make_node_theme_for_hue(hue: AppColor) -> DpgTag:
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(dpg.mvNodeCol_TitleBar, hue.set_hsv(s=0.5, v=0.4).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_TitleBarHovered, hue.set_hsv(s=0.5, v=0.5).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_TitleBarSelected, hue.set_hsv(s=0.4, v=0.55).to_rgb24(), category=dpg.mvThemeCat_Nodes)

            dpg.add_theme_color(dpg.mvNodeCol_NodeBackground, hue.set_hsv(s=0.15, v=0.3).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundHovered, hue.set_hsv(s=0.1, v=0.35).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundSelected, hue.set_hsv(s=0.1, v=0.35).to_rgb24(), category=dpg.mvThemeCat_Nodes)
    return theme


class WindowAsbGraph:
    def __init__(self, asb_location: PackIndexEntry, ectx: EditContext):
        print(f"Opening {asb_location.fullfile}")
        self.ectx = ectx
        self.asb = self.ectx.load_asb(asb_location)

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
        _AS, asbfile = pathlib.Path(self.asb.location.internalfile).parts
        if self.asb.location.packfile == "Root":
            window_label = f"[{_AS}] {asbfile}"
        else:
            window_label = f"[{_AS}] {asbfile} [from {self.asb.location.packfile}]"

        self.tag = dpg.add_window(
            label=window_label,
            on_close=lambda: self.ectx.close_file_window(self.asb.location),
            **window_kwargs,
        )
        self.render_contents()
        return self.tag

    def redump_json_textbox(self):
        # Replace json textbox with working asb (possibly dirty)
        asb_json_str = orjson.dumps(self.asb.json, option=orjson.OPT_INDENT_2)
        # yep. this lib only supports 2 spaces, but fast + keeps unicode strings unescaped
        if True: # if dpg.get_value(AppConfigKeys.INDENT_4):
            asb_json_str = '\n'.join([
                ' '*(((len(line) - len(line.lstrip(' '))) // 2) * 4) + line.lstrip(' ')
                for line in asb_json_str.decode("utf8").split('\n')
            ])
        dpg.set_value(self.json_textbox, asb_json_str)

    def rerender_graph_from_json(self):
        user_json_str = dpg.get_value(self.json_textbox)

        # Send event to edit ctx
        edit_op = AsbEditOperation(op_type=AsbEditOperationTypes.REPLACE_JSON, op_value=user_json_str)
        self.ectx.perform_new_asb_edit_operation(self.asb, edit_op)

        # Re-render editor TODO this belongs in AsbGraphEditor?
        dpg.delete_item(self.node_editor)
        dpg.delete_item(f"{self.node_editor}/toolbar")
        self.editor.render_contents()

    def rerender_history(self):
        dpg.delete_item(self.history_entries_tag, children_only=True)
        # history is stored+appended with time asc, but displayed with time desc
        for edit_op in reversed(self.ectx.edit_histories.get(self.asb.location.fullfile, [])):
            with dpg.group(parent=self.history_entries_tag):
                with dpg.group():
                    selector = f"@ {edit_op.op_selector}" if edit_op.op_selector else ""
                    dpg.add_text(f"{prettydate(edit_op.when)}: {edit_op.op_type} {selector}")
                    dpg.add_text(str(edit_op.op_value))
                    dpg.add_separator()

    def render_contents(self):
        def _tab_change(sender, data, user_data):
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
                    self.editor = AsbGraphEditor.create(tag=self.node_editor, parent=graph_window, asb=self.asb)

            with dpg.tab(tag=f"{self.tag}/tabs/json", label="Parsed JSON"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    with dpg.group(horizontal=True):
                        #dpg.add_button(label="Refresh JSON", callback=self.redump_json_textbox)
                        #dpg.add_checkbox(label="(Always refresh)", tag=f"{self.tag}/tabs/json/autodump", default_value=True)
                        dpg.add_button(label="Apply Changes", callback=self.rerender_graph_from_json)
                        #      dpg.add_button(label="Overwrite ASB") duh
                        #      dpg.add_button(label="Open JSON in: ", source="jsdfl/opencmd")
                        #      dpg.add_input_text(default_value='$EDITOR "%s"', tag="jsdfl/opencmd")
                    dpg.add_input_text(tag=self.json_textbox, default_value="any slow dumps?", width=-1, height=-1, multiline=True, tab_input=True, readonly=False)
                    self.redump_json_textbox()

            with dpg.tab(tag=f"{self.tag}/tabs/history", label="Edit History"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    dpg.add_group(tag=self.history_entries_tag)
                    self.rerender_history()

            save_asb = lambda: self.ectx.save_asb(self.asb)
            dpg.add_tab_button(label="Save to modfs", callback=save_asb)


class AsbGraphEditor:
    @classmethod
    def create(cls, tag: DpgTag, parent: DpgTag, asb: MutableAsb) -> AsbGraphEditor:
        editor = cls(tag=tag, parent=parent)
        editor.set_asb(asb)
        return editor

    def __init__(self, tag: DpgTag, parent: DpgTag):
        self.tag = tag
        self.parent = parent

    def set_asb(self, asb: MutableAsb) -> None:
        self.asb = asb
        # TODO clear contents?
        self.render_contents()

    @property
    def _add_node_tag(self) -> DpgTag:
        return f"{self.tag}/AddNode/Window"

    def begin_add_node(self, sender, _data, _user_data):
        input_tag = f"{self._add_node_tag}/Input"
        dpg.delete_item(self._add_node_tag)
        with dpg.window(
            tag=self._add_node_tag,
            min_size=(1024, 768),
            max_size=(1024, 768),
            popup=True,  # XXX neither autosize nor no_resize seem to do anything here?
        ):
            dpg.add_text("TODO LOL")

    def render_contents(self):
        # sludge for now
        def _link_callback(sender, app_data):
            dpg.add_node_link(app_data[0], app_data[1], parent=sender)
        def _delink_callback(sender, app_data):
            dpg.delete_item(app_data)

        # TODO top bar, might replace tabs?
        # - "jump to" node list dropdown, command dropdown, transition dropdown, ...
        # - dirty indicators
        # - "{}" json button?
        with dpg.group(tag=f"{self.tag}/toolbar", horizontal=True, parent=self.parent):
            dpg.add_button(label=f"Add Node", callback=self.begin_add_node)

        # Main graph ui + rendering nodes
        dpg.add_node_editor(
            tag=self.tag,
            parent=self.parent,
            callback=_link_callback,
            delink_callback=_delink_callback,
            minimap=True,
            minimap_location=dpg.mvNodeMiniMap_Location_BottomRight
        )

        self.preprocess_transitions()
        self.render_asb_nodes()

    def preprocess_transitions(self):
        self.command_to_transition_membership: Dict[str, List[MutableAsbTransition]] = defaultdict(list)
        aj = self.asb.json  # asb json. we still call him aj
        for (i, tsection) in enumerate(aj.get("Transitions", [])):
            assert tsection["Unknown"] == -1  # what is this and why are we in sections
            for j, transition in enumerate(tsection.get("Transitions", [])):
                trans = MutableAsbTransition.from_ref(i, j, transition)
                # XXX assuming "" means any?
                self.command_to_transition_membership[trans.json["Command 1"]].append(trans)
                self.command_to_transition_membership[trans.json["Command 2"]].append(trans)

    def render_asb_nodes(self):
        aj = self.asb.json  # asb json. we still call him aj

        # Render globals as a type of node? Not sure if dumb, we do need to link/associate globals into nodes anyways somehow
        if mutable_globals_section := self.asb.get_global_param_section():
            globals_node = AsbGraphEditorGlobalsNode(editor=self, section=mutable_globals_section)
            globals_node.render()

        graph_nodes = [
            AsbGraphEditorNode(editor=self, node=self.asb.get_node_i(i))
            for i in range(self.asb.get_node_len())
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
        for command_i in range(self.asb.get_command_len()):
            command = self.asb.get_command_i(command_i)
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


class AsbGraphEditorNode:
    def __init__(self, editor: AsbGraphEditor, node: MutableAsbNode):
        self.editor = editor
        self.node = node

    @property
    def node_i(self) -> int:
        return self.node.json["Node Index"]

    @property
    def node_json(self) -> dict:
        return self.node.json

    @property
    def node_type(self) -> str:
        return self.node_json["Node Type"]

    @property
    def tag(self) -> DpgTag:
        return f"{self.editor.tag}/node{self.node_i}"

    def render(self) -> List[DeferredNodeLinkCall]:
        output_attr_links: List[DeferredNodeLinkCall] = []
        label = f"{self.node_type} ({self.node_i})"

        rh = AsbGraphEditorRenderHelpers
        with dpg.node(tag=f"{self.tag}/Node", label=label, parent=self.editor.tag):
            rh.node_topmeta(self)
            # if section := self.node.get_param_section(ParamSectionName.IMMEDIATE):
            #     rh.node_param_section(self, section)
            # if section := self.node.get_param_section(ParamSectionName.INPUT):
            #     rh.node_param_section(self, section)
            # if section := self.node.get_param_section(ParamSectionName.OUTPUT):
            #     rh.node_param_section(self, section)

            # for aj_link_type, aj_links in self.node_json.get("Linked Nodes", {}).items():
            #     for i_of_link_type, aj_link in enumerate(aj_links):
            #         if aj_link_type == "Output/bool Input/float Input Link": # 0
            #             output_attr_links += rh.link_bidirectional_lookup(self, aj_link, i_of_link_type)
            #         elif aj_link_type == "Standard Link": # 2
            #             output_attr_links += rh.link_standard(self, aj_link, i_of_link_type)
            #         elif aj_link_type == "Resident Update Link": # 3
            #             output_attr_links += rh.link_resident_update(self, aj_link, i_of_link_type)
            #         elif aj_link_type == "String Input Link": # 4
            #             output_attr_links += rh.link_string_input(self, aj_link, i_of_link_type)
            #         elif aj_link_type == "int Input Link": # 5
            #             output_attr_links += rh.link_int_input(self, aj_link, i_of_link_type)
            #         else:
            #             print(f"Unsupported link type {aj_link_type}")
            #             breakpoint()
            #             continue

        return output_attr_links


class AsbGraphEditorGlobalsNode(AsbGraphEditorNode):
    def __init__(self, editor: AsbGraphEditor, section: MutableAsbNodeParamSection):
        self.editor = editor
        self.section = section

    @property
    def node_i(self) -> int:
        return -420  # lol

    @property
    def node_json(self) -> dict:
        return self.editor.asb.json

    @property
    def tag(self) -> DpgTag:
        return f"{self.editor.tag}/Globals"

    def render(self):
        globals_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_GLOBALS_HUE)
        with dpg.node(tag=f"{self.tag}/Node", label=ParamSectionName.GLOBAL, parent=self.editor.tag):
            AsbGraphEditorRenderHelpers.node_param_section(self, self.section)
        dpg.bind_item_theme(f"{self.tag}/Node", globals_node_theme)


class AsbGraphEditorRenderHelpers:
    @staticmethod
    def node_topmeta(node: AsbGraphEditorNode) -> None:
        with dpg.node_attribute(tag=f"{node.tag}/LinkTarget", attribute_type=dpg.mvNode_Attr_Input):
            # TODO editor.commands: List[AsbGraphEditorCommand]
            # editor.get_command_json(name: str) -> dict
            for command_i, command in enumerate(node.editor.asb.json.get("Commands", [])):
                if node.node_i == command["Left Node Index"]:
                    cmd_name = command["Name"]
                    dpg.add_text(f"@ Command[{cmd_name}]")
                    for aj_flag in command.get("Tags", []):
                        dpg.add_text(f"@ {aj_flag}")

                    transitions_by_name = node.editor.command_to_transition_membership[cmd_name]
                    transitions_wildcard = node.editor.command_to_transition_membership[""]
                    transitions_count = len(transitions_by_name) + len(transitions_wildcard)
                    if transitions_count:
                        transitions_items = [f"Transitions [{transitions_count}]"]
                        if transitions_by_name:
                            transitions_items.append(f"[{len(transitions_by_name)} Named]")
                            for t in transitions_by_name:
                                tj = t.json
                                exclusive = "Exclusive, " if tj["Allow Multiple Matches"] == False else ""
                                tstr = f"{tj['Command 1'] or '*'} -> {tj['Command 2'] or '*'} ({exclusive}SetParam {tj['Parameter']}={tj['Value']})"
                                transitions_items.append(tstr)
                        if transitions_wildcard:
                            transitions_items.append(f"[{len(transitions_wildcard)} Wildcard]")
                            for t in transitions_wildcard:
                                tj = t.json
                                # FIXME named are duplicated in this section. continue+decrement if tj["Command 1 or 2"] == cmd_name?
                                # FIXME * -> * are duplicated. sets of id()s? idk not hard
                                exclusive = "Exclusive, " if tj["Allow Multiple Matches"] == False else ""
                                tstr = f"{tj['Command 1'] or '*'} -> {tj['Command 2'] or '*'} ({exclusive}SetParam {tj['Parameter']}={tj['Value']})"
                                transitions_items.append(tstr)
                        dpg.add_combo(items=transitions_items, default_value=transitions_items[0], width=300)

                    command_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_COMMAND_HUE)
                    dpg.bind_item_theme(f"{node.tag}/Node", command_node_theme)


            for aj_flag in node.node_json.get("Tags", []):
                dpg.add_text(f"@ {aj_flag}")

            dpg.add_text("TODO LOL")


    @staticmethod
    def node_param_section(node: AsbGraphEditorNode, param_section: MutableAsbNodeParamSection):
        typed_params: Dict[str, List[Dict]] = param_section.json
        for aj_type, aj_params in typed_params.items():
            i_of_type = -1
            for aj_param in aj_params:
                i_of_type += 1
                # TODO allow editing names, although this will break links? higher level rename for that might be better
                # TODO displaying nulls + ui for nulling values
                param = MutableAsbNodeParam.from_ref(aj_param, node.node_i, param_section.name, aj_type, i_of_type)
                AsbGraphEditorRenderHelpers.node_param_render(node, param)


    @staticmethod
    def node_param_render(node: AsbGraphEditorNode, param: MutableAsbNodeParam):
        # Some dpg inputs (eg int) blow up when given a null, so we awkwardly omit any null arg
        v = param.json.get(param.param_default_name)
        dpg_default_value_kwarg = {"default_value": v} if v is not None else {}

        ui_label = f"$ {param.param_type} {param.i_of_type}: {param.name}"  # XXX only asb blackboard, no node params?
        op_selector = param.get_default_value_selector()

        def on_edit(sender, data, op_selector):
            # XXX ideally plumb in ectx, or send this up through the editor?
            edit_op = AsbEditOperation(op_type=AsbEditOperationTypes.PARAM_UPDATE_DEFAULT, op_value=data, op_selector=op_selector)
            EditContext.get().perform_new_asb_edit_operation(node.editor.asb, edit_op)

        node_attr_tag_ns = f"{node.tag}/Params/{param.param_section_name}/{param.name}"
        ui_input_tag = f"{node_attr_tag_ns}/ui_input"
        with dpg.node_attribute(tag=node_attr_tag_ns, parent=f"{node.tag}/Node", attribute_type=dpg.mvNode_Attr_Output):
            if param.param_type == "int":
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
            elif param.param_type == "userdefined":
                dpg.add_input_text(tag=ui_input_tag, label=ui_label, width=300, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
            else:
                err_label = f"bruh typo in ur type {param.param_type}"
                dpg.add_text(tag=ui_input_tag, label=err_label, width=300, **dpg_default_value_kwarg)
