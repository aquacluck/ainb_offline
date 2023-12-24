import pathlib
import dearpygui.dearpygui as dpg

from app_types import *
from dt_ainb.ainb import AINB
import pack_util

active_ectx = None  # initialized in main

class EditContext:
    @staticmethod
    def get():  # singleton or something, the whole app gets it this way
        global active_ectx
        return active_ectx

    def __init__(self):
        self.romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
        self.modfs = dpg.get_value(AppConfigKeys.MODFS_PATH)
        self.open_windows = {}

    def get_ainb_window(self, ainb_location: AinbIndexCacheEntry):
        return self.open_windows.get(ainb_location.fullfile)

    def register_ainb_window(self, ainb_location: AinbIndexCacheEntry, tag):
        if ainb_location.fullfile in self.open_windows:
            raise Exception(f"Window already open for {ainb_location.fullfile}")
        self.open_windows[ainb_location.fullfile] = tag

    def unregister_ainb_window(self, ainb_location):
        del self.open_windows[ainb_location.fullfile]

    def load_ainb(self, ainb_location: AinbIndexCacheEntry) -> AINB:
        # Resolve through modfs, modfs packs, ...
        if ainb_location.packfile == "Root":
            modfs_ainbfile = pathlib.Path(f"{self.modfs}/{ainb_location.ainbfile}")
            if modfs_ainbfile.exists():
                return AINB(open(modfs_ainbfile, "rb").read())

            romfs_ainbfile = pathlib.Path(f"{self.romfs}/{ainb_location.ainbfile}")
            if romfs_ainbfile.exists():
                return AINB(open(romfs_ainbfile, "rb").read())

            raise FileNotFoundError(f"Failed to resolve: {ainb_location.fullfile}")

        else:
            modfs_packfile = pathlib.Path(f"{self.modfs}/{ainb_location.packfile}")
            if modfs_packfile.exists():
                try:
                    return AINB(pack_util.load_file_from_pack(modfs_packfile, ainb_location.ainbfile))
                except KeyError:
                    pass  # Other tools+workflows might create incomplete packs, just fall back to romfs

            romfs_packfile = pathlib.Path(f"{self.romfs}/{ainb_location.packfile}")
            if romfs_packfile.exists():
                return AINB(pack_util.load_file_from_pack(romfs_packfile, ainb_location.ainbfile))

            raise FileNotFoundError(f"Failed to resolve: {ainb_location.fullfile}")
