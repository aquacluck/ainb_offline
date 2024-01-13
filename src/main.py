import os
import pathlib
import sys
from typing import *

import dearpygui.dearpygui as dpg

from . import app_ainb_cache
from .app_types import *
from . import db
from .edit_context import EditContext
from .ui.window_ainb_index import WindowAinbIndex
from .ui.window_sql_shell import WindowSqlShell


def init_fonts():
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


def init_romfs_version_detect():
    # Determine romfs title+version
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    title_version = os.environ.get("TITLE_VERSION")  # Set this to suppress probing {romfs}/RSDB
    title_version = TitleVersion.lookup(title_version) if title_version else None
    if not title_version:
        for tv in TitleVersion.all():
            if pathlib.Path(f"{romfs}/{tv.identifying_file}").exists():
                title_version = tv
                break
    if not title_version:
        raise Exception(f"Version detection failed for romfs={romfs}")
    with dpg.value_registry():
        print(f"Title version {title_version}")
        dpg.add_string_value(tag=AppConfigKeys.TITLE_VERSION, default_value=str(title_version))


def init_for_totk():
    # Stupid mapviz picker :D
    with dpg.texture_registry():
        width, height, channels, data = dpg.load_image("static/totkmap.png")
        dpg.add_static_texture(width=width, height=height, default_value=data, tag=AppStaticTextureKeys.TOTK_MAP_PICKER_250)


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

    init_fonts()
    init_romfs_version_detect()

    if TitleVersion.get().is_totk:
        init_for_totk()

    db.Connection.get()  # Bring up sqlite3
    app_ainb_cache.build_indexes_for_unknown_files() # Do any crawling/caching

    # Main ui
    with dpg.window() as primary_window:
        with dpg.menu_bar():
            with dpg.menu(label="Debug"):
                dpg.add_menu_item(label="Show Item Registry", callback=lambda: dpg.show_tool(dpg.mvTool_ItemRegistry))
                dpg.add_menu_item(label="Show Debug", callback=lambda: dpg.show_tool(dpg.mvTool_Debug))
                dpg.add_menu_item(label="Show Metrics", callback=lambda: dpg.show_tool(dpg.mvTool_Metrics))
                dpg.add_menu_item(label="Show Style Editor", callback=lambda: dpg.show_tool(dpg.mvTool_Style))
                dpg.add_menu_item(label="Show Font Manager", callback=lambda: dpg.show_tool(dpg.mvTool_Font))
                dpg.add_menu_item(label="Show SQL Shell", callback=lambda: WindowSqlShell.create_anon_oneshot("SELECT sql FROM sqlite_master;"))

        WindowAinbIndex.create_anon_oneshot()

    def resolve_argv_location() -> Optional[PackIndexEntry]:
        romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
        arg_location = str(sys.argv[-1])
        if extension := RomfsFileTypes.get_from_filename(arg_location):
            # Make path romfs-relative
            if arg_location.startswith(romfs):
                arg_location = arg_location[len(romfs):].lstrip("/")
            # Resolve "Pack/Name.pack.zs:AI/File.ainb" notation
            arg_location = arg_location.split(":")
            if len(arg_location) == 2:
                return PackIndexEntry(internalfile=arg_location[1], packfile=arg_location[0], extension=extension)
            elif len(arg_location) == 1:
                return PackIndexEntry(internalfile=arg_location[0], packfile="Root", extension=extension)
            else:
                raise ValueError(f"Unparsable path {arg_location}")

    def after_first_frame():
        dpg.maximize_viewport()
        if open_location := resolve_argv_location():
            EditContext.get().open_ainb_window(open_location)

    dpg.set_primary_window(primary_window, True)
    dpg.create_viewport(title="ainb offline", x_pos=0, y_pos=0, width=1600, height=1080, decorated=True, vsync=True)

    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_frame_callback(1, lambda: after_first_frame())

    dpg.start_dearpygui() # dpg loop runs...
    dpg.destroy_context()

