import os
import pathlib
from typing import *

import dearpygui.dearpygui as dpg
from .. import curio

from .. import pack_util
from ..app_types import *
from ..app_ainb_cache import get_pack_index_by_extension
from ..edit_context import EditContext


class WindowAinbIndex:
    @classmethod
    async def create_as_coro(cls, parent: DpgTag) -> None:
        window = cls()
        window.create(parent)
        while True:
            # we own+supervise this instance and its ui
            await curio.sleep(69)

    def create(self, parent: DpgTag) -> DpgTag:
        self.tag = dpg.add_child_window(label="AINB Index", pos=[0, 18], width=400, autosize_y=True, parent=parent)
        self.render_contents()
        return self.tag

    def render_contents(self):
        # Opening ainb windows
        with dpg.item_handler_registry(tag="ainb_index_window_handler") as open_ainb_handler:
            def callback_open_ainb(s, a, u):
                textitem = a[1]
                ainb_location: PackIndexEntry = dpg.get_item_user_data(textitem)

                ectx = EditContext.get()
                req = CallbackReq.SpawnCoro(ectx.open_ainb_window_as_coro, [ainb_location])
                ectx.dpg_callback_queue.put(req)

            dpg.add_item_clicked_handler(callback=callback_open_ainb)

        # Opening asb windows
        with dpg.item_handler_registry(tag="asb_index_window_handler") as open_asb_handler:
            def callback_open_asb(s, a, u):
                textitem = a[1]
                asb_location: PackIndexEntry = dpg.get_item_user_data(textitem)

                ectx = EditContext.get()
                req = CallbackReq.SpawnCoro(ectx.open_asb_window_as_coro, [asb_location])
                ectx.dpg_callback_queue.put(req)

            dpg.add_item_clicked_handler(callback=callback_open_asb)

        # Quick search
        actor_pack_n = -1
        def callback_filter(sender, filter_string):
            if len(filter_string) < 3:
                # Exclude slowest chars for perf, although short substrings can still be invoked after commas.
                # We have no control over how search is performed, eg no way to use a db without reimplementing filtering.
                filter_string = ""
            dpg.set_value(f"{self.tag}/ASB/Root/Filter", filter_string)
            dpg.set_value(f"{self.tag}/AINB/Root/Filter", filter_string)
            dpg.set_value(f"{self.tag}/AINB/Global/Filter", filter_string)
            dpg.set_value(f"{self.tag}/AINB/PackActor/Filter", filter_string)
            for i in range(actor_pack_n):
                dpg.set_value(f"{self.tag}/AINB/PackActor/{i}/Filter", filter_string)
        # filter eg `-ai/, -logic/, localmodule, load`: any positive terms pass (union), matching all (intersection) not needed
        filter_input = dpg.add_input_text(hint="any1, any2, -exclude (min 3 chars)", callback=callback_filter, parent=self.tag)


        ainb_cache = get_pack_index_by_extension(RomfsFileTypes.AINB)
        asb_cache = get_pack_index_by_extension(RomfsFileTypes.ASB)
        with dpg.tab_bar(parent=self.tag):
            # dpg.add_tab_button(label="[max]", callback=dpg.maximize_viewport)  # works at runtime, fails at init?
            # dpg.add_tab_button(label="wipe cache")
            # dpg.add_tab_button(label="new ainb file")
            # TODO with dpg.tab(label="Modded AINBs"):
            #    # dirty indicators: working ainb is dirty (all edits), dirty ainb not present in modfs (first edit)
            #    # context menu -> delete pack or ainb changes
            #    # context menu -> re-calc romfs + edit_op history
            with dpg.tab(label="All AINBs"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    # TODO context menu -> re-crawl pack or ainb
                    with dpg.tree_node(label="Root", default_open=True):
                        with dpg.filter_set(tag=f"{self.tag}/AINB/Root/Filter"):
                            cached_ainb_locations = ainb_cache.get("Root", {})
                            for ainbfile, ainb_location in cached_ainb_locations.items():
                                item = dpg.add_text(ainb_location.internalfile, user_data=ainb_location, parent=f"{self.tag}/AINB/Root/Filter", filter_key=ainb_location.internalfile)
                                dpg.bind_item_handler_registry(item, open_ainb_handler)


                    global_packfile = TitleVersion.get().ai_global_pack
                    with dpg.tree_node(label=global_packfile, default_open=True):
                        with dpg.filter_set(tag=f"{self.tag}/AINB/Global/Filter"):
                            cached_ainb_locations = ainb_cache.get(global_packfile, {})
                            for ainbfile, ainb_location in cached_ainb_locations.items():
                                item = dpg.add_text(ainb_location.internalfile, user_data=ainb_location, parent=f"{self.tag}/AINB/Global/Filter", filter_key=ainb_location.internalfile)
                                dpg.bind_item_handler_registry(item, open_ainb_handler)


                    dpg.add_separator()
                    dpg.add_separator()
                    dpg.add_text("Actor Packs", indent=140, color=AppStyleColors.LIST_ENTRY_SEPARATOR.to_rgba32())
                    # TODO buttons to expand+close all trees
                    dpg.add_separator()
                    dpg.add_separator()

                    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
                    with dpg.filter_set(tag=f"{self.tag}/AINB/PackActor/Filter"):
                        for packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
                            # XXX why so paranoid about only showing existing packs? can't we just loop through cache excluding global+root?
                            romfs_relative: str = os.path.join(*packfile.parts[-3:])
                            romfs_relative = PackIndexEntry.fix_backslashes(romfs_relative)
                            cached_ainb_locations = ainb_cache.get(romfs_relative, {})
                            ainbcount = len(cached_ainb_locations)
                            if ainbcount == 0:
                                continue

                            packname = pathlib.Path(romfs_relative).name.rsplit(".pack.zs", 1)[0]
                            label = f"{packname} [{ainbcount}]"

                            # Glob-like formatting, but just a literal search key: a.pack.zs:{one,two}
                            # This way we can show/hide the pack item itself based on all filenames within.
                            # Root+Global packs make sense to always display, so we don't do this for those
                            filter_val = ",".join([al.internalfile for al in cached_ainb_locations.values()])
                            filter_val = f"{packfile}:{{{filter_val}}}"
                            actor_pack_n += 1
                            with dpg.tree_node(label=label, default_open=(ainbcount <= 4), filter_key=filter_val):
                                with dpg.filter_set(tag=f"{self.tag}/AINB/PackActor/{actor_pack_n}/Filter"):
                                    for ainbfile, ainb_location in cached_ainb_locations.items():
                                        item = dpg.add_text(ainb_location.internalfile, user_data=ainb_location, bullet=True, filter_key=ainb_location.fullfile)
                                        dpg.bind_item_handler_registry(item, open_ainb_handler)


            with dpg.tab(label="All ASBs"):
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    with dpg.tree_node(label="Root", default_open=True):
                        with dpg.filter_set(tag=f"{self.tag}/ASB/Root/Filter"):
                            cached_asb_locations = asb_cache.get("Root", {})
                            for asbfile, asb_location in cached_asb_locations.items():
                                item = dpg.add_text(asb_location.internalfile, user_data=asb_location, parent=f"{self.tag}/ASB/Root/Filter", filter_key=asb_location.internalfile)
                                dpg.bind_item_handler_registry(item, open_asb_handler)
