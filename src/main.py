import inspect
import os
import pathlib
import sys
from typing import *

import dearpygui.dearpygui as dpg
from . import curio

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


async def init_main():
    dpg.create_context()
    dpg.configure_app(manual_callback_management=True)

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


async def init_basic_ui():
    with dpg.window() as primary_window:
        with dpg.menu_bar():
            with dpg.menu(label="Debug"):
                dpg.add_menu_item(label="Show Item Registry", callback=lambda: dpg.show_tool(dpg.mvTool_ItemRegistry))
                dpg.add_menu_item(label="Show Debug", callback=lambda: dpg.show_tool(dpg.mvTool_Debug))
                dpg.add_menu_item(label="Show Metrics", callback=lambda: dpg.show_tool(dpg.mvTool_Metrics))
                dpg.add_menu_item(label="Show Style Editor", callback=lambda: dpg.show_tool(dpg.mvTool_Style))
                dpg.add_menu_item(label="Show Font Manager", callback=lambda: dpg.show_tool(dpg.mvTool_Font))
                dpg.add_menu_item(
                    label="Show SQL Shell",
                    callback=CallbackReq.SpawnCoro(WindowSqlShell.create_as_coro, ["SELECT sql FROM sqlite_master;"])
                )

        await curio.spawn(WindowAinbIndex.create_as_coro, primary_window)

    dpg.set_primary_window(primary_window, True)
    dpg.create_viewport(title="ainb offline", x_pos=0, y_pos=0, width=1600, height=1080, decorated=True, vsync=True)
    dpg.setup_dearpygui()


async def after_first_frame():
    dpg.maximize_viewport()
    if open_location := resolve_argv_location():
        ectx = EditContext.get()
        req = CallbackReq.SpawnCoro(ectx.open_ainb_window_as_coro, [open_location])
        await ectx.dpg_callback_queue.put(req)


async def dpg_callback_consumer(queue):
    while True:
        #print(f'awaiting get {queue}')
        if job := await queue.get():
            #print(f"done got {job}")
            while job:
                # First normalize what we're getting
                if isinstance(job, tuple):
                    # This is what we get raw from dpg callbacks.
                    # DpgJob: var len 1-4 Tuple[callable, sender, app_data, user_data]
                    if job[0] and callable(job[0]):
                        dpg_callback, dpg_args = job[0], job[1:]
                    elif job[0] is None:
                        # Some args may be set, but there's no callable set, and they silently ignore it. idk whats going on
                        # https://github.com/hoffstadt/DearPyGui/blob/c9d6a91fd579c4b1d01c9835ecb3ad57449378c3/dearpygui/dearpygui.py#L53
                        job = None
                        continue  # break
                    else:
                        # Unknown, nop and scream
                        dpg_callback, dpg_args = None, None
                elif isinstance(job, CallbackReq.Base):
                    dpg_callback, dpg_args = job, []
                else:
                    # Unknown, nop and scream
                    dpg_callback, dpg_args = None, None

                # Then dispatch, maybe receiving chained cb
                if isinstance(dpg_callback, CallbackReq.SpawnCoro):
                    # We never actually join() these, curio screams a little but it doesn't really matter afaict
                    task: curio.Task = await curio.spawn(dpg_callback(*dpg_args))
                    job = None  # break
                elif isinstance(dpg_callback, CallbackReq.AwaitCoro):
                    job = await dpg_callback(*dpg_args)
                elif callable(dpg_callback):
                    # Typical dpg callback, this is how they dispatch @_@
                    argn = len(inspect.signature(dpg_callback).parameters)
                    job = dpg_callback(*dpg_args[:argn])
                else:
                    print(f'Bad job {job}')
                    job = None  # break


def main():
    dpg_callback_queue = curio.UniversalQueue()

    async def dpg_main():
        frame_i = 0
        dpg.show_viewport()
        while dpg.is_dearpygui_running():
            if jobs := dpg.get_callback_queue():  # retrieves and clears queue
                for job in jobs:
                    await dpg_callback_queue.put(job)

            # We don't have any good reason to spawn threads, so this loop must await to yield control to other tasks,
            # there is no preemptive scheduling
            await curio.sleep(0)

            if frame_i == 10:
                async with curio.TaskGroup() as g:
                    await g.spawn(after_first_frame)

            dpg.render_dearpygui_frame()
            frame_i += 1
        dpg.destroy_context()

    async def app_main():
        await init_main()
        await init_basic_ui()
        # dpg.get_callback_queue() above only receives certain high level dpg callbacks,
        # eg callback handlers via dpg.item_handler_registry do not enter that queue.
        # Exposing the same destination queue through EditContext lets those callbacks
        # request an async context with CallbackReq the same way that normal callbacks can.
        EditContext.get().set_callback_queue(dpg_callback_queue)
        async with curio.TaskGroup(wait=any) as g:
            await g.spawn(dpg_callback_consumer(dpg_callback_queue))
            await g.spawn(dpg_main)

    curio.run(app_main)
