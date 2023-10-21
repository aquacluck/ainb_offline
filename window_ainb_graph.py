import json
import pathlib
from typing import *
from collections import defaultdict

import dearpygui.dearpygui as dpg
from dt_ainb.ainb import AINB

import pack_util
from app_types import *


def open_ainb_graph_window(s, a, ainb_location: AinbIndexCacheEntry):
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    if ainb_location.packfile is None:
        print(f"Opening {romfs}/{ainb_location.ainbfile}")
        ainb = AINB(open(f"{romfs}/{ainb_location.ainbfile}", "rb").read())
        # TODO verify romfs/pack relative ainb location is always 2 part {category}/{ainbfile} and categories are always accurate
        category, ainbfile = pathlib.Path(ainb_location.ainbfile).parts
        window_label = ainb_location.ainbfile
        window_label = f"[{category}] {ainbfile}"
    else:
        print(f"Opening {romfs}/{ainb_location.packfile}:/{ainb_location.ainbfile}")
        ainb = AINB(pack_util.load_file_from_pack(f"{romfs}/{ainb_location.packfile}", ainb_location.ainbfile))
        category, ainbfile = pathlib.Path(ainb_location.ainbfile).parts
        window_label = f"[{category}] {ainbfile} [from {ainb_location.packfile}]"

    with dpg.window(label=window_label, width=800, height=600, pos=[600, 200]) as ainbwindow:
        with dpg.tab_bar():
            # dpg.add_tab_button(label="[max]", callback=dpg.maximize_viewport)  # works at runtime, fails at init?
            # dpg.add_tab_button(label="wipe cache")
            with dpg.tab(label="Node Graph"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    # sludge for now
                    def link_callback(sender, app_data):
                        dpg.add_node_link(app_data[0], app_data[1], parent=sender)
                    def delink_callback(sender, app_data):
                        dpg.delete_item(app_data)

                    # Main graph ui + rendering nodes
                    node_editor = dpg.add_node_editor(
                        callback=link_callback,
                        delink_callback=delink_callback,
                        minimap=True,
                        minimap_location=dpg.mvNodeMiniMap_Location_BottomRight
                    )
                    add_ainb_nodes(ainb, ainb_location, node_editor)


            with dpg.tab(label="Parsed JSON"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    def dump_json():
                        ainb_json_str = json.dumps(ainb.output_dict, indent=4)
                        dpg.set_value(json_textbox, ainb_json_str)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Redump working AINB", callback=dump_json)
                        # TODO dpg.add_checkbox("Redump when entering this tab", default_value=True)
                        # TODO node_editor changes don't write back to AINB.output_dict yet
                        #      dpg.add_button(label="Overwrite AINB") duh
                        #      dpg.add_button(label="Open JSON in: ", source="jsdfl/opencmd")
                        #      dpg.add_input_text(default_value='$EDITOR "%s"', tag="jsdfl/opencmd")
                    json_textbox = dpg.add_input_text(default_value="any slow dumps?", width=-1, height=-1, multiline=True, tab_input=True, readonly=False)
                    dump_json()


            with dpg.tab(label="BYML"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    dpg.add_text('lol gottem')
                    # RSDB/ActorInfo, GameActorInfo, RSDB/*?
                    # lotta oob limits? GameSafetySetting.Product.100.rstbl.byml.zs

                    # Component/BSAParam/EnemyBase.game__component__BSAParam.bgyml:
                    # - ActionSlotMainAin: Work/AI/Root/Enemy/EnemyBase.action.root.ain
                    # - ActionSlot*Ain: Work/AI/Root/Enemy/EnemyBase.action.root.ain
                    # - BrainAinPath: Work/AI/Root/Enemy/EnemyBase.brain.root.ain
                    # - UtilityAinPath: Work/AI/Root/EnemyBase.utility.root.ain


    return ainbwindow


def add_ainb_nodes(ainb: AINB, ainb_location: AinbIndexCacheEntry, node_editor):
    from app_ainb_cache import scoped_ainbfile_lookup  # circular ImportError time, lol python
    aj = ainb.output_dict  # ainb json. we call him aj
    ainb_tag_ns = f"{node_editor}/ainb0"

    # We can't link nodes that don't exist yet
    deferred_link_calls: List[DeferredNodeLinkCall] = []

    # assume: `Node Index` always indexes into a sorted nonsparse `Nodes`
    aj_nodes = aj.get("Nodes", [])
    for aj_node in aj_nodes:
        node_i = aj_node["Node Index"]
        node_type = aj_node["Node Type"]
        node_name = aj_node["Name"]
        if node_type == "UserDefined":
            label = f'"{node_name}"({node_i})'
        elif node_name == "":
            label = f"{node_type}({node_i})"
        else:
            label = f"{node_type}({node_i}): {node_name}"
        # print(label, flush=True)

        # Legend:
        # _nnn per-mode-per-type counter on params, like ainb indexing
        # @4 flags and node meta
        # $3 global params
        # #2 immediate params
        # I1 input params
        # O0 output params
        #
        # All node contents must be in an attribute, which can make things weird
        #
        # ainb tag tree:
        #     /node{int}: Map<int, node_tag_ns>, a namespace for each node
        #
        # Each node tag tree/ns contains:
        #     /Node: dpg.node
        #     /LinkTarget: dpg.node_attribute, used by flow control nodes to reference nodes they operate on
        #     /Params/Global Parameters/{str}: Map<str, dpg.node_attribute>
        #     /Params/Immediate Parameters/{str}: Map<str, dpg.node_attribute>
        #     /Params/Input Parameters/{str}: Map<str, dpg.node_attribute>
        #     /Params/Output Parameters/{str}: Map<str, dpg.node_attribute>
        #     optional /stdlink{int}: Map<int, dpg.node_attribute>, Standard Link
        #     optional /reslink{int}: Map<int, dpg.node_attribute>, Resident Update Link

        node_tag_ns = f"{ainb_tag_ns}/node{node_i}"
        with dpg.node(tag=f"{node_tag_ns}/Node", label=label, parent=node_editor) as node_tag:
            with dpg.node_attribute(tag=f"{node_tag_ns}/LinkTarget", attribute_type=dpg.mvNode_Attr_Input):
                for command_i, command in enumerate(aj.get("Commands", [])):
                    if node_i == command["Left Node Index"]:
                        cmd_name = command["Name"]
                        dpg.add_text(f"@ Command[{cmd_name}]")

                for aj_flag in aj_node.get("Flags", []):
                    if aj_flag == "Is External AINB":
                        for aref in aj["Embedded AINB Files"]:
                            if aref["File Path"] != aj_node["Name"] + ".ainb":
                                continue

                            #print(aref["Count"]) ...instance/link count? TODO

                            # Try to resolve local pack -> global pack -> global Bare
                            dest_ainbfile = aref["File Category"] + '/' + aref["File Path"]
                            dest_location = scoped_ainbfile_lookup(AinbIndexCacheEntry(ainbfile=dest_ainbfile, packfile=ainb_location.packfile))
                            with dpg.group(horizontal=True):
                                dpg.add_text(f'@ ExternalAINB[{aref["File Category"]}] {aref["File Path"]}')
                                dpg.add_button(label="Open AINB", user_data=dest_location, callback=open_ainb_graph_window, arrow=True, direction=dpg.mvDir_Right)
                    else:
                        dpg.add_text(f"@ {aj_flag}")

            for aj_type, aj_params in aj_node.get("Immediate Parameters", {}).items():
                for aj_param in aj_params:
                    k = str(aj_param.get("Name"))
                    v = aj_param.get("Value")
                    ui_k = f"# {k}: {aj_type}"

                    with dpg.node_attribute(tag=f"{node_tag_ns}/Params/Immediate Parameters/{k}", attribute_type=dpg.mvNode_Attr_Static):
                        if aj_type == "int":
                            dpg.add_input_int(label=ui_k, width=80, default_value=v)
                        elif aj_type == "bool":
                            dpg.add_checkbox(label=ui_k, default_value=v)
                        elif aj_type == "float":
                            dpg.add_input_float(label=ui_k, width=100, default_value=v)
                        elif aj_type == "string":
                            dpg.add_input_text(label=ui_k, width=150, default_value=v)
                        elif aj_type == "vec3f":
                            # import pdb; pdb.set_trace()
                            dpg.add_input_text(label=ui_k, width=300, default_value=v)
                        elif aj_type == "userdefined":
                            dpg.add_input_text(label=ui_k, width=300, default_value=v)
                        else:
                            raise NotImplementedError(f"bruh typo in ur type {aj_type}")


            for aj_type, aj_params in aj_node.get("Input Parameters", {}).items():
                for aj_param in aj_params:
                    k = str(aj_param.get("Name"))
                    v = aj_param.get("Value")
                    param_attr_tag = f"{node_tag_ns}/Params/Input Parameters/{k}"
                    # TODO Global/EXB Index, Flags
                    # TODO node links: Node Index, Parameter Index
                    # or are these always the same as "Linked Nodes" "Output/bool Input/float Input Link"?
                    # when these point into precondition nodes, we don't always get the ^ link, so we need this?
                    # not choosing rn, so we get multiple links sometimes

                    input_link_node = aj_param.get("Node Index", -1)
                    input_link_param = aj_param.get("Parameter Index", -1)
                    if input_link_node > -1 and input_link_param > -1:
                        try:
                            _linked_params_of_type = aj_nodes[input_link_node]["Output Parameters"][aj_type]
                            param_name = _linked_params_of_type[input_link_param].get("Name", AppErrorStrings.FAILNULL)
                        except IndexError as e:
                            print(f"Link failure: {input_link_param} > {len(_linked_params_of_type)} in {param_attr_tag}? {e}")
                            # breakpoint()
                            param_name = AppErrorStrings.FAILNULL

                        dst_attr_tag = f"{ainb_tag_ns}/node{input_link_node}/Params/Output Parameters/{param_name}"

                        if "Is Precondition Node" in aj_nodes[input_link_node].get("Flags", []):
                            pass

                        deferred_link_calls.append(DeferredNodeLinkCall(
                            src_attr=param_attr_tag,
                            dst_attr=dst_attr_tag,
                            src_node_i=node_i,
                            dst_node_i=input_link_node,
                            parent=node_editor
                        ))
                    else:
                        # TODO is -100 special...?  but clearly we should link `Sources`
                        # if entry["Node Index"] <= -100 and entry["Node Index"] >= -8192:
                        #     entry["Multi Index"] = -100 - entry["Node Index"]
                        #     entry["Multi Count"] = entry["Parameter Index"]
                        # if input_link_node == -100: # what? eg Logic/A-1_2236.logic.root.ainb
                        # AI/PhantomGanon.metaai.root.json node 33 too. Which is its own precon?
                        # {'Name': 'BoolMulti', 'Node Index': -100, 'Parameter Index': 2, 'Value': False,
                        # 'Sources': [{'Node Index': 1, 'Parameter Index': 0}, {'Node Index': 3, 'Parameter Index': 2}]}
                        pass
                        #print(f"Unhandled Input Parameter: {aj_param}")


                    ui_k = f"I {k}: {aj_type}"

                    with dpg.node_attribute(tag=param_attr_tag, attribute_type=dpg.mvNode_Attr_Input):
                        if aj_type == "int":
                            dpg.add_input_int(label=ui_k, width=80, default_value=v)
                        elif aj_type == "bool":
                            dpg.add_checkbox(label=ui_k, default_value=v)
                        elif aj_type == "float":
                            dpg.add_input_float(label=ui_k, width=100, default_value=v)
                        elif aj_type == "string":
                            dpg.add_input_text(label=ui_k, width=150, default_value=v)
                        elif aj_type == "vec3f":
                            # import pdb; pdb.set_trace()
                            dpg.add_input_text(label=ui_k, width=300, default_value=v)
                        elif aj_type == "userdefined":
                            dpg.add_input_text(label=ui_k, width=300, default_value=v)
                        else:
                            raise NotImplementedError(f"bruh typo in ur type {aj_type}")


            for aj_type, aj_params in aj_node.get("Output Parameters", {}).items():
                # TODO Set Pointer Flag Bit Zero, maybe more
                for aj_param in aj_params:
                    param_name = aj_param.get("Name", AppErrorStrings.FAILNULL)
                    ui_name = f"O {param_name}: {aj_type}"
                    node_attr_tag = f"{node_tag_ns}/Params/Output Parameters/{param_name}"

                    try:
                        #print(node_attr_tag)
                        with dpg.node_attribute(tag=node_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
                            # not much to show unless we're planning to execute the graph?
                            dpg.add_text(ui_name)
                    except SystemError as e:
                        # FIXME eg Sequence/Amiibo.module.ainb has multiple Bool names so I misunderstood something
                        # let's not blow up the whole graph
                        # breakpoint()
                        print(f"Failed adding node_attribute {node_attr_tag} type {aj_type}: {e}")


            # aj_type = None  # TODO split shit up so we don't have to deal with leaked vars at least
            for aj_link_type, aj_links in aj_node.get("Linked Nodes", {}).items():
                for i_of_type, aj_link in enumerate(aj_links):
                    #print(aj_link_type, aj_link)
                    if aj_link_type == "Output/bool Input/float Input Link": # 0
                        # is_link_found = False
                        remote_i = dst_i = aj_link["Node Index"]
                        local_param_name = aj_link["Parameter"]  # May be input or output

                        # Find the local param being linked
                        local_type = None
                        local_param_direction = None  # "Output Parameters" or "Input Parameters"
                        local_i_of_type = None
                        parameter_index = None
                        local_param_node_index = None

                        for _local_type, local_params in aj_node.get("Input Parameters", {}).items():
                            for _i_of_type, local_param in enumerate(local_params):
                                if local_param["Name"] == local_param_name:
                                    local_type = _local_type
                                    local_param_direction = "Input Parameters"
                                    remote_param_direction = "Output Parameters"
                                    local_i_of_type = _i_of_type
                                    local_param_node_index = local_param["Node Index"]
                                    if local_param_node_index == -1:
                                        print(f"Unhandled -1 source node in Input Parameters - {aj_link_type}")
                                        pass # grabbing globals/exb???
                                        # continue 2?
                                    elif local_param_node_index in [-100, -110]:
                                        # Always multibool?
                                        len_of_nodeparams = local_param["Parameter Index"]  # unused?
                                        list_of_nodeparams = local_param["Sources"]
                                        for multi_item in list_of_nodeparams:
                                            multi_i = multi_item["Node Index"]
                                            multi_item_param_name = aj_nodes[multi_i]["Output Parameters"][local_type][multi_item["Parameter Index"]]["Name"]
                                            remote_multi_attr_tag = f"{ainb_tag_ns}/node{multi_i}/Params/Output Parameters/{multi_item_param_name}"
                                            my_attr_tag = f"{node_tag_ns}/Params/Input Parameters/{local_param_name}"
                                            deferred_link_calls.append(DeferredNodeLinkCall(
                                                src_attr=remote_multi_attr_tag,
                                                dst_attr=my_attr_tag,
                                                src_node_i=multi_i,
                                                dst_node_i=node_i,
                                                parent=node_editor
                                            ))
                                            # Return from this "Linked Nodes" item, no?
                                    else:
                                        if local_param_node_index != remote_i:
                                            breakpoint()
                                        assert local_param_node_index == remote_i
                                        parameter_index = local_param["Parameter Index"]

                        for _local_type, local_params in aj_node.get("Output Parameters", {}).items():
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
                        remote_params = aj_nodes[remote_i][remote_param_direction].get(remote_type, [])
                        if parameter_index is not None:
                            remote_param = remote_params[parameter_index]
                            remote_param_name = remote_param["Name"]
                        else:
                            for remote_param in remote_params:
                                # Pointing to our node?
                                if remote_param.get("Node Index") != node_i:
                                    continue

                                # Correct index into per-type param list?
                                if remote_param.get("Parameter Index") != local_i_of_type:
                                    continue

                                remote_param_name = remote_param["Name"]

                        my_attr_tag = f"{node_tag_ns}/Params/{local_param_direction}/{local_param_name}"
                        if remote_param_name is None and local_param_node_index < 0:
                            # return
                            pass # This is why multibool should return from "Linked Nodes" above...
                        elif remote_param_name is None and local_param_node_index > -1:
                            print(f"No remote param found for {my_attr_tag} in {aj_link}")
                        else:
                            remote_attr_tag = f"{ainb_tag_ns}/node{remote_i}/Params/{remote_param_direction}/{remote_param_name}"

                            # XXX is there anything more for when flags are precon, or was I just confused again
                            if local_param_direction == "Output Parameters":
                                deferred_link_calls.append(DeferredNodeLinkCall(
                                    src_attr=my_attr_tag,
                                    dst_attr=remote_attr_tag,
                                    src_node_i=node_i,
                                    dst_node_i=remote_i,
                                    parent=node_editor
                                ))
                            else:
                                deferred_link_calls.append(DeferredNodeLinkCall(
                                    src_attr=remote_attr_tag,
                                    dst_attr=my_attr_tag,
                                    src_node_i=remote_i,
                                    dst_node_i=node_i,
                                    parent=node_editor
                                ))

                    elif aj_link_type == "Standard Link": # 2
                        # refs to entire nodes for stuff like simultaneous, selectors.
                        # make new node attributes to support links to children.
                        dst_i = aj_link["Node Index"]
                        my_attr_tag = f"{node_tag_ns}/stdlink{i_of_type}"
                        dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/LinkTarget"

                        with dpg.node_attribute(tag=my_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
                            labels = []
                            if cname := aj_link.get("Connection Name"):
                                labels.append(cname)
                            if cond := aj_link.get("Condition"):
                                labels.append(f"Condition: {cond}")
                            label = ", ".join(labels) or f"[{aj_link_type}]"
                            dpg.add_text(label)

                        deferred_link_calls.append(DeferredNodeLinkCall(
                            src_attr=my_attr_tag,
                            dst_attr=dst_attr_tag,
                            src_node_i=node_i,
                            dst_node_i=dst_i,
                            parent=node_editor
                        ))

                    elif aj_link_type == "Resident Update Link": # 3
                        # pointers to params owned by other nodes? idk
                        # pulling in references to other nodes? idk
                        dst_i = aj_link["Node Index"]
                        my_attr_tag = f"{node_tag_ns}/reslink{i_of_type}"

                        # print(aj_link)

                        dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/LinkTarget" # TODO learn some things
                        # if dst_param_name := aj_link["Update Info"].get("String"):
                        #     # dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/Params/Input Parameters/{dst_param_name}"
                        #     # I don't understand how this String works, just point to the node for now.
                        #     dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/LinkTarget"
                        # else:
                        #     # Pointing into things like Element_Sequential or UDT @Is External AINB
                        #     # seem to not specify a String, so we'll just point at the node itself until
                        #     # this default/lhs/internal/??? param is better understood.
                        #     # The ResUpdate flags usually include "Is Valid Update" when this happens.
                        #     dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/LinkTarget"

                        with dpg.node_attribute(tag=my_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
                            flags = aj_link["Update Info"]["Flags"]
                            flags = "|".join((" ".join(flags)).split())  # bad ainb parse?
                            label = f"[ResUpdate] ({flags})" if flags else "[ResUpdate]"
                            dpg.add_text(label)

                        deferred_link_calls.append(DeferredNodeLinkCall(
                            src_attr=my_attr_tag,
                            dst_attr=dst_attr_tag,
                            src_node_i=node_i,
                            dst_node_i=dst_i,
                            parent=node_editor
                        ))

                    elif aj_link_type == "String Input Link": # 4
                        pass
                    elif aj_link_type == "int Input Link": # 5
                        # just the opposite direction of type 0?
                        pass
                    else:
                        breakpoint()
                        raise NotImplementedError(f"bruh stink in ur link {aj_link_type}")

        # end with dpg.node
    # end for aj_node


    # All nodes+attributes exist, now we can link them
    node_max_depth_map = defaultdict(int)  # commands start at 0
    node_i_links = defaultdict(set)

    # Add links
    for link in deferred_link_calls:
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
    for command_i, command in enumerate(aj.get("Commands", [])):
        node_i = command["Left Node Index"]
        if node_i == -1:
            continue

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

