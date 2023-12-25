import pathlib
import dearpygui.dearpygui as dpg
import io
import json
import os
import shutil

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
        self.edit_histories = {}

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

    def save_ainb(self, ainb_location: AinbIndexCacheEntry, dirty_ainb: AINB):
        # AINB.output_dict is not intended to be modified, so other AINB members are stale
        updated_ainb = AINB(dirty_ainb.output_dict, from_dict=True)

        if ainb_location.packfile == "Root":
            modfs_ainbfile = pathlib.Path(f"{self.modfs}/{ainb_location.ainbfile}")
            modfs_ainbfile.parent.mkdir(parents=True, exist_ok=True)
            with open(modfs_ainbfile, "wb") as outfile:
                updated_ainb.ToBytes(updated_ainb, outfile)
            print(f"Saved {ainb_location.fullfile}")
            return
        else:
            modfs_packfile = pathlib.Path(f"{self.modfs}/{ainb_location.packfile}")
            if not modfs_packfile.exists():
                # Copy from romfs
                modfs_packfile.parent.mkdir(parents=True, exist_ok=True)
                romfs_packfile = pathlib.Path(f"{self.romfs}/{ainb_location.packfile}")
                shutil.copy(romfs_packfile, modfs_packfile)
                os.chmod(modfs_packfile, 0o664)  # PROTIP: Make your romfs read only

            # Overwrite file and save updated pack
            data = io.BytesIO()
            updated_ainb.ToBytes(updated_ainb, data)
            pack_util.save_file_to_pack(modfs_packfile, ainb_location.ainbfile, data)
            print(f"Saved {ainb_location.fullfile}")
            return

    def perform_new_edit_operation(self, ainb_location: AinbIndexCacheEntry, ainb: AINB, edit_op: AinbEditOperation):
        # Store operation
        # TODO: save history on every operation and clear list (or keep a current entry tagged) upon export. eg crash recovery
        if ainb_location.fullfile not in self.edit_histories:
            self.edit_histories[ainb_location.fullfile] = []
        self.edit_histories[ainb_location.fullfile].append(edit_op)

        # Perform operation
        if edit_op.op_type == AinbEditOperationTypes.REPLACE_JSON:
            ainb.output_dict.clear()
            ainb.output_dict.update(json.loads(edit_op.op_value))
            print(f"Overwrote working ainb @ {ainb_location.fullfile}")
        elif edit_op.op_type == AinbEditOperationTypes.PARAM_UPDATE_DEFAULT:
            # TODO generalize this into any path assignment? creating missing objs + being careful w mutability/refs...
            # For now we just hardcode support for the selector shapes we use.
            print(f"param default = {edit_op.op_value} @ {edit_op.op_selector}")
            sel = edit_op.op_selector
            if len(sel) != 6 or sel[0] != "Nodes" or sel[-1] != "Value":
                raise AssertionError(f"Cannot parse selector {sel}")
            # The path is guaranteed to exist for this case, so no missing parts
            # aj["Nodes"][i]["Immediate Parameters"][aj_type][i_of_type]["Value"] = op_value
            param_type = sel[3]
            if param_type == "vec3f":
                # FIXME separate ui elements, then parse them here
                v = json.loads(edit_op.op_value)
                ainb.output_dict[sel[0]][sel[1]][sel[2]][sel[3]][sel[4]][sel[5]][0] = v[0]
                ainb.output_dict[sel[0]][sel[1]][sel[2]][sel[3]][sel[4]][sel[5]][1] = v[1]
                ainb.output_dict[sel[0]][sel[1]][sel[2]][sel[3]][sel[4]][sel[5]][2] = v[2]
            else:
                ainb.output_dict[sel[0]][sel[1]][sel[2]][sel[3]][sel[4]][sel[5]] = edit_op.op_value