import functools
import json
import pathlib
from typing import *
from collections import defaultdict

import dearpygui.dearpygui as dpg

from .dt_ainb.ainb import AINB
from .app_ainb_cache import scoped_pack_lookup
from .edit_context import EditContext
from . import pack_util
from .app_types import *


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


@dataclass
class RenderAinbNodeRequest:
    # ainb
    ainb: AINB
    ainb_location: PackIndexEntry
    aj: dict  # AINB.output_dict json
    category: str  # AI Logic Sequence
    # ainb node
    aj_node: dict
    node_i: int
    # ui
    node_editor: Union[int, str]
    ainb_tag_ns: str
    node_tag_ns: str


def open_ainb_graph_window(s, a, ainb_location: PackIndexEntry):
    ectx = EditContext.get()
    if window_tag := ectx.get_ainb_window(ainb_location):
        dpg.focus_item(window_tag)
        return

    print(f"Opening {ainb_location.fullfile}")
    category, ainbfile = pathlib.Path(ainb_location.internalfile).parts
    ainb = ectx.load_ainb(ainb_location)

    if ainb_location.packfile == "Root":
        window_label = f"[{category}] {ainbfile}"
    else:
        window_label = f"[{category}] {ainbfile} [from {ainb_location.packfile}]"

    def close(*_):
        ectx.unregister_ainb_window(ainb_location)

    with dpg.window(label=window_label, width=1280, height=1080, pos=[600, 200], on_close=close) as ainb_window:
        ectx.register_ainb_window(ainb_location, ainb_window)

        def save_ainb():
            ectx.save_ainb(ainb_location, ainb)

        def redump_json():
            # Replace json textbox with working ainb (possibly dirty)
            ainb_json_str = json.dumps(ainb.output_dict, indent=4)
            json_textbox = f"{ainb_window}/tabs/json/textbox"
            dpg.set_value(json_textbox, ainb_json_str)

        def rerender_graph_from_json():
            json_textbox = f"{ainb_window}/tabs/json/textbox"
            node_editor = f"{ainb_window}/tabs/graph/editor"
            user_json_str = dpg.get_value(json_textbox)

            # Send event to edit ctx
            edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.REPLACE_JSON, op_value=user_json_str)
            ectx.perform_new_edit_operation(ainb_location, ainb, edit_op)

            # Re-render editor
            dpg.delete_item(node_editor, children_only=True)
            add_ainb_nodes(ainb, ainb_location, node_editor)

        def tab_change(sender, data, app_data):
            entered_tab = dpg.get_item_alias(data)
            is_autodump = True  # dpg.get_value(f"{ainb_window}/tabs/json/autodump")
            if entered_tab == f"{ainb_window}/tabs/json" and is_autodump:
                redump_json()

        with dpg.tab_bar(tag=f"{ainb_window}/tabs", callback=tab_change):
            # dpg.add_tab_button(label="[max]", callback=dpg.maximize_viewport)  # works at runtime, fails at init?
            # dpg.add_tab_button(label="wipe cache")
            with dpg.tab(tag=f"{ainb_window}/tabs/graph", label="Node Graph"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    # sludge for now
                    def link_callback(sender, app_data):
                        dpg.add_node_link(app_data[0], app_data[1], parent=sender)
                    def delink_callback(sender, app_data):
                        dpg.delete_item(app_data)

                    # TODO top bar, might replace tabs?
                    # - "jump to" node list dropdown
                    # - add node button with searchable popup for node type
                    # - save to modfs button, dirty indicator
                    # - "{}" json button?

                    # Main graph ui + rendering nodes
                    node_editor = f"{ainb_window}/tabs/graph/editor"
                    dpg.add_node_editor(
                        tag=node_editor,
                        callback=link_callback,
                        delink_callback=delink_callback,
                        minimap=True,
                        minimap_location=dpg.mvNodeMiniMap_Location_BottomRight
                    )
                    add_ainb_nodes(ainb, ainb_location, node_editor)


            with dpg.tab(tag=f"{ainb_window}/tabs/json", label="Parsed JSON"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    with dpg.group(horizontal=True):
                        #dpg.add_button(label="Refresh JSON", callback=redump_json)
                        #dpg.add_checkbox(label="(Always refresh)", tag=f"{ainb_window}/tabs/json/autodump", default_value=True)
                        dpg.add_button(label="Apply Changes", callback=rerender_graph_from_json)
                        #      dpg.add_button(label="Overwrite AINB") duh
                        #      dpg.add_button(label="Open JSON in: ", source="jsdfl/opencmd")
                        #      dpg.add_input_text(default_value='$EDITOR "%s"', tag="jsdfl/opencmd")
                    json_textbox = f"{ainb_window}/tabs/json/textbox"
                    dpg.add_input_text(tag=json_textbox, default_value="any slow dumps?", width=-1, height=-1, multiline=True, tab_input=True, readonly=False)
                    redump_json()

            dpg.add_tab_button(label="Save to modfs", callback=save_ainb)

    return ainb_window


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


def add_ainb_nodes(ainb: AINB, ainb_location: PackIndexEntry, node_editor):
    aj = ainb.output_dict  # ainb json. we call him aj
    ainb_tag_ns = f"{node_editor}/ainb0"
    category, _ainbfile = pathlib.Path(ainb_location.internalfile).parts

    # TODO special layout+style for globals node (and move node nearby when hovering on a consuming param?)
    # TODO globals links, eg <Assassin_Senior.action.interuptlargedamage.module>.nodes[0].#ASCommand["Global Parameters Index"] == 0 points to $ASName="LargeDamagge"
    # Render globals as a type of node? Not sure if dumb, we do need to link/associate globals into nodes anyways somehow
    if aj.get(ParamSectionName.GLOBAL):
        globals_tag_ns = f"{ainb_tag_ns}/Globals"

        globals_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_GLOBALS_HUE)
        dpg.add_node(tag=f"{globals_tag_ns}/Node", label=ParamSectionName.GLOBAL, parent=node_editor)
        dpg.bind_item_theme(f"{globals_tag_ns}/Node", globals_node_theme)

        render_ainb_node_param_section(RenderAinbNodeRequest(
            # ainb
            ainb=ainb,
            ainb_location=ainb_location,
            aj=aj,
            category=category,
            # ainb node
            aj_node=aj,
            node_i=-420,  # lol
            # ui
            node_editor=node_editor,
            ainb_tag_ns=ainb_tag_ns,
            node_tag_ns=globals_tag_ns,
        ), ParamSectionName.GLOBAL)

    # needed somewhere to throw a lot of vars...
    render_reqs = [RenderAinbNodeRequest(
        # ainb
        ainb=ainb,
        ainb_location=ainb_location,
        aj=aj,
        category=category,
        # ainb node
        aj_node=aj_node,
        node_i=node_i,
        # ui
        node_editor=node_editor,
        ainb_tag_ns=ainb_tag_ns,
        node_tag_ns=f"{ainb_tag_ns}/node{node_i}",
    ) for node_i, aj_node in enumerate(aj.get("Nodes", []))]

    # We can't link nodes that don't exist yet
    deferred_link_calls: List[DeferredNodeLinkCall] = []
    for req in render_reqs:
        pending_links = render_ainb_node(req)
        deferred_link_calls += pending_links

    # All nodes+attributes exist, now we can link them
    render_ainb_file_links_and_layout(aj, ainb_tag_ns, deferred_link_calls)


def render_ainb_node(req: RenderAinbNodeRequest) -> List[DeferredNodeLinkCall]:
    output_attr_links: List[DeferredNodeLinkCall] = []

    node_type = req.aj_node["Node Type"]
    node_name = req.aj_node["Name"]
    if node_type == "UserDefined":
        label = f"{node_name} ({req.node_i})"
    else:
        label = f"{node_type} ({req.node_i})"

    with dpg.node(tag=f"{req.node_tag_ns}/Node", label=label, parent=req.node_editor) as node_tag_:
        render_ainb_node_topmeta(req)
        render_ainb_node_param_section(req, ParamSectionName.IMMEDIATE)
        render_ainb_node_param_section(req, ParamSectionName.INPUT)
        render_ainb_node_param_section(req, ParamSectionName.OUTPUT)

        for aj_link_type, aj_links in req.aj_node.get("Linked Nodes", {}).items():
            for i_of_link_type, aj_link in enumerate(aj_links):
                #print(aj_link_type, aj_link)
                if aj_link_type == "Output/bool Input/float Input Link": # 0
                    output_attr_links += process_ainb_node_link__outputboolinputfloatinput_link(req, aj_link, i_of_link_type)
                elif aj_link_type == "Standard Link": # 2
                    output_attr_links += process_ainb_node_link__standard_link(req, aj_link, i_of_link_type)
                elif aj_link_type == "Resident Update Link": # 3
                    output_attr_links += process_ainb_node_link__resident_update_link(req, aj_link, i_of_link_type)
                elif aj_link_type == "String Input Link": # 4
                    pass # output_attr_links += process_ainb_node_link__string_input_link(req, aj_link, i_of_link_type)
                elif aj_link_type == "int Input Link": # 5 the opposite direction of type 0? TODO learn things
                    pass # output_attr_links += process_ainb_node_link__int_input_link(req, aj_link, i_of_link_type)
                else:
                    print(f"Unsupported link type {aj_link_type}")
                    breakpoint()
                    continue
    return output_attr_links


def render_ainb_file_links_and_layout(aj, ainb_tag_ns: str, link_calls: List[DeferredNodeLinkCall]):
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
    for command_i, command in enumerate(aj.get("Commands", [])):
        node_i = command["Left Node Index"]
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
        command_named_coords[command["Name"]] = (0 * LAYOUT_X_SPACING, command_i * LAYOUT_Y_SPACING)

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
        node_tag = f"{ainb_tag_ns}/node{node_i}/Node"
        x = LAYOUT_X_SPACING * max_depth - entry_point_offset[0]
        y = LAYOUT_Y_SPACING * node_y_at_depth[max_depth] - entry_point_offset[1]
        node_y_at_depth[max_depth] += 1
        pos = [x, y]
        # print(node_tag, pos)
        dpg.set_item_pos(node_tag, pos)


def render_ainb_node_topmeta(req: RenderAinbNodeRequest) -> None:
    with dpg.node_attribute(tag=f"{req.node_tag_ns}/LinkTarget", attribute_type=dpg.mvNode_Attr_Input):
        for command_i, command in enumerate(req.aj.get("Commands", [])):
            if req.node_i == command["Left Node Index"]:
                cmd_name = command["Name"]
                dpg.add_text(f"@ Command[{cmd_name}]")
                command_node_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_COMMAND_HUE)
                dpg.bind_item_theme(f"{req.node_tag_ns}/Node", command_node_theme)


        for aj_flag in req.aj_node.get("Flags", []):
            if aj_flag == "Is External AINB":
                for aref in req.aj["Embedded AINB Files"]:
                    if aref["File Path"] != req.aj_node["Name"] + ".ainb":
                        continue

                    #print(aref["Count"]) ...instance/link count? TODO

                    dest_ainbfile = aref["File Category"] + '/' + aref["File Path"]
                    dest_location = scoped_pack_lookup(PackIndexEntry(internalfile=dest_ainbfile, packfile=req.ainb_location.packfile, extension="ainb"))
                    with dpg.group(horizontal=True):
                        dpg.add_text(f'@ ExternalAINB[{aref["File Category"]}] {aref["File Path"]}')
                        dpg.add_button(label="Open AINB", user_data=dest_location, callback=open_ainb_graph_window, arrow=True, direction=dpg.mvDir_Right)

                    external_ainb_theme = make_node_theme_for_hue(AppStyleColors.GRAPH_MODULE_HUE)
                    dpg.bind_item_theme(f"{req.node_tag_ns}/Node", external_ainb_theme)
            else:
                dpg.add_text(f"@ {aj_flag}")


