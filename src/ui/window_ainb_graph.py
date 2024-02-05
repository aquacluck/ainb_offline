from __future__ import annotations
import pathlib
from typing import *
from collections import defaultdict

from .. import curio
import dearpygui.dearpygui as dpg
import graphviz
import orjson

from ..app_ainb_cache import scoped_pack_lookup
from ..edit_context import EditContext
from ..mutable_ainb import MutableAinb, MutableAinbParam
from .. import db, pack_util
from ..app_types import *
from .util import make_node_theme_for_hue, prettydate


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


# TODO lol whats an attachment (runtime node replacement...?)
# TODO Global/EXB Index, Flags
# if entry["Node Index"] <= -100 and entry["Node Index"] >= -8192:
#     entry["Multi Index"] = -100 - entry["Node Index"]
#     entry["Multi Count"] = entry["Parameter Index"]
# AI/PhantomGanon.metaai.root.json node 33 is its own precon?
# TODO Set Pointer Flag Bit Zero, maybe more
# TODO allow editing names, although this will break links? higher level rename for that might be better
# TODO displaying nulls + ui for nulling values


class AinbGraphLayout:
    layout_data: dict = None
    inflight_dot: graphviz.Digraph = None
    inflight_nodes: dict = None
    location: PackIndexEntry = None

    @property
    def has_layout(self) -> bool:
        return self.layout_data is not None

    @classmethod
    def try_get_cached_layout(cls, location: PackIndexEntry) -> AinbGraphLayout:
        # if layout_data := db.TODOLayoutCache.get_by_fullfile(location.fullfile):
        #     return cls(location, layout_data)
        return cls(location)

    def __init__(self, location: PackIndexEntry, layout_data: dict = None):
        self.location = location
        self.layout_data = layout_data
        if not self.has_layout:
            # begin building new layout
            self.inflight_nodes ={}
            self.inflight_dot = graphviz.Digraph(
                "hi", #data["Info"]["Filename"],
                graph_attr={"rankdir": "LR"},
                node_attr={"fontsize": "16", "fixedsize": "true", "shape": "box"}
            )

    def maybe_dot_node(self, i: int, node_tag: DpgTag):
        if self.has_layout:
            return
        self.inflight_nodes[i] = node_tag

    def maybe_dot_edge(self, src_i: int, dst_i: int):
        if self.has_layout:
            return
        self.inflight_dot.edge(str(src_i), str(dst_i))

    async def finalize(self):
        if self.has_layout:
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

        # Send event to edit ctx
        edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.REPLACE_JSON, op_value=user_json_str)
        self.ectx.perform_new_ainb_edit_operation(self.ainb, edit_op)

        # Re-render editor TODO this belongs in AinbGraphEditor?
        dpg.delete_item(self.node_editor)
        dpg.delete_item(f"{self.node_editor}/toolbar")

        return CallbackReq.AwaitCoro(self.editor.render_contents)

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
        async def _tab_change(dpg_args):
            sender, data, user_data = dpg_args
            entered_tab = dpg.get_item_alias(data)
            is_autodump = True  # dpg.get_value(f"{self.tag}/tabs/json/autodump")
            if entered_tab == f"{self.tag}/tabs/json" and is_autodump:
                await self.redump_json_textbox()
            if entered_tab == f"{self.tag}/tabs/history" and is_autodump:
                await self.rerender_history()

        with dpg.tab_bar(tag=f"{self.tag}/tabs", parent=self.tag, callback=CallbackReq.AwaitCoro(_tab_change)):
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
                return CallbackReq.AwaitCoro(self.render_contents)

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

    async def render_contents(self, dpg_args=None):
        # sludge for now
        def _link_callback(sender, app_data):
            dpg.add_node_link(app_data[0], app_data[1], parent=sender)
        def _delink_callback(sender, app_data):
            dpg.delete_item(app_data)

        # TODO top bar, might replace tabs?
        # - "jump to" node list dropdown
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

        # Render globals as a type of node? Not sure if dumb, we do need to link/associate globals into nodes anyways somehow
        # TODO special layout+style for globals node (and move node nearby when hovering on a consuming param?)
        # TODO globals links, eg <Assassin_Senior.action.interuptlargedamage.module>.nodes[0].#ASCommand["Global Parameters Index"] == 0 points to $ASName="LargeDamagge"
        if self.ainb.global_params:
            globals_node = AinbGraphEditorGlobalsNode(editor=self)
            globals_node.render()

        links: List[AinbGraphEditorLink] = []
        for n in self.ainb.nodes:
            gnode = AinbGraphEditorNode(editor=self, node=n)
            gnode.render()
            links += gnode.all_links

        # All nodes+attributes exist, now we can link them
        for link in links:
            link.render_node_link()

        await self.apply_layout()


    async def apply_layout(self):
        await self.layout.finalize()
        for node_i in self.layout.get_node_indexes_with_layout():
            node_tag = f"{self.tag}/node{node_i}/Node"
            pos = self.layout.get_node_coordinates(node_i)
            # print(node_tag, pos)
            dpg.set_item_pos(node_tag, pos)


