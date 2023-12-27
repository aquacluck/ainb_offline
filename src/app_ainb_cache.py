import functools
import os
import pathlib
from typing import *

import dearpygui.dearpygui as dpg

from app_types import *
import db
from db_model_pack_index import PackIndex
import pack_util


def scoped_ainbfile_lookup(requested_ainb: PackIndexEntry) -> PackIndexEntry:
    # Resolves globals from inside packs, hydrates requested entry from index
    ainb_cache = get_ainb_index()

    # First look inside the specified "local" pack
    if entry := ainb_cache["Pack"].get(requested_ainb.packfile, {}).get(requested_ainb.internalfile):
        return entry

    # Then check AI/Global pack
    global_packfile = TitleVersionAiGlobalPack.get(dpg.get_value(AppConfigKeys.TITLE_VERSION))
    if entry := ainb_cache["Pack"].get(global_packfile, {}).get(requested_ainb.internalfile):
        return entry

    # Finally check "Root" from {romfs}/{cat}/*.ainb
    if entry := ainb_cache["Pack"]["Root"].get(requested_ainb.internalfile):
        return entry

    print(f"Failed scoped_ainbfile_lookup! {requested_ainb}")


@functools.lru_cache
def get_ainb_index() -> Dict[str, Dict[str, PackIndexEntry]]:
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    entry_hit = 0
    entry_total = 0

    with db.Connection.get() as conn:
        ainb_cache = {"Pack": PackIndex.get_all_entries_by_extension(conn, "ainb")}
        if ainb_cache["Pack"].get("Root") is None:
            ainb_cache["Pack"]["Root"] = {}

        # Root ainb
        root_locations = []
        root_dirs = TitleVersionRootPackDirs.get(dpg.get_value(AppConfigKeys.TITLE_VERSION))
        print(f"Finding Root {root_dirs} AINBs ", end='', flush=True)
        for catdir in root_dirs:
            for ainbfile in sorted(pathlib.Path(f"{romfs}/{catdir}").rglob("*.ainb")):
                romfs_relative: str = os.path.join(*ainbfile.parts[-2:])
                entry_total += 1
                if ainb_cache["Pack"]["Root"].get(romfs_relative) is not None:
                    entry_hit += 1
                else:
                    # TODO open AINB(ainbfile) and index: node types
                    root_locations.append(romfs_relative)
        PackIndex.persist_one_pack_one_extension(conn, "Root", "ainb", root_locations)
        print("")  # \n

        # Global pack ainb
        packfile = TitleVersionAiGlobalPack.get(dpg.get_value(AppConfigKeys.TITLE_VERSION))
        print(f"Finding {packfile} AINBs ", end='', flush=True)
        # Packs with no matches will be present with an empty {}, only unknown packs will be None, serving as negative cache
        cached_ainb_locations = ainb_cache["Pack"].get(packfile, None)
        if cached_ainb_locations is None:
            # TODO open AINB and index stuff?
            global_locations = [
                f for f in pack_util.get_pack_internal_filenames(f"{romfs}/{packfile}")
                if f.endswith(".ainb")
            ]
            PackIndex.persist_one_pack_one_extension(conn, packfile, "ainb", global_locations)
            entry_total += len(global_locations)
        else:
            entry_hit += len(cached_ainb_locations)
            entry_total += len(cached_ainb_locations)
        print("")  # \n

        # Actor pack ainb
        print("Finding Pack/Actor AINBs: ", end='', flush=True)
        log_feedback_letter = ''
        for abs_packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
            packfile = os.path.join(*abs_packfile.parts[-3:])
            # Packs with no matches will be present with an empty {}, only unknown packs will be None, serving as negative cache
            cached_ainb_locations = ainb_cache["Pack"].get(packfile, None)
            if cached_ainb_locations is None:
                # TODO open AINB and index stuff?
                pack_locations = [
                    f for f in pack_util.get_pack_internal_filenames(f"{romfs}/{packfile}")
                    if f.endswith(".ainb")
                ]
                PackIndex.persist_one_pack_one_extension(conn, packfile, "ainb", pack_locations)
                entry_total += len(pack_locations)
            else:
                entry_hit += len(cached_ainb_locations)
                entry_total += len(cached_ainb_locations)
            packname = pathlib.Path(packfile).name.rsplit(".pack.zs", 1)[0]
            if log_feedback_letter != packname[0]:
                log_feedback_letter = packname[0]
                print(log_feedback_letter, end='', flush=True)
        print("")  # \n

    if entry_hit < entry_total:
        # output is stale, just fetch our recent updates from db
        del ainb_cache
        print(f"Cached {entry_total-entry_hit} new entries\n", flush=True)
        return {"Pack": PackIndex.get_all_entries_by_extension(conn, "ainb")}
    else:
        print(f"Cache hits {entry_hit}/{entry_total}\n", flush=True)
        return ainb_cache
