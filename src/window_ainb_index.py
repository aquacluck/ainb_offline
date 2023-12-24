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

    with dpg.window() as primary_window:
        with dpg.child_window(label="AINB Index", pos=[0, 0], width=400, autosize_y=True) as ainb_index_window:

            def callback_open_ainb(s, a, u):
                textitem = a[1]
                ainb_location: AinbIndexCacheEntry = dpg.get_item_user_data(textitem)
                open_ainb_graph_window(None, None, ainb_location)

            with dpg.item_handler_registry(tag="ainb_index_window_handler") as open_ainb_handler:
                dpg.add_item_clicked_handler(callback=callback_open_ainb)

            with dpg.tab_bar():
                # dpg.add_tab_button(label="[max]", callback=dpg.maximize_viewport)  # works at runtime, fails at init?
                # dpg.add_tab_button(label="wipe cache")
                # filtering, optional abc group trees, etc would be nice

                for cat in ("AI", "Logic", "Sequence"):
                    with dpg.tab(label=cat):
                        with dpg.child_window(tag=f"{ainb_index_window}/Root/{cat}", autosize_x=True, autosize_y=True):
                            pass

                cached_ainb_locations = ainb_cache["Pack"].get("Root", {})
                for ainbfile, ainb_location in cached_ainb_locations.items():
                    p = pathlib.Path(ainb_location.ainbfile)
                    label = p.name
                    cat, _ = p.parts
                    item = dpg.add_text(label, user_data=ainb_location, parent=f"{ainb_index_window}/Root/{cat}")
                    dpg.bind_item_handler_registry(item, open_ainb_handler)

                with dpg.tab(label="Pack/AI.Global.Product.100"):
                    with dpg.child_window(autosize_x=True, autosize_y=True):
                        packfile = "Pack/AI.Global.Product.100.pack.zs"
                        cached_ainb_locations = ainb_cache["Pack"].get(packfile, {})
                        for ainbfile, ainb_location in cached_ainb_locations.items():
                            label = pathlib.Path(ainb_location.ainbfile).name
                            item = dpg.add_text(label, user_data=ainb_location)
                            dpg.bind_item_handler_registry(item, open_ainb_handler)

                with dpg.tab(label="Pack/Actor"):
                    with dpg.child_window(autosize_x=True, autosize_y=True):
                        for packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
                            romfs_relative: str = os.path.join(*packfile.parts[-3:])
                            cached_ainb_locations = ainb_cache["Pack"].get(romfs_relative, {})
                            ainbcount = len(cached_ainb_locations)
                            if ainbcount == 0:
                                continue
                            packname = pathlib.Path(romfs_relative).name.rsplit(".pack.zs", 1)[0]
                            label = f"{packname} [{ainbcount}]"
                            with dpg.tree_node(label=label, default_open=(ainbcount <= 4)):
                                for ainbfile, ainb_location in cached_ainb_locations.items():
                                    item = dpg.add_text(ainb_location.ainbfile, user_data=ainb_location, bullet=True)
                                    dpg.bind_item_handler_registry(item, open_ainb_handler)


    return primary_window