class AinbGraphEditorGlobalsNode:
    def __init__(self, editor: AinbGraphEditor):
        self.editor = editor

    @property
    def tag(self) -> DpgTag:
        return f"{self.editor.tag}/Globals"

    def render(self):
        globals_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_GLOBALS_HUE)
        with dpg.node(tag=f"{self.tag}/Node", label=ParamSectionName.GLOBAL, parent=self.editor.tag):
            for param in self.editor.ainb.global_params:
                AinbGraphEditorParam(self.editor, param, self.tag).render()
        dpg.bind_item_theme(f"{self.tag}/Node", globals_node_theme)


class AinbGraphEditorNode:
    def __init__(self, editor: AinbGraphEditor, node: MutableAinbNode):
        self.editor = editor
        self.node = node

    @property
    def node_i(self) -> int:
        i = self.node.path.segment_by_name("node_i")
        assert i == self.node.json["Node Index"]
        return i

    @property
    def node_type(self) -> str:
        node_type = self.node.json["Node Type"]
        if node_type == "UserDefined":
            return self.node.json["Name"]
        return node_type

    @property
    def tag(self) -> DpgTag:
        return f"{self.editor.tag}/node{self.node_i}"

    @property
    def all_links(self) -> List[AinbGraphEditorLink]:
        return [AinbGraphEditorLink.create_from_subclass_factory(self.editor, self, link) for link in self.node.all_links]

    def render(self):
        label = f"{self.node_type} ({self.node_i})"

        with dpg.node(tag=f"{self.tag}/Node", label=label, parent=self.editor.tag):
            self.render_topmeta()
            for param in self.node.all_params:
                AinbGraphEditorParam(self.editor, param, self.tag).render()

            self.editor.layout.maybe_dot_node(self.node_i, f"{self.tag}/Node")
            for link in self.all_links:
                # Things like Standard Links need their own "output" dpg.node_attribute,
                # as they don't logically link from a param but the node itself.
                link.maybe_render_node_attribute()

    def render_topmeta(self):
        with dpg.node_attribute(tag=f"{self.tag}/LinkTarget", attribute_type=dpg.mvNode_Attr_Input):
            for command_i, command in enumerate(self.editor.ainb.json.get("Commands", [])):
                if self.node_i == command["Left Node Index"]:
                    cmd_name = command["Name"]
                    dpg.add_text(f"@ Command[{cmd_name}]")
                    command_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_COMMAND_HUE)
                    dpg.bind_item_theme(f"{self.tag}/Node", command_node_theme)

            for aj_flag in self.node.json.get("Flags", []):
                if aj_flag == "Is External AINB":
                    for aref in self.editor.ainb.json["Embedded AINB Files"]:
                        if aref["File Path"] != self.node.json["Name"] + ".ainb":
                            continue
                        #print(aref["Count"]) ...instance/link count? TODO

                        dest_ainbfile = aref["File Category"] + '/' + aref["File Path"]
                        dest_location = scoped_pack_lookup(PackIndexEntry(internalfile=dest_ainbfile, packfile=self.editor.ainb.location.packfile, extension=RomfsFileTypes.AINB))
                        with dpg.group(horizontal=True):
                            dpg.add_text(f'@ ExternalAINB[{aref["File Category"]}] {aref["File Path"]}')
                            dpg.add_button(
                                label="Open AINB",
                                callback=CallbackReq.SpawnCoro(EditContext.get().open_ainb_window_as_coro, [dest_location]),
                                arrow=True,
                                direction=dpg.mvDir_Right,
                            )

                        external_ainb_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_MODULE_HUE)
                        dpg.bind_item_theme(f"{self.tag}/Node", external_ainb_theme)
                else:
                    dpg.add_text(f"@ {aj_flag}")