# TODO lol whats an attachment (runtime node replacement...?)
# TODO Global/EXB Index, Flags
# if entry["Node Index"] <= -100 and entry["Node Index"] >= -8192:
#     entry["Multi Index"] = -100 - entry["Node Index"]
#     entry["Multi Count"] = entry["Parameter Index"]
# AI/PhantomGanon.metaai.root.json node 33 is its own precon?
# TODO Set Pointer Flag Bit Zero, maybe more
def render_ainb_node_param_section(req: RenderAinbNodeRequest, param_section: ParamSectionName):
    typed_params: Dict[str, List[Dict]] = req.aj_node.get(param_section, {})
    for aj_type, aj_params in typed_params.items():
        i_of_type = -1
        for aj_param in aj_params:
            i_of_type += 1
            # TODO allow editing names, although this will break links? higher level rename for that might be better
            param_name = aj_param.get("Name", AppErrorStrings.FAILNULL)

            # How defaults are named in this param section's json
            param_default_name = "Default Value" if param_section == ParamSectionName.GLOBAL else "Value"

            # TODO displaying nulls + ui for nulling values
            # Some dpg inputs (eg int) blow up when given a null, so we awkwardly omit any null arg
            v = aj_param.get(param_default_name)
            dpg_default_value_kwarg = {"default_value": v} if v is not None else {}

            ui_label = f"{ParamSectionLegend[param_section]} {aj_type} {i_of_type}: {param_name}"
            op_selector = ("Nodes", req.node_i, param_section, aj_type, i_of_type, param_default_name)

            def on_edit(sender, data, op_selector):
                ectx = EditContext.get()
                # TODO store jsonpath or something instead?
                # aj["Nodes"][i]["Immediate Parameters"][aj_type][i_of_type]["Value"] = op_value
                # aj["Global Parameters"][aj_type][i_of_type]["Default Value"] = op_value
                op_value = data  # TODO how do non scalars work? also debounce or do on leave or something?
                edit_op = AinbEditOperation(op_type=AinbEditOperationTypes.PARAM_UPDATE_DEFAULT, op_value=op_value, op_selector=op_selector)
                ectx.perform_new_edit_operation(req.ainb_location, req.ainb, edit_op)

            node_attr_tag_ns = f"{req.node_tag_ns}/Params/{param_section}/{param_name}"
            ui_input_tag = f"{node_attr_tag_ns}/ui_input"
            with dpg.node_attribute(tag=node_attr_tag_ns, parent=f"{req.node_tag_ns}/Node", attribute_type=ParamSectionDpgAttrType[param_section]):
                if param_section == ParamSectionName.OUTPUT:
                    # not much to show unless we're planning to execute the graph?
                    dpg.add_text(ui_label)

                elif aj_type == "int":
                    dpg.add_input_int(tag=ui_input_tag, label=ui_label, width=80, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
                elif aj_type == "bool":
                    dpg.add_checkbox(tag=ui_input_tag, label=ui_label, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
                elif aj_type == "float":
                    dpg.add_input_float(tag=ui_input_tag, label=ui_label, width=100, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
                elif aj_type == "string":
                    dpg.add_input_text(tag=ui_input_tag, label=ui_label, width=150, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
                elif aj_type == "vec3f":
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

                elif aj_type == "userdefined":
                    dpg.add_input_text(tag=ui_input_tag, label=ui_label, width=300, user_data=op_selector, callback=on_edit, **dpg_default_value_kwarg)
                else:
                    err_label = f"bruh typo in ur type {aj_type}"
                    dpg.add_text(tag=ui_input_tag, label=err_label, width=300, **dpg_default_value_kwarg)


def process_ainb_node_link__outputboolinputfloatinput_link(req: RenderAinbNodeRequest, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
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

    for _local_type, local_params in req.aj_node.get("Input Parameters", {}).items():
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
                        multi_item_param_name = req.aj["Nodes"][multi_i]["Output Parameters"][local_type][multi_item["Parameter Index"]]["Name"]
                        remote_multi_attr_tag = f"{req.ainb_tag_ns}/node{multi_i}/Params/Output Parameters/{multi_item_param_name}"
                        my_attr_tag = f"{req.node_tag_ns}/Params/Input Parameters/{local_param_name}"
                        output_attr_links.append(DeferredNodeLinkCall(
                            src_attr=remote_multi_attr_tag,
                            dst_attr=my_attr_tag,
                            src_node_i=multi_i,
                            dst_node_i=req.node_i,
                            parent=req.node_editor
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

    for _local_type, local_params in req.aj_node.get("Output Parameters", {}).items():
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
    remote_params = req.aj["Nodes"][remote_i].get(remote_param_direction, {}).get(remote_type, [])
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
            if remote_param.get("Node Index") != req.node_i:
                continue

            # Correct index into per-type param list?
            if remote_param.get("Parameter Index") != local_i_of_type:
                continue

            remote_param_name = remote_param["Name"]

    my_attr_tag = f"{req.node_tag_ns}/Params/{local_param_direction}/{local_param_name}"
    if remote_param_name is None and (local_param_node_index or 0) > -1:
        # XXX is this right
        print(f"No remote param found for {my_attr_tag} in {aj_link}")
    else:
        remote_attr_tag = f"{req.ainb_tag_ns}/node{remote_i}/Params/{remote_param_direction}/{remote_param_name}"

        # XXX is there anything more for when flags are precon, or was I just confused again
        if local_param_direction == "Output Parameters":
            output_attr_links.append(DeferredNodeLinkCall(
                src_attr=my_attr_tag,
                dst_attr=remote_attr_tag,
                src_node_i=req.node_i,
                dst_node_i=remote_i,
                parent=req.node_editor
            ))
        else:
            output_attr_links.append(DeferredNodeLinkCall(
                src_attr=remote_attr_tag,
                dst_attr=my_attr_tag,
                src_node_i=remote_i,
                dst_node_i=req.node_i,
                parent=req.node_editor
            ))
    return output_attr_links


def process_ainb_node_link__standard_link(req: RenderAinbNodeRequest, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
    aj_link_type = "Standard Link"
    output_attr_links = []

    # refs to entire nodes for stuff like simultaneous, selectors.
    # make new node attributes to support links to children.
    dst_i = aj_link["Node Index"]
    my_attr_tag = f"{req.node_tag_ns}/stdlink{i_of_link_type}"
    dst_attr_tag = f"{req.ainb_tag_ns}/node{dst_i}/LinkTarget"

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
        src_node_i=req.node_i,
        dst_node_i=dst_i,
        parent=req.node_editor
    ))
    return output_attr_links


def process_ainb_node_link__resident_update_link(req: RenderAinbNodeRequest, aj_link: Dict, i_of_link_type: int) -> List[DeferredNodeLinkCall]:
    aj_link_type = "Resident Update Link"
    output_attr_links = []

    # pointers to params owned by other nodes? idk
    # pulling in references to other nodes? idk
    dst_i = aj_link["Node Index"]
    my_attr_tag = f"{req.node_tag_ns}/reslink{i_of_link_type}"

    # print(aj_link)

    dst_attr_tag = f"{req.ainb_tag_ns}/node{dst_i}/LinkTarget" # TODO learn some things
    # if dst_param_name := aj_link["Update Info"].get("String"):
    #     # dst_attr_tag = f"{req.ainb_tag_ns}/node{dst_i}/Params/Input Parameters/{dst_param_name}"
    #     # I don't understand how this String works, just point to the node for now.
    #     dst_attr_tag = f"{req.ainb_tag_ns}/node{dst_i}/LinkTarget"
    # else:
    #     # Pointing into things like Element_Sequential or UDT @Is External AINB
    #     # seem to not specify a String, so we'll just point at the node itself until
    #     # this default/lhs/internal/??? param is better understood.
    #     # The ResUpdate flags usually include "Is Valid Update" when this happens.
    #     dst_attr_tag = f"{req.ainb_tag_ns}/node{dst_i}/LinkTarget"

    with dpg.node_attribute(tag=my_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
        flags = aj_link["Update Info"]["Flags"]
        flags = "|".join((" ".join(flags)).split())  # bad ainb parse?
        label = f"[ResUpdate] ({flags})" if flags else "[ResUpdate]"
        dpg.add_text(label)

    output_attr_links.append(DeferredNodeLinkCall(
        src_attr=my_attr_tag,
        dst_attr=dst_attr_tag,
        src_node_i=req.node_i,
        dst_node_i=dst_i,
        parent=req.node_editor
    ))
    return output_attr_links
