import os
import sys
from typing import *

import dearpygui.dearpygui as dpg

from app_types import *
from window_ainb_index import open_ainb_index_window
from window_ainb_graph import open_ainb_graph_window


def main():
    dpg.create_context()

    # const globals+config
    with dpg.value_registry():
        _romfs = os.environ.get("ROMFS") or "romfs"
        dpg.add_string_value(tag=AppConfigKeys.ROMFS_PATH, default_value=_romfs)
        dpg.add_string_value(tag=AppConfigKeys.ZSDIC_FILENAME, default_value=f"{dpg.get_value(AppConfigKeys.ROMFS_PATH)}/Pack/ZsDic.pack.zs")

        _var = os.environ.get("APPVAR") or "var"
        dpg.add_string_value(tag=AppConfigKeys.APPVAR_PATH, default_value=_var)
        dpg.add_string_value(tag=AppConfigKeys.AINB_FILE_INDEX_FILE, default_value=f"{dpg.get_value(AppConfigKeys.APPVAR_PATH)}/cache/ainb_file_index.json")

        _modfs = os.environ.get("OUTPUT_ROMFS") or "var/modfs"
        dpg.add_string_value(tag=AppConfigKeys.MODFS_PATH, default_value=_modfs)

    with dpg.font_registry():
        default_font = dpg.add_font("static/fonts/SourceCodePro-Regular.otf", 16)
    dpg.bind_font(default_font)

    ainb_index_window = open_ainb_index_window()

    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    use_ainbfile = sys.argv[-1] if str(sys.argv[-1]).endswith(".ainb") else None
    if use_ainbfile:
        use_ainbfile = use_ainbfile[len(romfs):].lstrip("/") if use_ainbfile.startswith(romfs) else use_ainbfile
        open_ainb_graph_window(None, None, AinbIndexCacheEntry(ainbfile=use_ainbfile, packfile="Root"))

    # import dearpygui.demo as demo
    # demo.show_demo()

    dpg.set_primary_window(ainb_index_window, True)
    dpg.create_viewport(title="ainb offline", x_pos=0, y_pos=0, width=1600, height=1080, decorated=True, vsync=True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.maximize_viewport()
    dpg.show_viewport(maximized=True)
    dpg.destroy_context()


if __name__ == "__main__":
    main()