class AinbGraphEditorParam:
    def __init__(self, editor: AinbGraphEditor, param: MutableAinbParam, node_tag: DpgTag):
        self.editor = editor
        self.param = param
        self.node_tag = node_tag

    def render(self):
        param = self.param

        # Some dpg inputs (eg int) blow up when given a null, so we awkwardly omit any null arg
        v = param.json.get(param.param_default_name)
        dpg_default_value_kwarg = {"default_value": v} if v is not None else {}

        ui_label = f"{ParamSectionLegend[param.param_section_name]} {param.param_type} {param.i_of_type}: {param.name}"
        op_selector = param.get_default_value_selector()

        def on_edit(sender, data, op_selector):
            # XXX ideally plumb in ectx, or send this up through the editor?
            edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.PARAM_UPDATE_DEFAULT, op_value=data, op_selector=op_selector)
            EditContext.get().perform_new_ainb_edit_operation(self.editor.ainb, edit_op)

        node_attr_tag_ns = f"{self.node_tag}/Params/{param.param_section_name}/{param.name}"
        ui_input_tag = f"{node_attr_tag_ns}/ui_input"
        with dpg.node_attribute(tag=node_attr_tag_ns, parent=f"{self.node_tag}/Node", attribute_type=ParamSectionDpgAttrType[param.param_section_name]):
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


class AinbGraphEditorLink:
    @staticmethod
    def create_from_subclass_factory(editor: AinbGraphEditor, node: AinbGraphEditorNode, link: MutableAinbLink) -> AinbGraphEditorLink:
        ltype = link.link_type
        ltype = link.path.segment_by_name("link_type")
        if ltype == "Output/bool Input/float Input Link": # 0
            cls = AinbGraphEditorLink_0_bidirectional_lookup
        elif ltype == "Standard Link": # 2
            cls = AinbGraphEditorLink_2_standard
        elif ltype == "Resident Update Link": # 3
            cls = AinbGraphEditorLink_3_resident_update
        elif ltype == "String Input Link": # 4
            cls = AinbGraphEditorLink_4_string_input
        elif ltype == "int Input Link": # 5
            cls = AinbGraphEditorLink_5_int_input
        else:
            breakpoint()
            raise ValueError(f"Unsupported link type {ltype}")
        return cls(editor, node, link)

    def __init__(self, editor: AinbGraphEditor, node: AinbGraphEditorNode, link: MutableAinbLink):
        self.editor = editor
        self.node = node
        self.link = link

    def maybe_render_node_attribute(self):
        pass  # override me when applicable

    def get_link_calls(self) -> List[DeferredNodeLinkCall]:
        return []  # override me

    def render_node_link(self):
        for lc in self.get_link_calls():
            self.editor.layout.maybe_dot_edge(lc.src_node_i, lc.dst_node_i)
            dpg.add_node_link(lc.src_attr, lc.dst_attr, parent=lc.parent)


