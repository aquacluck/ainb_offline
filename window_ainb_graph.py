import json
import pathlib
from typing import *
from collections import defaultdict

import dearpygui.dearpygui as dpg
from dt_ainb.ainb import AINB

import pack_util
from app_types import *


def open_ainb_graph_window(s, a, ainb_location: AinbIndexCacheEntry):
    # TODO: consistent title: [A] [L] [S] typeflag? romfs path? pack+internal path? idk yet
    if ainb_location.packfile is None:
        ainb = AINB(open(ainb_location.ainbfile, "rb").read())
        window_label = pathlib.Path(ainb_location.ainbfile).name
    else:
        ainb = AINB(pack_util.load_file_from_pack(ainb_location.packfile, ainb_location.ainbfile))
        packname = pathlib.Path(ainb_location.packfile).name.rsplit(".pack.zs", 1)[0]
        window_label = f"Pack/Actor/{packname}/{ainb_location.ainbfile}"

    with dpg.window(label=window_label, width=800, height=600, pos=[600, 200]) as ainbwindow:
        def dump_json():
            print(json.dumps(ainb.output_dict, indent=4))
        def link_callback(sender, app_data):
            dpg.add_node_link(app_data[0], app_data[1], parent=sender)
        def delink_callback(sender, app_data):
            dpg.delete_item(app_data)

        # dpg.add_button(label="print state", callback=dump_json)
        node_editor = dpg.add_node_editor(callback=link_callback, delink_callback=delink_callback, minimap=True, minimap_location=dpg.mvNodeMiniMap_Location_BottomRight)
        add_ainb_nodes(ainb, node_editor)

    return ainbwindow


