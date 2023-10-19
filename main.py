import json
import os
import pathlib
import sys
from typing import *
from dataclasses import dataclass
from collections import defaultdict

import dearpygui.dearpygui as dpg
from dt_ainb.ainb import AINB
from sarc import SARC
import zstandard as zstd


ROMFS_PATH = "romfs"
ZSDIC_FILENAME = f"{ROMFS_PATH}/Pack/ZsDic.pack.zs"
AINB_FILE_INDEX_FILE = "var/cache/ainb_file_index.json"


@dataclass
class AinbIndexCacheEntry:  # Basic info for each ainb file
    ainbfile: str # *.ainb, relative to romfs or pack root
    packfile: Optional[str] = None  # romfs relative .pack.zs containing ainbfile


def load_pack_zs_contents(filename: str, zstd_options: Dict) -> Dict[str, memoryview]:
    dctx = zstd.ZstdDecompressor(**zstd_options)
    archive = SARC(dctx.decompress(open(filename, "rb").read()))
    return { fn: archive.get_file_data(fn) for fn in sorted(archive.list_files()) }


def get_pack_zs_filenames(filename: str, zstd_options: Dict) -> List[str]:
    dctx = zstd.ZstdDecompressor(**zstd_options)
    archive = SARC(dctx.decompress(open(filename, "rb").read()))
    return sorted(archive.list_files())


def open_ainb_index_window():
    zsdics = { fn: zstd.ZstdCompressionDict(data) for fn, data in load_pack_zs_contents(ZSDIC_FILENAME, {}).items() }
    pack_zstd_options = { "dict_data": zsdics["pack.zsdic"], }

    # input_filename = f"{ROMFS_PATH}/Pack/Actor/DungeonBoss_Rito_EventStarter.pack.zs"
    # test_pack_contents = load_pack_zs_contents(input_filename, pack_zstd_options)
    # dctx = zstd.ZstdDecompressor(**pack_zstd_options)
    # archive = SARC(dctx.decompress(open(input_filename, "rb").read()))
    #test_pack_filenames = get_pack_zs_filenames(input_filename, pack_zstd_options)
    # [str(x) for x in pathlib.Path("romfs/Logic").rglob("*.ainb") ]
    #ainb = AINB(open(filename, "rb").read())

    # 100% viewport height how?
    with dpg.window(label="AINB Index", pos=[0, 0], width=300, height=1080, no_close=True, no_collapse=True, no_move=True) as ainb_index_window:

        def callback_open_ainb(s, a, u):
            textitem = a[1]
            ainb_location: AinbIndexCacheEntry = dpg.get_item_user_data(textitem)
            open_ainb_window(s, None, ainb_location)

        with dpg.item_handler_registry(tag="ainb_index_window_handler") as open_ainb_handler:
            dpg.add_item_clicked_handler(callback=callback_open_ainb)

        # filtering, optional abc group trees, etc would be nice
        with dpg.tree_node(label="AI"):
            for ainbfile in pathlib.Path(f"{ROMFS_PATH}/AI").rglob("*.ainb"):
                ainb_location = AinbIndexCacheEntry(str(ainbfile))
                item = dpg.add_text(ainbfile.name, user_data=ainb_location)
                dpg.bind_item_handler_registry(item, open_ainb_handler)

        with dpg.tree_node(label="Logic"):
            for ainbfile in pathlib.Path(f"{ROMFS_PATH}/Logic").rglob("*.ainb"):
                ainb_location = AinbIndexCacheEntry(str(ainbfile))
                item = dpg.add_text(ainbfile.name, user_data=ainb_location)
                dpg.bind_item_handler_registry(item, open_ainb_handler)

        with dpg.tree_node(label="Sequence"):
            for ainbfile in pathlib.Path(f"{ROMFS_PATH}/Sequence").rglob("*.ainb"):
                ainb_location = AinbIndexCacheEntry(str(ainbfile))
                item = dpg.add_text(ainbfile.name, user_data=ainb_location)
                dpg.bind_item_handler_registry(item, open_ainb_handler)


        ainb_cache = {"Pack": {}} # cache format: {"Pack": {AinbIndexCacheEntry.packfile: List[AinbIndexCacheEntry]}}
        should_walk_packs = True
        try:
            ainb_cache = json.load(open(AINB_FILE_INDEX_FILE, "r"))
            if "Pack" not in ainb_cache:
                ainb_cache["Pack"] = {}
            for packfile, json_entries in ainb_cache["Pack"].items():
                # Rewrite in-place with dataclasses
                ainb_cache["Pack"][packfile] = [AinbIndexCacheEntry(**kw) for kw in json_entries]
        except FileNotFoundError:
            pass

        pack_hit = 0
        pack_total = 0
        if should_walk_packs:
            dctx = zstd.ZstdDecompressor(**pack_zstd_options)
            with dpg.tree_node(label="Pack/AI.Global.Product.100.pack.zs/AI"):
                print("Finding Pack/AI.Global.Product.100.pack.zs/AI/* AINBs: ", end='', flush=True)
                log_feedback_letter = ''

                packfile = f"{ROMFS_PATH}/Pack/AI.Global.Product.100.pack.zs"
                cached_ainb_locations = ainb_cache["Pack"].get(str(packfile), None)  # no [] default = negative cache
                if cached_ainb_locations is None:
                    archive = SARC(dctx.decompress(open(packfile, "rb").read()))
                    ainbfiles = [f for f in sorted(archive.list_files()) if f.endswith(".ainb")]
                    cached_ainb_locations = ainb_cache["Pack"][str(packfile)] = [AinbIndexCacheEntry(f, packfile=str(packfile)) for f in ainbfiles]
                else:
                    pack_hit += 1
                pack_total += 1

                ainbcount = len(cached_ainb_locations)
                # if ainbcount == 0:
                #     continue

                packname = pathlib.Path(packfile).name.rsplit(".pack.zs", 1)[0]

                if log_feedback_letter != packname[0]:
                    log_feedback_letter = packname[0]
                    print(log_feedback_letter, end='', flush=True)

                for ainb_location in cached_ainb_locations:
                    label = pathlib.Path(ainb_location.ainbfile).name
                    item = dpg.add_text(label, user_data=ainb_location)
                    dpg.bind_item_handler_registry(item, open_ainb_handler)
                print("")  # \n

            with dpg.tree_node(label="Pack/Actor/*.pack.zs"):
                print("Finding Pack/Actor/* AINBs: ", end='', flush=True)
                log_feedback_letter = ''

                for packfile in sorted(pathlib.Path(f"{ROMFS_PATH}/Pack/Actor").rglob("*.pack.zs")):
                    cached_ainb_locations = ainb_cache["Pack"].get(str(packfile), None)  # no [] default = negative cache
                    if cached_ainb_locations is None:
                        archive = SARC(dctx.decompress(open(packfile, "rb").read()))
                        ainbfiles = [f for f in sorted(archive.list_files()) if f.endswith(".ainb")]
                        cached_ainb_locations = ainb_cache["Pack"][str(packfile)] = [AinbIndexCacheEntry(f, packfile=str(packfile)) for f in ainbfiles]
                    else:
                        pack_hit += 1
                    pack_total += 1

                    ainbcount = len(cached_ainb_locations)
                    if ainbcount == 0:
                        continue

                    packname = pathlib.Path(packfile).name.rsplit(".pack.zs", 1)[0]
                    label = f"{packname} [{ainbcount}]"

                    if log_feedback_letter != packname[0]:
                        log_feedback_letter = packname[0]
                        print(log_feedback_letter, end='', flush=True)

                    with dpg.tree_node(label=label, default_open=(ainbcount <= 4)):
                        for ainb_location in cached_ainb_locations:
                            item = dpg.add_text(ainb_location.ainbfile, user_data=ainb_location)
                            dpg.bind_item_handler_registry(item, open_ainb_handler)

            if pack_hit < pack_total:
                print(f" ...saving {pack_total-pack_hit} to cache", end='')
                out = json.dumps(ainb_cache, default=vars, indent=4)
                with open(AINB_FILE_INDEX_FILE, "w") as outfile:
                    outfile.write(out)
            print(f" ({pack_total} total)", flush=True)

    return ainb_index_window