class AinbGraphEditorLink_0_bidirectional_lookup(AinbGraphEditorLink):
    def get_link_calls(self) -> List[DeferredNodeLinkCall]:
        output_attr_links = []

        remote_i = self.link.json["Node Index"]
        local_param_name = self.link.json["Parameter"]  # May be input or output

        # Find the local param being linked
        local_type = None
        local_param_direction = None  # "Output Parameters" or "Input Parameters"
        local_i_of_type = None
        parameter_index = None
        local_param_node_index = None

        for _local_type, local_params in self.node.node.json.get("Input Parameters", {}).items():
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
                                print(f"ignoring exb source in {self.node.node_type} {self.node.node_i}")
                                continue
                            multi_i = multi_item["Node Index"]
                            multi_item_param_name = self.editor.ainb.json["Nodes"][multi_i]["Output Parameters"][local_type][multi_item["Parameter Index"]]["Name"]
                            remote_multi_attr_tag = f"{self.editor.tag}/node{multi_i}/Params/Output Parameters/{multi_item_param_name}"
                            my_attr_tag = f"{self.node.tag}/Params/Input Parameters/{local_param_name}"
                            output_attr_links.append(DeferredNodeLinkCall(
                                src_attr=remote_multi_attr_tag,
                                dst_attr=my_attr_tag,
                                src_node_i=multi_i,
                                dst_node_i=self.node.node_i,
                                parent=self.editor.tag,
                            ))
                        return output_attr_links  # Return multi links

                    elif local_param_node_index < 0:
                        # grabbing globals/exb???
                        print(f"Unhandled {local_param_node_index} source node in Input Parameters - {self.link.link_type}")
                        return output_attr_links  # TODO Return nothing for now

                    else:
                        if local_param_node_index != remote_i:
                            # FIXME loop+segfault in AI/EquipEventNPC.event.root.ainb, and some Bool business
                            # Unhandled local_param_node_index 269 != remote_i 268
                            print(f"Unhandled local_param_node_index {local_param_node_index} != remote_i {remote_i}")
                            # breakpoint()
                            return output_attr_links # XXX Return nothing? I'm doing something wrong lol, get examples
                        parameter_index = local_param["Parameter Index"]  # can this still be a multi?

        for _local_type, local_params in self.node.node.json.get("Output Parameters", {}).items():
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
        remote_params = self.editor.ainb.json["Nodes"][remote_i].get(remote_param_direction, {}).get(remote_type, [])
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
                if remote_param.get("Node Index") != self.node.node_i:
                    continue

                # Correct index into per-type param list?
                if remote_param.get("Parameter Index") != local_i_of_type:
                    continue

                remote_param_name = remote_param["Name"]

        my_attr_tag = f"{self.node.tag}/Params/{local_param_direction}/{local_param_name}"
        if remote_param_name is None and (local_param_node_index or 0) > -1:
            # XXX is this right
            print(f"No remote param found for {my_attr_tag} in {self.link.json}")
        else:
            remote_attr_tag = f"{self.editor.tag}/node{remote_i}/Params/{remote_param_direction}/{remote_param_name}"

            # XXX is there anything more for when flags are precon, or was I just confused again
            if local_param_direction == "Output Parameters":
                output_attr_links.append(DeferredNodeLinkCall(
                    src_attr=my_attr_tag,
                    dst_attr=remote_attr_tag,
                    src_node_i=self.node.node_i,
                    dst_node_i=remote_i,
                    parent=self.editor.tag
                ))
            else:
                output_attr_links.append(DeferredNodeLinkCall(
                    src_attr=remote_attr_tag,
                    dst_attr=my_attr_tag,
                    src_node_i=remote_i,
                    dst_node_i=self.node.node_i,
                    parent=self.editor.tag
                ))
        return output_attr_links


class AinbGraphEditorLink_2_standard(AinbGraphEditorLink):
    def maybe_render_node_attribute(self):
        _link_calls = self.get_link_calls()
        if not _link_calls:
            return
        lc: DeferredNodeLinkCall = _link_calls[0]

        # make new src node attributes for links to children/selected/etc nodes
        with dpg.node_attribute(tag=lc.src_attr, attribute_type=dpg.mvNode_Attr_Output):
            labels = []
            if cname := self.link.json.get("Connection Name"):
                labels.append(cname)
            if cond := self.link.json.get("Condition"):
                labels.append(f"Condition: {cond}")
            if note := self.link.json.get("その他"):  # "Others"?
                labels.append(note)  # Contains "Default"?
            label = ", ".join(labels) or f"[{self.link.link_type}]"
            dpg.add_text(label)

    def get_link_calls(self) -> List[DeferredNodeLinkCall]:
        output_attr_links = []

        # refs to entire nodes for stuff like simultaneous, selectors.
        dst_i = self.link.json["Node Index"]
        my_attr_tag = f"{self.node.tag}/stdlink{self.link.i_of_link_type}"
        dst_attr_tag = f"{self.editor.tag}/node{dst_i}/LinkTarget"

        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=my_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=self.node.node_i,
            dst_node_i=dst_i,
            parent=self.editor.tag
        ))
        return output_attr_links