def add_ainb_nodes(ainb: AINB, node_editor):
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

        # Legend:
        # @ flags and node meta
        # # immediate params
        # & input params
        # * output params
        #
        # We're doing this because collapsible sections etc don't work:
        # https://github.com/Nelarius/imnodes#known-issues
        #
        # Also all node contents must be in an attribute, which can make things weird
        #
        # ainb tag tree:
        #     /node{int}: Map<int, node_tag_ns>, a namespace for each node
        #
        # Each node tag tree/ns contains:
        #     /Node: dpg.node
        #     /LinkTarget: dpg.node_attribute, used by flow control nodes to reference nodes they operate on
        #     /Params/{str}: Map<str, dpg.node_attribute>, namespace for all parameters
        #     optional /stdlink{int}: Map<int, dpg.node_attribute>, Standard Link
        #     optional /reslink{int}: Map<int, dpg.node_attribute>, Resident Update Link

        node_tag_ns = f"{ainb_tag_ns}/node{node_i}"
        with dpg.node(tag=f"{node_tag_ns}/Node", label=label, parent=node_editor) as node_tag:
            with dpg.node_attribute(tag=f"{node_tag_ns}/LinkTarget", attribute_type=dpg.mvNode_Attr_Input):

                def scoot(sender, app_data, node_tag):
                    print("scoot", sender, app_data, node_tag)
                    pos = dpg.get_item_pos(node_tag)
                    pos[0] += 1000  # grid of 1000 seems ok?
                    # less would be nice but need to wrap/format flags+filename, they wide
                    dpg.set_item_pos(node_tag, pos)
                # dpg.add_button(label="hi", callback=scoot, user_data=node_tag)

                for command_i, command in enumerate(aj.get("Commands", [])):
                    if node_i == command["Left Node Index"]:
                        cmd_name = command["Name"]
                        dpg.add_text(f"@Command({cmd_name})")
                for aj_flag in aj_node.get("Flags", []):
                    dpg.add_text(f"@{aj_flag}")

            for aj_type, aj_params in aj_node.get("Immediate Parameters", {}).items():
                for aj_param in aj_params:
                    k = str(aj_param.get("Name"))
                    v = aj_param.get("Value")
                    # assume: param names of different input/output/etc types must still be unique
                    #attr_tag = f"{node_editor}/ainb0/node{node_i}/immediate/{aj_type}/{k}"
                    ui_k = f"#{k}: {aj_type}"

                    with dpg.node_attribute(tag=f"{node_tag_ns}/Params/{k}", attribute_type=dpg.mvNode_Attr_Static):
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
                    param_attr_tag = f"{node_tag_ns}/Params/{k}"
                    # TODO Global/EXB Index, Flags
                    # TODO node links: Node Index, Parameter Index
                    # or are these always the same as "Linked Nodes" "Output/bool Input/float Input Link"?
                    # when these point into precondition nodes, we don't always get the ^ link, so we need this?
                    # not choosing rn, so we get multiple links sometimes

                    input_link_node = aj_param.get("Node Index", -1)
                    input_link_param = aj_param.get("Parameter Index", -1)
                    if input_link_node != -1 and input_link_param != -1:
                        # dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/Params/Input"
                        param_name = aj_nodes[input_link_node]["Output Parameters"][aj_type][input_link_param]["Name"]
                        dst_attr_tag = f"{ainb_tag_ns}/node{input_link_node}/Params/{param_name}"

                        if "Is Precondition Node" in aj_nodes[input_link_node].get("Flags", []):
                            pass

                        deferred_link_calls.append(DeferredNodeLinkCall(
                            src_attr=param_attr_tag,
                            dst_attr=dst_attr_tag,
                            src_node_i=node_i,
                            dst_node_i=input_link_node,
                            parent=node_editor
                        ))


                    ui_k = f"&{k}: {aj_type}"

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
                for aj_param in aj_params:
                    k = str(aj_param.get("Name"))
                    # TODO Set Pointer Flag Bit Zero, maybe more
                    ui_k = f"*{k}: {aj_type}"

                    with dpg.node_attribute(tag=f"{node_tag_ns}/Params/{k}", attribute_type=dpg.mvNode_Attr_Output):
                        # not much to show unless we're planning to execute the graph?
                        dpg.add_text(ui_k)


            for aj_link_type, aj_links in aj_node.get("Linked Nodes", {}).items():
                for i_of_type, aj_link in enumerate(aj_links):
                    #print(aj_link_type, aj_link)
                    if aj_link_type == "Output/bool Input/float Input Link": # 0
                        dst_i = aj_link["Node Index"]
                        link_param = aj_link["Parameter"]
                        dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/Params/Input"
                        my_attr_tag = f"{node_tag_ns}/Params/{link_param}"
                        #import pdb; pdb.set_trace()
                        # probably not right lol
                        if not "Is Precondition Node" in aj_nodes[dst_i].get("Flags", []):
                            deferred_link_calls.append(DeferredNodeLinkCall(
                                src_attr=my_attr_tag,
                                dst_attr=dst_attr_tag,
                                src_node_i=node_i,
                                dst_node_i=dst_i,
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

                        print(aj_link)

                        dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/LinkTarget" # TODO learn some things
                        # if dst_param_name := aj_link["Update Info"].get("String"):
                        #     # dst_attr_tag = f"{ainb_tag_ns}/node{dst_i}/Params/{dst_param_name}"
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
                        raise NotImplementedError(f"bruh stink in ur link {aj_link_type}")

        # end with dpg.node
    # end for aj_node


    # All nodes+attributes exist, now we can link them
    node_max_depth_map = defaultdict(int)  # commands start at 0
    node_i_links = defaultdict(set)

    # Add links
    for link in deferred_link_calls:
        dpg.add_node_link(link.src_attr, link.dst_attr, parent=link.parent)
        node_i_links[link.src_node_i].add(link.dst_node_i)

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

    # Layout
    node_y_at_depth = defaultdict(int)
    for node_i, max_depth in node_max_depth_map.items():
        node_tag = f"{ainb_tag_ns}/node{node_i}/Node"
        node_y_at_depth[max_depth] += 1
        y = 500*node_y_at_depth[max_depth]
        pos = [800*max_depth, y]
        # print(node_tag, pos)
        dpg.set_item_pos(node_tag, pos)
