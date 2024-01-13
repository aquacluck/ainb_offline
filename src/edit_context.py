import pathlib
import dearpygui.dearpygui as dpg
import io
import os
import shutil

from .app_types import *
from .mutable_ainb import MutableAinb, AinbEditOperationExecutor
from .mutable_asb import MutableAsb, AsbEditOperationExecutor
from .dt_tools.ainb import AINB
from .dt_tools.asb import ASB
# XXX deferred from .ui.window_ainb_graph import WindowAinbGraph
# XXX deferred from .ui.window_asb_graph import WindowAsbGraph
from . import pack_util


GLOBAL_INSTANCE = None

class EditContext:
    @classmethod
    def get(cls) -> "EditContext":
        # singleton or something, the whole app gets it this way
        global GLOBAL_INSTANCE
        if not GLOBAL_INSTANCE:
            GLOBAL_INSTANCE = cls()
        return GLOBAL_INSTANCE

    def __init__(self):
        self.romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
        self.modfs = dpg.get_value(AppConfigKeys.MODFS_PATH)
        self.title_version = dpg.get_value(AppConfigKeys.TITLE_VERSION)
        self.open_windows: Dict[str, "WindowAinbGraph"] = {}
        self.edit_histories: Dict[str, List[AinbEditOperation]] = {}

    def open_ainb_window(self, ainb_location: PackIndexEntry) -> None:
        if window := self.open_windows.get(ainb_location.fullfile):
            # Ignore request and just raise existing window
            dpg.focus_item(window.tag)
            return
        from .ui.window_ainb_graph import WindowAinbGraph  # XXX
        window = WindowAinbGraph(ainb_location, self)
        i = len(self.open_windows)
        pos = [400 + 25*i, 50 + 25*i]
        window.create(width=1280, height=1080, pos=pos)
        self.open_windows[ainb_location.fullfile] = window

    def open_asb_window(self, asb_location: PackIndexEntry) -> None:
        if window := self.open_windows.get(asb_location.fullfile):
            # Ignore request and just raise existing window
            dpg.focus_item(window.tag)
            return
        from .ui.window_asb_graph import WindowAsbGraph  # XXX
        window = WindowAsbGraph(asb_location, self)
        i = len(self.open_windows)
        pos = [400 + 25*i, 50 + 25*i]
        window.create(width=1280, height=1080, pos=pos)
        self.open_windows[asb_location.fullfile] = window

    def close_file_window(self, location: PackIndexEntry) -> None:
        del self.open_windows[location.fullfile]

    def load_ainb(self, ainb_location: PackIndexEntry) -> MutableAinb:
        data = self._resolve_and_read(ainb_location)
        ainb = AINB(data)
        return MutableAinb.from_dt_ainb(ainb, ainb_location)

    def load_asb(self, asb_location: PackIndexEntry) -> MutableAsb:
        data = self._resolve_and_read(asb_location)
        asb = ASB(data)
        return MutableAsb.from_dt_asb(asb, asb_location)

    def _resolve_and_read(self, location: PackIndexEntry) -> memoryview:
        # Resolve through modfs, modfs packs, ...
        if location.packfile == "Root":
            modfs_file = pathlib.Path(f"{self.modfs}/{location.internalfile}")
            if modfs_file.exists():
                if str(modfs_file).endswith(".zs"):
                    return pack_util.load_compressed_file(modfs_file)
                else:
                    return memoryview(open(modfs_file, "rb").read())

            romfs_file = pathlib.Path(f"{self.romfs}/{location.internalfile}")
            if romfs_file.exists():
                if str(romfs_file).endswith(".zs"):
                    return pack_util.load_compressed_file(romfs_file)
                else:
                    return memoryview(open(romfs_file, "rb").read())

            raise FileNotFoundError(f"Failed to resolve: {location.fullfile}")

        else:
            modfs_packfile = pathlib.Path(f"{self.modfs}/{location.packfile}")
            if modfs_packfile.exists():
                try:
                    return pack_util.load_file_from_pack(modfs_packfile, location.internalfile)
                except KeyError:
                    pass  # Other tools+workflows might create incomplete packs, just fall back to romfs

            romfs_packfile = pathlib.Path(f"{self.romfs}/{location.packfile}")
            if romfs_packfile.exists():
                return pack_util.load_file_from_pack(romfs_packfile, location.internalfile)

            raise FileNotFoundError(f"Failed to resolve: {location.fullfile}")

    def save_ainb(self, dirty_ainb: MutableAinb):
        updated_ainb = AINB(dirty_ainb.json, from_dict=True)
        ainb_location = dirty_ainb.location

        if ainb_location.packfile == "Root":
            modfs_ainbfile = pathlib.Path(f"{self.modfs}/{ainb_location.internalfile}")
            modfs_ainbfile.parent.mkdir(parents=True, exist_ok=True)
            # FIXME output to a BytesIO so we don't clobber the file on failure
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
            pack_util.save_file_to_pack(modfs_packfile, ainb_location.internalfile, data)
            print(f"Saved {ainb_location.fullfile}")
            return

    def save_asb(self, dirty_asb: MutableAsb):
        updated_asb = ASB(dirty_asb.json)
        asb_location = dirty_asb.location

        if asb_location.packfile == "Root":
            modfs_asbfile = pathlib.Path(f"{self.modfs}/{asb_location.internalfile}")
            modfs_asbfile.parent.mkdir(parents=True, exist_ok=True)
            data = io.BytesIO()
            updated_asb.ToBuffer(data)
            # Root ASBs are always compressed
            pack_util.save_compressed_file(modfs_asbfile, data)
            print(f"Saved {asb_location.fullfile}")
            return
        else:
            modfs_packfile = pathlib.Path(f"{self.modfs}/{asb_location.packfile}")
            if not modfs_packfile.exists():
                # Copy from romfs
                modfs_packfile.parent.mkdir(parents=True, exist_ok=True)
                romfs_packfile = pathlib.Path(f"{self.romfs}/{asb_location.packfile}")
                shutil.copy(romfs_packfile, modfs_packfile)
                os.chmod(modfs_packfile, 0o664)  # PROTIP: Make your romfs read only

            # Overwrite file and save updated pack
            data = io.BytesIO()
            updated_asb.ToBytes(updated_asb, data)
            pack_util.save_file_to_pack(modfs_packfile, asb_location.internalfile, data)
            print(f"Saved {asb_location.fullfile}")
            return

    def perform_new_ainb_edit_operation(self, ainb: MutableAinb, edit_op: AinbEditOperation):
        # Perform operation
        AinbEditOperationExecutor.dispatch(ainb, edit_op)

        # Store operation (after, so we won't store a crashing operation)
        # TODO: persist history to db on every operation and set filehash upon export. eg crash recovery
        if ainb.location.fullfile not in self.edit_histories:
            self.edit_histories[ainb.location.fullfile] = []
            self.edit_histories[ainb.location.fullfile].append(edit_op)
            # persist history.db (insert edit_op)
            #edit_op.filehash = "fakehash_first_edit"
        else:
            prev_op = self.edit_histories[ainb.location.fullfile][-1]
            is_prev_op_amended = AinbEditOperationExecutor.try_merge_history(edit_op, prev_op)
            if is_prev_op_amended:
                pass # persist history.db (update prev_op)
            else:
                self.edit_histories[ainb.location.fullfile].append(edit_op)
                # persist history.db (insert edit_op)

    def perform_new_asb_edit_operation(self, asb: MutableAsb, edit_op: AsbEditOperation):
        # Perform operation
        AsbEditOperationExecutor.dispatch(asb, edit_op)

        # Store operation (after, so we won't store a crashing operation)
        # TODO: persist history to db on every operation and set filehash upon export. eg crash recovery
        if asb.location.fullfile not in self.edit_histories:
            self.edit_histories[asb.location.fullfile] = []
            self.edit_histories[asb.location.fullfile].append(edit_op)
            # persist history.db (insert edit_op)
            #edit_op.filehash = "fakehash_first_edit"
        else:
            prev_op = self.edit_histories[asb.location.fullfile][-1]
            is_prev_op_amended = AsbEditOperationExecutor.try_merge_history(edit_op, prev_op)
            if is_prev_op_amended:
                pass # persist history.db (update prev_op)
            else:
                self.edit_histories[asb.location.fullfile].append(edit_op)
                # persist history.db (insert edit_op)
