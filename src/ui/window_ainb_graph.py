from __future__ import annotations
from datetime import datetime
import functools
import pathlib
from typing import *
from collections import defaultdict

from .. import curio
import dearpygui.dearpygui as dpg
# deferred import graphviz
import orjson

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


class AinbGraphLayout:
    layout_data: dict = None
    inflight_dot: "graphviz.Digraph" = None
    inflight_nodes: dict = None
    location: PackIndexEntry = None
    insist_stinky: bool = False  # use old layout

    @property
    def has_layout(self) -> bool:
        return self.layout_data is not None

    @staticmethod
    @functools.cache
    def is_graphviz_enabled() -> bool:
        try:
            import graphviz
            return True
        except ImportError:
            return False

    @classmethod
    def try_get_cached_layout(cls, location: PackIndexEntry) -> "AinbGraphLayout":
        # if layout_data := db.TODOLayoutCache.get_by_fullfile(location.fullfile):
        #     return cls(location, layout_data)
        return cls(location)

    def __init__(self, location: PackIndexEntry, layout_data: dict = None):
        self.location = location
        self.layout_data = layout_data
        if not self.has_layout and self.is_graphviz_enabled():
            # begin building new layout
            import graphviz
            self.inflight_nodes ={}
            self.inflight_dot = graphviz.Digraph(
                "hi", #data["Info"]["Filename"],
                graph_attr={"rankdir": "LR"},
                node_attr={"fontsize": "16", "fixedsize": "true", "shape": "box"}
            )

    def maybe_dot_node(self, i: int, node_tag: DpgTag):
        if self.has_layout or not self.is_graphviz_enabled():
            return
        self.inflight_nodes[i] = node_tag

    def maybe_dot_edge(self, src_i: int, dst_i: int):
        if self.has_layout or not self.is_graphviz_enabled():
            return
        self.inflight_dot.edge(str(src_i), str(dst_i))

    async def finalize(self):
        if self.has_layout or not self.is_graphviz_enabled():
            return

        # TODO reimplement "after next frame" wait
        await curio.sleep(0.1)  # wait for dpg so we can see rendered node dimensions

        # Defer maybe_dot_node operations until here
        for node_i, tag in self.inflight_nodes.items():
            w, h = dpg.get_item_state(tag)["rect_size"]
            w = str(w / 50)
            h = str(h / 50)
            # print(w, h)
            self.inflight_dot.node(str(node_i), label=str(node_i), width=w, height=h)

        graphdump = orjson.loads(self.inflight_dot.pipe("json"))
        out = {}
        for obj in graphdump.get("objects", []):
            node_index = int(obj["name"])
            x, y = obj["pos"].split(",")
            x, y = int(float(x)), -1 * int(float(y))
            out[node_index] = x, y

        # TODO persist layout queryable by i+command? Dict[i|str, vec2i] but i should be fine
        # Persist separate per-graph xy translation for "panning" just like stinky did it
        self.layout_data = out

        # persist svg
        if _do_svg_persist := True:
            appvar = dpg.get_value(AppConfigKeys.APPVAR_PATH)
            title_version = dpg.get_value(AppConfigKeys.TITLE_VERSION)
            svgfile = self.location.internalfile+".svg"
            svgfile = f"{appvar}/{title_version}/svgtmp/{svgfile}"
            pathlib.Path(svgfile).parent.mkdir(parents=True, exist_ok=True)
            self.inflight_dot.render(outfile=svgfile, format="svg", cleanup=True)
            #print(f"Debug graphviz layout {svgfile}")

        self.inflight_dot = None
        self.inflight_nodes = None

    def get_node_indexes_with_layout(self) -> List[int]:
        if not self.has_layout:
            return []
        return list(self.layout_data.keys())

    def get_node_coordinates(self, i: int, default=(0, 0)) -> Tuple[int, int]:
        if not self.has_layout:
            return default
        return self.layout_data.get(i, default)


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

    async def create_as_coro(self, **window_kwargs) -> None:
        await self.create(**window_kwargs)
        while True:
            # ectx owns, we run this instance and its ui
            await curio.sleep(69)

    async def create(self, **window_kwargs) -> DpgTag:
        category, ainbfile = pathlib.Path(self.ainb.location.internalfile).parts
        if self.ainb.location.packfile == "Root":
            window_label = f"[{category}] {ainbfile}"
        else:
            window_label = f"[{category}] {ainbfile} [from {self.ainb.location.packfile}]"

        self.tag = dpg.add_window(
            label=window_label,
            on_close=lambda: self.ectx.close_file_window(self.ainb.location),
            **window_kwargs,
        )
        await self.render_contents()
        return self.tag

    async def redump_json_textbox(self):
        # Replace json textbox with working ainb (possibly dirty)
        ainb_json_str = orjson.dumps(self.ainb.json, option=orjson.OPT_INDENT_2)
        # yep. this lib only supports 2 spaces, but fast + keeps unicode strings unescaped
        if True: # if dpg.get_value(AppConfigKeys.INDENT_4):
            ainb_json_str = '\n'.join([
                ' '*(((len(line) - len(line.lstrip(' '))) // 2) * 4) + line.lstrip(' ')
                for line in ainb_json_str.decode("utf8").split('\n')
            ])
        dpg.set_value(self.json_textbox, ainb_json_str)

    def rerender_graph_from_json(self):
        user_json_str = dpg.get_value(self.json_textbox)

        # FIXME route through callback?
        """
        # Send event to edit ctx
        edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.REPLACE_JSON, op_value=user_json_str)
        self.ectx.perform_new_ainb_edit_operation(self.ainb, edit_op)

        # Re-render editor TODO this belongs in AinbGraphEditor?
        dpg.delete_item(self.node_editor)
        dpg.delete_item(f"{self.node_editor}/toolbar")
        self.editor.render_contents()
        """
        # FIXME await self.editor.render_contents()

    async def rerender_history(self):
        dpg.delete_item(self.history_entries_tag, children_only=True)
        # history is stored+appended with time asc, but displayed with time desc
        for edit_op in reversed(self.ectx.edit_histories.get(self.ainb.location.fullfile, [])):
            with dpg.group(parent=self.history_entries_tag):
                with dpg.group():
                    selector = f"@ {edit_op.op_selector}" if edit_op.op_selector else ""
                    dpg.add_text(f"{prettydate(edit_op.when)}: {edit_op.op_type} {selector}")
                    dpg.add_text(str(edit_op.op_value))
                    dpg.add_separator()

    async def render_contents(self):
        def _tab_change(sender, data, user_data):
            # FIXME async callback
            """
            entered_tab = dpg.get_item_alias(data)
            is_autodump = True  # dpg.get_value(f"{self.tag}/tabs/json/autodump")
            if entered_tab == f"{self.tag}/tabs/json" and is_autodump:
                await self.redump_json_textbox()
            if entered_tab == f"{self.tag}/tabs/history" and is_autodump:
                await self.rerender_history()
            """

        with dpg.tab_bar(tag=f"{self.tag}/tabs", parent=self.tag, callback=_tab_change):
            # dpg.add_tab_button(label="[max]", callback=dpg.maximize_viewport)  # works at runtime, fails at init?
            # dpg.add_tab_button(label="wipe cache")
            with dpg.tab(tag=f"{self.tag}/tabs/graph", label="Node Graph"):
                with dpg.child_window(autosize_x=True, autosize_y=True) as graph_window:
                    self.editor = await AinbGraphEditor.create(tag=self.node_editor, parent=graph_window, ainb=self.ainb)

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
                    await self.redump_json_textbox()

            with dpg.tab(tag=f"{self.tag}/tabs/history", label="Edit History"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    dpg.add_group(tag=self.history_entries_tag)
                    await self.rerender_history()

            save_ainb = lambda: self.ectx.save_ainb(self.ainb)
            dpg.add_tab_button(label="Save to modfs", callback=save_ainb)


class AinbGraphEditor:
    @classmethod
    async def create(cls, tag: DpgTag, parent: DpgTag, ainb: MutableAinb) -> AinbGraphEditor:
        editor = cls(tag=tag, parent=parent)
        await editor.set_ainb(ainb)
        return editor

    def __init__(self, tag: DpgTag, parent: DpgTag):
        self.tag = tag
        self.parent = parent

    async def set_ainb(self, ainb: MutableAinb) -> None:
        self.ainb = ainb
        # TODO clear contents?
        self.layout = AinbGraphLayout.try_get_cached_layout(self.ainb.location)
        await self.render_contents()

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
            # Get usages to present to user
            file_cat = self.ainb.json["Info"]["File Category"]
            node_usages = db.AinbFileNodeUsageIndex.get_node_types(db.Connection.get(), file_cat)

            # Set up filtering
            filter_ns = f"{self._add_node_tag}/Filter"
            def set_filters(sender, filter_string, _user_data):
                if len(filter_string) < 3:
                    filter_string = ""
                dpg.set_value(f"{filter_ns}/builtin", filter_string)
                dpg.set_value(f"{filter_ns}/userdefined", filter_string)
                dpg.set_value(f"{filter_ns}/module", filter_string)
            dpg.add_input_text(tag=input_tag, hint="Node Type...", callback=set_filters)

            # Output containers for filtered node types
            with dpg.child_window(horizontal_scrollbar=True):
                dpg.add_separator()
                dpg.add_text("Builtins (Element_)", color=AppStyleColors.LIST_ENTRY_SEPARATOR.to_rgb24())
                dpg.add_separator()
                dpg.add_filter_set(tag=f"{filter_ns}/builtin")

                dpg.add_separator()
                dpg.add_text(f"UserDefined (for {file_cat})", color=AppStyleColors.LIST_ENTRY_SEPARATOR.to_rgb24())
                dpg.add_separator()
                dpg.add_filter_set(tag=f"{filter_ns}/userdefined")

                dpg.add_separator()
                dpg.add_text(f"External AINB (.module for {file_cat})", color=AppStyleColors.LIST_ENTRY_SEPARATOR.to_rgb24())
                dpg.add_separator()
                dpg.add_filter_set(tag=f"{filter_ns}/module")

            def on_submit_node(sender, data, user_data):
                dpg.delete_item(self._add_node_tag)
                (node_type, param_details_json) = user_data

                # XXX how much of this even belongs in here?
                # FIXME add ainb-level header for this module
                flags_kw = {}
                if node_type.endswith(".module"):
                    flags_kw["Flags"] = ["Is External AINB"]

                # Skeleton node json
                data = {
                    "Node Type": node_type if node_type.startswith("Element_") else "UserDefined",
                    "Node Index": None,  # Assigned at AinbEditOperation runtime
                    **flags_kw,  # "Flags": ["Is Precondition Node"]
                    "Name": "" if node_type.startswith("Element_") else node_type,
                    "Base Precondition Node": 0,  # Required?
                    "GUID": None,
                    # "Precondition Nodes": [2],
                    **param_details_json,
                    # "Linked Nodes": {},
                }
                # XXX ideally plumb in ectx, or send this up through the editor?
                edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.ADD_NODE, op_value=data)
                EditContext.get().perform_new_ainb_edit_operation(self.ainb, edit_op)

                # Re-render editor TODO this belongs in AinbGraphEditor?
                dpg.delete_item(self.tag)
                dpg.delete_item(f"{self.tag}/toolbar")
                self.render_contents()

            # Populate containers with all possible results
            for (node_type, param_details_json) in node_usages:
                if node_type.startswith("Element_"):  # builtins
                    parent = f"{filter_ns}/builtin"
                elif node_type.endswith(".module"):  # modules / external ainb
                    parent = f"{filter_ns}/module"
                else:  # userdefined
                    parent = f"{filter_ns}/userdefined"

                with dpg.group(horizontal=True, parent=parent, filter_key=node_type):
                    # color = AppStyleColors.GRAPH_MODULE_HUE.set_hsv(s=0.2, v=1.0)
                    # type_color_kw["color"] = color.to_rgb24()
                    # dpg.add_text(node_type, **type_color_kw)
                    dpg.add_button(label=node_type, user_data=(node_type, param_details_json), callback=on_submit_node)

                    with dpg.group(horizontal=False):
                        if False: #comment := "hola pendejo":
                            dpg.add_text(f"// {comment}", color=AppStyleColors.INLINE_COMMENT_TEXT.to_rgb24())
                        else:
                            dpg.add_text("")
                        for section, typed_params in param_details_json.items():
                            param_names = ", ".join([
                                f"{param_type}: [{', '.join([p['Name'] for p in param_list])}]"
                                for (param_type, param_list) in typed_params.items()
                            ])
                            dpg.add_text(f"{ParamSectionLegend[section]} {param_names}", color=AppStyleColors.NEW_NODE_PICKER_PARAM_DETAILS.to_rgb24())

        dpg.focus_item(input_tag)  # XXX inconsistent bullshit, this just uhh stopped working again :(

    async def render_contents(self):
        # sludge for now
        def _link_callback(sender, app_data):
            dpg.add_node_link(app_data[0], app_data[1], parent=sender)
        def _delink_callback(sender, app_data):
            dpg.delete_item(app_data)

        # TODO top bar, might replace tabs?
        # - "jump to" node list dropdown
        # - dirty indicators
        # - "{}" json button?
        def rerender_stinky():
            self.layout.insist_stinky = not self.layout.insist_stinky
            # FIXME async callback: await self.render_contents()
            """
            # Re-render editor TODO this belongs in AinbGraphEditor?
            dpg.delete_item(self.tag)
            dpg.delete_item(f"{self.tag}/toolbar")
            self.render_contents()
            """
        with dpg.group(tag=f"{self.tag}/toolbar", horizontal=True, parent=self.parent):
            dpg.add_button(label=f"Add Node", callback=self.begin_add_node)
            dpg.add_button(label=f"Stinky {self.layout.insist_stinky}", callback=rerender_stinky)

        # Main graph ui + rendering nodes
        dpg.add_node_editor(
            tag=self.tag,
            parent=self.parent,
            callback=_link_callback,
            delink_callback=_delink_callback,
            minimap=True,
            minimap_location=dpg.mvNodeMiniMap_Location_BottomRight
        )

        await self.render_ainb_nodes()

    async def render_ainb_nodes(self):
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
        await self.render_links_and_layout(deferred_link_calls)

    async def render_links_and_layout(self, link_calls: List[DeferredNodeLinkCall]):
        await self.layout.finalize()

        # Add links
        node_i_links = defaultdict(set)
        for link in link_calls:
            # print(link, flush=True)
            # breakpoint()
            dpg.add_node_link(link.src_attr, link.dst_attr, parent=link.parent)
            node_i_links[link.src_node_i].add(link.dst_node_i)

        if self.layout.is_graphviz_enabled() and not self.layout.insist_stinky:
            for node_i in self.layout.get_node_indexes_with_layout():
                node_tag = f"{self.tag}/node{node_i}/Node"
                pos = self.layout.get_node_coordinates(node_i)
                # print(node_tag, pos)
                dpg.set_item_pos(node_tag, pos)

            return  # no stinky

        #
        # XXX STINKY OLD LAYOUT XXX
        #

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
    def node_type(self) -> str:
        node_type = self.node_json["Node Type"]
        if node_type == "UserDefined":
            return self.node_json["Name"]
        return node_type

    @property
    def tag(self) -> DpgTag:
        # TODO AinbGraphEditor.get_node_json(i) instead?
        return f"{self.editor.tag}/node{self.node_i}"

    def render(self) -> List[DeferredNodeLinkCall]:
        output_attr_links: List[DeferredNodeLinkCall] = []
        label = f"{self.node_type} ({self.node_i})"

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
                    if aj_link_type == "Output/bool Input/float Input Link": # 0
                        output_attr_links += rh.link_bidirectional_lookup(self, aj_link, i_of_link_type)
                    elif aj_link_type == "Standard Link": # 2
                        output_attr_links += rh.link_standard(self, aj_link, i_of_link_type)
                    elif aj_link_type == "Resident Update Link": # 3
                        output_attr_links += rh.link_resident_update(self, aj_link, i_of_link_type)
                    elif aj_link_type == "String Input Link": # 4
                        output_attr_links += rh.link_string_input(self, aj_link, i_of_link_type)
                    elif aj_link_type == "int Input Link": # 5
                        output_attr_links += rh.link_int_input(self, aj_link, i_of_link_type)
                    else:
                        print(f"Unsupported link type {aj_link_type}")
                        breakpoint()
                        continue

        # Accumulate graphviz operations
        self.editor.layout.maybe_dot_node(self.node_i, f"{self.tag}/Node")
        for link in output_attr_links:
            self.editor.layout.maybe_dot_edge(link.src_node_i, link.dst_node_i)

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
                        dest_location = scoped_pack_lookup(PackIndexEntry(internalfile=dest_ainbfile, packfile=node.editor.ainb.location.packfile, extension=RomfsFileTypes.AINB))
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
            EditContext.get().perform_new_ainb_edit_operation(node.editor.ainb, edit_op)

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

                    if local_param_node_index <= -100:
                        # Always multibool?
                        # local_param["Parameter Index"] # Always 2?
                        list_of_nodeparams = local_param["Sources"]
                        for multi_item in list_of_nodeparams:
                            if multi_item.get("Function"):
                                # FIXME traverse links to figure out the datatype (needed to use Parameter Index)?
                                print(f"ignoring exb source in {node.node_type} {node.node_i}")
                                continue
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
            if note := aj_link.get("その他"):  # "Others"?
                labels.append(note)  # Contains "Default"?
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


    @staticmethod
    def link_string_input(node: AinbGraphEditorNode, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
        output_attr_links = []

        # The link info exists on the destination `node`, so the source is "remote"
        remote_src_node_i: int = aj_link["Node Index"]
        dst_param_name: str = aj_link["Parameter"]
        dst_attr_tag: DpgTag = f"{node.tag}/Params/Input Parameters/{dst_param_name}"

        # We need to find the remote node's param index, to get that remote param's name, used to visually link.
        # This param index is stored on the local param. The link info itself only locates the local/destination name and remote/source *node index*.
        remote_param_i: int = None
        for local_param in node.node_json[ParamSectionName.INPUT]["string"]:
            # idk why we have both of these, but may as well check both
            if local_param["Name"] != dst_param_name:
                continue
            if local_param["Node Index"] != remote_src_node_i:
                continue

            remote_param_i = local_param["Parameter Index"]
            break

        if remote_param_i is None:
            print(f"No remote param found for {dst_attr_tag} in {aj_link}")

        remote_node_json = node.editor.ainb.json["Nodes"][remote_src_node_i]
        remote_src_param_name = remote_node_json[ParamSectionName.OUTPUT]["string"][remote_param_i]["Name"]

        src_attr_tag: DpgTag = f"{node.editor.tag}/node{remote_src_node_i}/Params/Output Parameters/{remote_src_param_name}"
        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=src_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=remote_src_node_i,
            dst_node_i=node.node_i,
            parent=node.editor.tag
        ))
        return output_attr_links


    @staticmethod
    def link_int_input(node: AinbGraphEditorNode, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
        output_attr_links = []

        # The link info exists on the destination `node`, so the source is "remote"
        remote_src_node_i: int = aj_link["Node Index"]
        dst_param_name: str = aj_link["Parameter"]
        dst_attr_tag: DpgTag = f"{node.tag}/Params/Input Parameters/{dst_param_name}"

        # We need to find the remote node's param index, to get that remote param's name, used to visually link.
        # This param index is stored on the local param. The link info itself only locates the local/destination name and remote/source *node index*.
        remote_param_i: int = None
        for local_param in node.node_json[ParamSectionName.INPUT]["int"]:
            # idk why we have both of these, but may as well check both
            if local_param["Name"] != dst_param_name:
                continue
            if local_param["Node Index"] != remote_src_node_i:
                continue

            remote_param_i = local_param["Parameter Index"]
            break

        if remote_param_i is None:
            print(f"No remote param found for {dst_attr_tag} in {aj_link}")

        remote_node_json = node.editor.ainb.json["Nodes"][remote_src_node_i]
        remote_src_param_name = remote_node_json[ParamSectionName.OUTPUT]["int"][remote_param_i]["Name"]

        src_attr_tag: DpgTag = f"{node.editor.tag}/node{remote_src_node_i}/Params/Output Parameters/{remote_src_param_name}"
        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=src_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=remote_src_node_i,
            dst_node_i=node.node_i,
            parent=node.editor.tag
        ))
        return output_attr_links
