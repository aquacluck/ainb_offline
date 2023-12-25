import json
import os
import pathlib
from typing import *

import dearpygui.dearpygui as dpg

import pack_util
from app_types import *
from app_ainb_cache import get_ainb_index
from window_ainb_graph import open_ainb_graph_window


def open_ainb_index_window():
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    ainb_cache = get_ainb_index()
    title_version = dpg.get_value(AppConfigKeys.TITLE_VERSION)
    global_packfile = TitleVersionAiGlobalPack[title_version]
    root_dirs = TitleVersionRootPackDirs[title_version]

    with dpg.window() as primary_window:
        with dpg.child_window(label="AINB Index", pos=[0, 0], width=400, autosize_y=True) as ainb_index_window:
            # Opening ainb windows
            with dpg.item_handler_registry(tag="ainb_index_window_handler") as open_ainb_handler:
                def callback_open_ainb(s, a, u):
                    textitem = a[1]
                    ainb_location: AinbIndexCacheEntry = dpg.get_item_user_data(textitem)
                    open_ainb_graph_window(None, None, ainb_location)
                dpg.add_item_clicked_handler(callback=callback_open_ainb)

            # Quick search
            actor_pack_n = -1
            def callback_filter(sender, filter_string):
                for cat in root_dirs:
                    dpg.set_value(f"{ainb_index_window}/Root/{cat}/Filter", filter_string)
                dpg.set_value(f"{ainb_index_window}/Global/Filter", filter_string)
                dpg.set_value(f"{ainb_index_window}/PackActor/Filter", filter_string)
                for i in range(actor_pack_n):
                    dpg.set_value(f"{ainb_index_window}/PackActor/{i}/Filter", filter_string)
            filter_input = dpg.add_input_text(label="Filter (inc, -exc)", callback=callback_filter)

            with dpg.tab_bar():
                # dpg.add_tab_button(label="[max]", callback=dpg.maximize_viewport)  # works at runtime, fails at init?
                # dpg.add_tab_button(label="wipe cache")
                for cat in root_dirs:
                    with dpg.tab(label=cat):
                        with dpg.child_window(tag=f"{ainb_index_window}/Root/{cat}", autosize_x=True, autosize_y=True):
                            with dpg.filter_set(tag=f"{ainb_index_window}/Root/{cat}/Filter"):
                                pass

                cached_ainb_locations = ainb_cache["Pack"].get("Root", {})
                for ainbfile, ainb_location in cached_ainb_locations.items():
                    p = pathlib.Path(ainb_location.ainbfile)
                    label = p.name
                    cat, _ = p.parts
                    item = dpg.add_text(label, user_data=ainb_location, parent=f"{ainb_index_window}/Root/{cat}/Filter", filter_key=ainb_location.ainbfile)
                    dpg.bind_item_handler_registry(item, open_ainb_handler)

                with dpg.tab(label=global_packfile[:-8]):
                    with dpg.child_window(autosize_x=True, autosize_y=True):
                        with dpg.filter_set(tag=f"{ainb_index_window}/Global/Filter"):
                            cached_ainb_locations = ainb_cache["Pack"].get(global_packfile, {})
                            for ainbfile, ainb_location in cached_ainb_locations.items():
                                label = pathlib.Path(ainb_location.ainbfile).name
                                item = dpg.add_text(label, user_data=ainb_location, filter_key=ainb_location.ainbfile)
                                dpg.bind_item_handler_registry(item, open_ainb_handler)

                with dpg.tab(label="Pack/Actor"):
                    with dpg.child_window(autosize_x=True, autosize_y=True):
                        with dpg.filter_set(tag=f"{ainb_index_window}/PackActor/Filter"):
                            for packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
                                romfs_relative: str = os.path.join(*packfile.parts[-3:])
                                cached_ainb_locations = ainb_cache["Pack"].get(romfs_relative, {})
                                ainbcount = len(cached_ainb_locations)
                                if ainbcount == 0:
                                    continue

                                packname = pathlib.Path(romfs_relative).name.rsplit(".pack.zs", 1)[0]
                                label = f"{packname} [{ainbcount}]"

                                # Glob-like formatting, but just a literal search key: a.pack.zs:{one,two}
                                filter_val = ",".join([al.ainbfile for al in cached_ainb_locations.values()])
                                filter_val = f"{packfile}:{{{filter_val}}}"
                                actor_pack_n += 1
                                with dpg.tree_node(label=label, default_open=(ainbcount <= 4), filter_key=filter_val):
                                    with dpg.filter_set(tag=f"{ainb_index_window}/PackActor/{actor_pack_n}/Filter"):
                                        for ainbfile, ainb_location in cached_ainb_locations.items():
                                            item = dpg.add_text(ainb_location.ainbfile, user_data=ainb_location, bullet=True, filter_key=ainb_location.fullfile)
                                            dpg.bind_item_handler_registry(item, open_ainb_handler)


    return primary_window