@dataclass
class DeferredNodeLinkCall:
    src_attr: str
    dst_attr: str
    src_node_i: int
    dst_node_i: int
    parent: Union[int, str]


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
    ainb_tag_ns = f"{node_editor}/ainb0"

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


def open_ainb_window(s, a, ainb_location: AinbIndexCacheEntry):
    if ainb_location.packfile is None:
        ainb = AINB(open(ainb_location.ainbfile, "rb").read())
        window_label = pathlib.Path(ainb_location.ainbfile).name
    else:
        # XXX maybe don't copypaste me, also better ctx mgmt
        zsdics = { fn: zstd.ZstdCompressionDict(data) for fn, data in load_pack_zs_contents(ZSDIC_FILENAME, {}).items() }
        pack_zstd_options = { "dict_data": zsdics["pack.zsdic"], }
        dctx = zstd.ZstdDecompressor(**pack_zstd_options)
        archive = SARC(dctx.decompress(open(ainb_location.packfile, "rb").read()))
        packname = pathlib.Path(ainb_location.packfile).name.rsplit(".pack.zs", 1)[0]
        ainb = AINB(archive.get_file_data(ainb_location.ainbfile))
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


def main():
    dpg.create_context()

    with dpg.font_registry():
        default_font = dpg.add_font("static/fonts/SourceCodePro-Regular.otf", 16)
    dpg.bind_font(default_font)

    # TODO: infer romfs root from argv filename?
    # EXAMPLE_AINBFILE = "romfs/Sequence/AutoPlacement.root.ainb"
    EXAMPLE_AINBFILE = "romfs/Sequence/ShortCutPauseOn.module.ainb"
    use_ainbfile = sys.argv[-1] if str(sys.argv[-1]).endswith(".ainb") else None
    if use_ainbfile:
        open_ainb_window(None, None, AinbIndexCacheEntry(use_ainbfile))

    ainb_index_window = open_ainb_index_window()

    # import dearpygui.demo as demo
    # demo.show_demo()

    # dpg.set_primary_window(ainb_index_window, True)
    dpg.create_viewport(title="ainb offline", x_pos=0, y_pos=0, width=1600, height=1080, decorated=True, vsync=True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.maximize_viewport()
    dpg.show_viewport(maximized=True)
    dpg.destroy_context()


if __name__ == "__main__":
    main()
