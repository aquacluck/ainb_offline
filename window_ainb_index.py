import json
import pathlib
from typing import *

import dearpygui.dearpygui as dpg

import pack_util
from app_types import *
from window_ainb_graph import open_ainb_graph_window


def open_ainb_index_window():
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)

    # 100% viewport height how?
    with dpg.window(label="AINB Index", pos=[0, 0], width=300, height=1080, no_close=True, no_collapse=True, no_move=True) as ainb_index_window:

        def callback_open_ainb(s, a, u):
            textitem = a[1]
            ainb_location: AinbIndexCacheEntry = dpg.get_item_user_data(textitem)
            open_ainb_graph_window(s, None, ainb_location)

        with dpg.item_handler_registry(tag="ainb_index_window_handler") as open_ainb_handler:
            dpg.add_item_clicked_handler(callback=callback_open_ainb)

        # filtering, optional abc group trees, etc would be nice
        with dpg.tree_node(label="AI"):
            for ainbfile in pathlib.Path(f"{romfs}/AI").rglob("*.ainb"):
                ainb_location = AinbIndexCacheEntry(str(ainbfile))
                item = dpg.add_text(ainbfile.name, user_data=ainb_location)
                dpg.bind_item_handler_registry(item, open_ainb_handler)

        with dpg.tree_node(label="Logic"):
            for ainbfile in pathlib.Path(f"{romfs}/Logic").rglob("*.ainb"):
                ainb_location = AinbIndexCacheEntry(str(ainbfile))
                item = dpg.add_text(ainbfile.name, user_data=ainb_location)
                dpg.bind_item_handler_registry(item, open_ainb_handler)

        with dpg.tree_node(label="Sequence"):
            for ainbfile in pathlib.Path(f"{romfs}/Sequence").rglob("*.ainb"):
                ainb_location = AinbIndexCacheEntry(str(ainbfile))
                item = dpg.add_text(ainbfile.name, user_data=ainb_location)
                dpg.bind_item_handler_registry(item, open_ainb_handler)


        ainb_file_index_file = dpg.get_value(AppConfigKeys.AINB_FILE_INDEX_FILE)
        ainb_cache = {"Pack": {}} # cache format: {"Pack": {AinbIndexCacheEntry.packfile: List[AinbIndexCacheEntry]}}
        should_walk_packs = True
        try:
            ainb_cache = json.load(open(ainb_file_index_file, "r"))
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
            with dpg.tree_node(label="Pack/AI.Global.Product.100.pack.zs/AI"):
                print("Finding Pack/AI.Global.Product.100.pack.zs/AI/* AINBs: ", end='', flush=True)
                log_feedback_letter = ''

                packfile = f"{romfs}/Pack/AI.Global.Product.100.pack.zs"
                cached_ainb_locations = ainb_cache["Pack"].get(str(packfile), None)  # no [] default = negative cache
                if cached_ainb_locations is None:
                    ainbfiles = [f for f in pack_util.get_pack_internal_filenames(packfile) if f.endswith(".ainb")]
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

                for packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
                    cached_ainb_locations = ainb_cache["Pack"].get(str(packfile), None)  # no [] default = negative cache
                    if cached_ainb_locations is None:
                        ainbfiles = [f for f in pack_util.get_pack_internal_filenames(packfile) if f.endswith(".ainb")]
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
                ainb_file_index_file = dpg.get_value(AppConfigKeys.AINB_FILE_INDEX_FILE)
                with open(ainb_file_index_file, "w") as outfile:
                    outfile.write(out)
            print(f" ({pack_total} total)", flush=True)

    return ainb_index_window