class AinbGraphEditorLink_3_resident_update(AinbGraphEditorLink):
    def maybe_render_node_attribute(self):
        _link_calls = self.get_link_calls()
        if not _link_calls:
            return
        lc: DeferredNodeLinkCall = _link_calls[0]

        with dpg.node_attribute(tag=lc.src_attr, attribute_type=dpg.mvNode_Attr_Output):
            flags = self.link.json["Update Info"]["Flags"]
            label = f"[ResUpdate] ({flags})" if flags else "[ResUpdate]"
            dpg.add_text(label)

    def get_link_calls(self) -> List[DeferredNodeLinkCall]:
        output_attr_links = []

        # pointers to params owned by other nodes? idk
        # pulling in references to other nodes? idk
        dst_i = self.link.json["Node Index"]
        my_attr_tag = f"{self.node.tag}/reslink{self.link.i_of_link_type}"

        dst_attr_tag = f"{self.editor.tag}/node{dst_i}/LinkTarget" # TODO learn some things
        # if dst_param_name := self.link.json["Update Info"].get("String"):
        #     # dst_attr_tag = f"{self.editor.tag}/node{dst_i}/Params/Input Parameters/{dst_param_name}"
        #     # I don't understand how this String works, just point to the node for now.
        #     dst_attr_tag = f"{self.editor.tag}/node{dst_i}/LinkTarget"
        # else:
        #     # Pointing into things like Element_Sequential or UDT @Is External AINB
        #     # seem to not specify a String, so we'll just point at the node itself until
        #     # this default/lhs/internal/??? param is better understood.
        #     # The ResUpdate flags usually include "Is Valid Update" when this happens.
        #     dst_attr_tag = f"{self.editor.tag}/node{dst_i}/LinkTarget"

        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=my_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=self.node.node_i,
            dst_node_i=dst_i,
            parent=self.editor.tag
        ))
        return output_attr_links


class AinbGraphEditorLink_4_string_input(AinbGraphEditorLink):
    def get_link_calls(self) -> List[DeferredNodeLinkCall]:
        output_attr_links = []

        # The link info exists on the destination `node`, so the source is "remote"
        remote_src_node_i: int = self.link.json["Node Index"]
        dst_param_name: str = self.link.json["Parameter"]
        dst_attr_tag: DpgTag = f"{self.node.tag}/Params/Input Parameters/{dst_param_name}"

        # We need to find the remote node's param index, to get that remote param's name, used to visually link.
        # This param index is stored on the local param. The link info itself only locates the local/destination name and remote/source *node index*.
        remote_param_i: int = None
        for local_param in self.node.node.json[ParamSectionName.INPUT]["string"]:
            # idk why we have both of these, but may as well check both
            if local_param["Name"] != dst_param_name:
                continue
            if local_param["Node Index"] != remote_src_node_i:
                continue

            remote_param_i = local_param["Parameter Index"]
            break

        if remote_param_i is None:
            print(f"No remote param found for {dst_attr_tag} in {self.link.json}")

        remote_node_json = self.editor.ainb.json["Nodes"][remote_src_node_i]
        remote_src_param_name = remote_node_json[ParamSectionName.OUTPUT]["string"][remote_param_i]["Name"]

        src_attr_tag: DpgTag = f"{self.editor.tag}/node{remote_src_node_i}/Params/Output Parameters/{remote_src_param_name}"
        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=src_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=remote_src_node_i,
            dst_node_i=self.node.node_i,
            parent=self.editor.tag
        ))
        return output_attr_links


class AinbGraphEditorLink_5_int_input(AinbGraphEditorLink):
    def get_link_calls(self) -> List[DeferredNodeLinkCall]:
        output_attr_links = []

        # The link info exists on the destination `node`, so the source is "remote"
        remote_src_node_i: int = self.link.json["Node Index"]
        dst_param_name: str = self.link.json["Parameter"]
        dst_attr_tag: DpgTag = f"{self.node.tag}/Params/Input Parameters/{dst_param_name}"

        # We need to find the remote node's param index, to get that remote param's name, used to visually link.
        # This param index is stored on the local param. The link info itself only locates the local/destination name and remote/source *node index*.
        remote_param_i: int = None
        for local_param in self.node.node.json[ParamSectionName.INPUT]["int"]:
            # idk why we have both of these, but may as well check both
            if local_param["Name"] != dst_param_name:
                continue
            if local_param["Node Index"] != remote_src_node_i:
                continue

            remote_param_i = local_param["Parameter Index"]
            break

        if remote_param_i is None:
            print(f"No remote param found for {dst_attr_tag} in {self.link.json}")

        remote_node_json = self.editor.ainb.json["Nodes"][remote_src_node_i]
        remote_src_param_name = remote_node_json[ParamSectionName.OUTPUT]["int"][remote_param_i]["Name"]

        src_attr_tag: DpgTag = f"{self.editor.tag}/node{remote_src_node_i}/Params/Output Parameters/{remote_src_param_name}"
        output_attr_links.append(DeferredNodeLinkCall(
            src_attr=src_attr_tag,
            dst_attr=dst_attr_tag,
            src_node_i=remote_src_node_i,
            dst_node_i=self.node.node_i,
            parent=self.editor.tag
        ))
        return output_attr_links
