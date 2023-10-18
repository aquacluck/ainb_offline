import sys
#from dataclasses import dataclass
import json

import dearpygui.dearpygui as dpg
from dt_ainb.ainb import AINB


#@dataclass
#class AINBNodeLink:
#    linktag: str
#    # needs a self.tag for the imnode link tag itself
#    # accumulate AINBNodeLinks via ainbnodeids while adding nodes,
#    # then add links populating linktag/self.tag last.
#    # hold link metadata, link type+bidirectionality+etc
#    #tagfrom = "mynodeeditor/node/attribute/linkorsomething"
#    #tagto = "$otherattribute"
#    tagto: str


#@dataclass
#class AINBNodeMeta:
#    # lol i dunno
#    imnodeid: int
#    is_root: bool
#    is_command: bool
#    left_i: int
#    right_i: int


def add_ainb_nodes(ainb: AINB, node_editor):
    aj = ainb.output_dict  # ainb json. we call him aj

    # nodemetas = []  # accumulate which nodes are roots/commands/???
    # for command in aj.get("Commands", []):
    #     meta = AINBNodeMeta(
    #         imnodeid=None,
    #         is_command=True,
    #         command_name
    #         is_root=command["Name"] == "Root",
    #         left=command["Left Node Index"],
    #         right=command["Right Node Index"],
    #     )
    #     nodemetas.append(meta)

    # We can't link nodes that don't exist yet
    deferred_link_calls = []
    def accumulate_add_node_link(*args, **kwargs):
        deferred_link_calls.append((args, kwargs))

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

        ainb_tag_ns = f"{node_editor}/ainb0"
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
                            import pdb; pdb.set_trace()
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
                        # dest_attr_tag = f"{ainb_tag_ns}/node{dest_i}/Params/Input"
                        param_name = aj_nodes[input_link_node]["Output Parameters"][aj_type][input_link_param]["Name"]
                        dest_attr_tag = f"{ainb_tag_ns}/node{input_link_node}/Params/{param_name}"
                        my_attr_tag = f"{node_tag_ns}/Params/{k}"
                        accumulate_add_node_link(param_attr_tag, dest_attr_tag, parent=node_editor)


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
                            import pdb; pdb.set_trace()
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
                        dest_i = aj_link["Node Index"]
                        link_param = aj_link["Parameter"]
                        dest_attr_tag = f"{ainb_tag_ns}/node{dest_i}/Params/Input"
                        my_attr_tag = f"{node_tag_ns}/Params/{link_param}"
                        #import pdb; pdb.set_trace()
                        # probably not right lol
                        if not "Is Precondition Node" in aj_nodes[dest_i]["Flags"]:
                            accumulate_add_node_link(my_attr_tag, dest_attr_tag, parent=node_editor)

                    elif aj_link_type == "Standard Link": # 2
                        # refs to entire nodes for stuff like simultaneous, selectors.
                        # make new node attributes to support links to children.
                        dest_i = aj_link["Node Index"]
                        my_attr_tag = f"{node_tag_ns}/stdlink{i_of_type}"
                        dest_attr_tag = f"{ainb_tag_ns}/node{dest_i}/LinkTarget"

                        with dpg.node_attribute(tag=my_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
                            labels = []
                            if cname := aj_link.get("Connection Name"):
                                labels.append(cname)
                            if cond := aj_link.get("Condition"):
                                labels.append(f"Condition: {cond}")
                            label = ", ".join(labels) or f"[{aj_link_type}]"
                            dpg.add_text(label)

                        accumulate_add_node_link(my_attr_tag, dest_attr_tag, parent=node_editor)

                    elif aj_link_type == "Resident Update Link": # 3
                        # pointers to params owned by other nodes? idk
                        # pulling in references to other nodes? idk
                        dest_i = aj_link["Node Index"]
                        my_attr_tag = f"{node_tag_ns}/reslink{i_of_type}"

                        print(aj_link)

                        dest_attr_tag = f"{ainb_tag_ns}/node{dest_i}/LinkTarget" # TODO learn some things
                        # if dest_param_name := aj_link["Update Info"].get("String"):
                        #     # dest_attr_tag = f"{ainb_tag_ns}/node{dest_i}/Params/{dest_param_name}"
                        #     # I don't understand how this String works, just point to the node for now.
                        #     dest_attr_tag = f"{ainb_tag_ns}/node{dest_i}/LinkTarget"
                        # else:
                        #     # Pointing into things like Element_Sequential or UDT @Is External AINB
                        #     # seem to not specify a String, so we'll just point at the node itself until
                        #     # this default/lhs/internal/??? param is better understood.
                        #     # The ResUpdate flags usually include "Is Valid Update" when this happens.
                        #     dest_attr_tag = f"{ainb_tag_ns}/node{dest_i}/LinkTarget"

                        with dpg.node_attribute(tag=my_attr_tag, attribute_type=dpg.mvNode_Attr_Output):
                            flags = aj_link["Update Info"]["Flags"]
                            flags = "|".join((" ".join(flags)).split())  # bad ainb parse?
                            label = f"[ResUpdate] ({flags})" if flags else "[ResUpdate]"
                            dpg.add_text(label)

                        accumulate_add_node_link(my_attr_tag, dest_attr_tag, parent=node_editor)

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
    for (link_args, link_kwargs) in deferred_link_calls:
        # TODO: - store link calls differently or just parse them here, so we can get at node ids.
        #       - x axis: bucket nodes by max link depth, try 1000px*depth pos on x axis?
        #       - y axis: rough sort nodes within each depth-bucket for decent proximity+aesthetics.
        #                 also try to add gaps between shallower nodes to make room for deeper nodes.
        #                 we can count node attributes to estimate height if it's unavailable?
        print(link_args, link_kwargs)
        dpg.add_node_link(*link_args, **link_kwargs)


def open_ainb_window(s, a, filename):
    ainb = AINB(open(filename, "rb").read())
    with dpg.window() as ainbwindow:
        def dump_json():
            print(json.dumps(ainb.output_dict, indent=4))
        def link_callback(sender, app_data):
            dpg.add_node_link(app_data[0], app_data[1], parent=sender)
        def delink_callback(sender, app_data):
            dpg.delete_item(app_data)

        dpg.add_text(filename)
        dpg.add_button(label="print state", callback=dump_json)
        node_editor = dpg.add_node_editor(callback=link_callback, delink_callback=delink_callback, minimap=True, minimap_location=dpg.mvNodeMiniMap_Location_BottomRight)
        add_ainb_nodes(ainb, node_editor)

    return ainbwindow


def main():
    dpg.create_context()

    with dpg.font_registry():
        default_font = dpg.add_font("static/fonts/SourceCodePro-Regular.otf", 20)
    dpg.bind_font(default_font)

    # EXAMPLE_AINBFILE = "romfs/Sequence/AutoPlacement.root.ainb"
    EXAMPLE_AINBFILE = "romfs/Sequence/ShortCutPauseOn.module.ainb"
    use_ainbfile = sys.argv[-1] if str(sys.argv[-1]).endswith(".ainb") else EXAMPLE_AINBFILE

    print(use_ainbfile)
    ainbwindow = open_ainb_window(None, None, use_ainbfile)

    dpg.set_primary_window(ainbwindow, True)
    dpg.create_viewport(title="ainb offline", x_pos=0, y_pos=0, width=1600, height=1080, decorated=True, vsync=True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.maximize_viewport()
    dpg.show_viewport(maximized=True)
    dpg.destroy_context()


if __name__ == "__main__":
    main()
