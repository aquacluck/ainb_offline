import os
import pathlib
import sys
from typing import *

import dearpygui.dearpygui as dpg

import db
from app_types import *
from window_ainb_index import open_ainb_index_window
from window_ainb_graph import open_ainb_graph_window
import edit_context


def main():
    dpg.create_context()

    # const globals+config
    with dpg.value_registry():
        _romfs = os.environ.get("ROMFS") or "romfs"
        dpg.add_string_value(tag=AppConfigKeys.ROMFS_PATH, default_value=_romfs)

        _var = os.environ.get("APPVAR") or "var"
        dpg.add_string_value(tag=AppConfigKeys.APPVAR_PATH, default_value=_var)

        _modfs = os.environ.get("OUTPUT_MODFS") or "var/modfs"
        dpg.add_string_value(tag=AppConfigKeys.MODFS_PATH, default_value=_modfs)


    # Font management
    with dpg.font_registry():
        # No JP support
        #default_font = dpg.add_font("static/fonts/SourceCodePro-Regular.otf", 16)

        # Excessive filesize
        with dpg.font("static/fonts/sarasa-term-j-regular.ttf", 16) as default_font:
            dpg.add_font_range_hint(dpg.mvFontRangeHint_Japanese)

        # 14 can be strenous to read, but useful in some conditions
        #with dpg.font("static/fonts/sarasa-term-j-regular.ttf", 14) as small_font:
        #    dpg.add_font_range_hint(dpg.mvFontRangeHint_Japanese)
    dpg.bind_font(default_font)


    # Determine romfs title+version
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    title_version = os.environ.get("TITLE_VERSION")  # Set this to suppress probing {romfs}/RSDB
    if not title_version:
        for tv in TitleVersions:
            file = TitleVersionIdentifyingFiles[tv]
            if pathlib.Path(f"{romfs}/{file}").exists():
                title_version = tv
                break
    if not title_version:
        raise Exception(f"Version detection failed for romfs={romfs}")
    with dpg.value_registry():
        print(f"Title version {title_version}")
        dpg.add_string_value(tag=AppConfigKeys.TITLE_VERSION, default_value=title_version)


    # Bring up sqlite3
    db.Connection.get()


    # Create edit context
    ectx = edit_context.EditContext()
    edit_context.active_ectx = ectx  # global via EditContext.get()


    # Stupid mapviz picker :D
    if TitleVersionIsTotk(dpg.get_value(AppConfigKeys.TITLE_VERSION)):
        with dpg.texture_registry():
            width, height, channels, data = dpg.load_image("static/totkmap.png")
            dpg.add_static_texture(width=width, height=height, default_value=data, tag=AppStaticTextureKeys.TOTK_MAP_PICKER_250)


    # Main ui
    with dpg.window() as primary_window:
        with dpg.menu_bar():
            with dpg.menu(label="Debug"):
                dpg.add_menu_item(label="Show Item Registry", callback=lambda: dpg.show_tool(dpg.mvTool_ItemRegistry))
                dpg.add_menu_item(label="Show Debug", callback=lambda: dpg.show_tool(dpg.mvTool_Debug))
                dpg.add_menu_item(label="Show Metrics", callback=lambda: dpg.show_tool(dpg.mvTool_Metrics))
                dpg.add_menu_item(label="Show Style Editor", callback=lambda: dpg.show_tool(dpg.mvTool_Style))
                dpg.add_menu_item(label="Show Font Manager", callback=lambda: dpg.show_tool(dpg.mvTool_Font))

        ainb_index_window = open_ainb_index_window()


    # Handle opening ainb from argv
    use_ainbfile = sys.argv[-1] if str(sys.argv[-1]).endswith(".ainb") else None
    if use_ainbfile:
        # Make path romfs-relative
        use_ainbfile = use_ainbfile[len(romfs):].lstrip("/") if use_ainbfile.startswith(romfs) else use_ainbfile
        # Resolve "Pack/Name.pack.zs:AI/File.ainb" notation
        use_ainbfile = use_ainbfile.split(":")
        if len(use_ainbfile) == 2:
            ainb_location = PackIndexEntry(internalfile=use_ainbfile[1], packfile=use_ainbfile[0], extension="ainb")
        elif len(use_ainbfile) == 1:
            ainb_location = PackIndexEntry(internalfile=use_ainbfile[0], packfile="Root", extension="ainb")
        else:
            raise ValueError(f"Unparsable path {use_ainbfile}")
        open_ainb_graph_window(None, None, ainb_location)


    # Hand over control to dpg's main loop
    dpg.set_primary_window(primary_window, True)
    dpg.create_viewport(title="ainb offline", x_pos=0, y_pos=0, width=1600, height=1080, decorated=True, vsync=True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.maximize_viewport()
    dpg.show_viewport(maximized=True)
    dpg.destroy_context()


if __name__ == "__main__":
    main()
