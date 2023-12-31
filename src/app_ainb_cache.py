import functools
import json
import os
import pathlib
import sqlite3
from typing import *

import dearpygui.dearpygui as dpg

from .app_types import *
from .db import Connection, AinbFileNodeUsageIndex, PackIndex
from .dt_ainb.ainb import AINB
from . import pack_util


def scoped_pack_lookup(req: PackIndexEntry) -> PackIndexEntry:
    # ainb external modules only specify name, never pack location,
    # so we need to check all the relevant scopes to locate the pack containing it.
    pack_index = get_pack_index_by_extension(req.extension)

    # First look inside the specified "local" pack
    if entry := pack_index.get(req.packfile, {}).get(req.internalfile):
        return entry

    # Can inject any other "global" packed resources per extension/format/etc here
    if req.extension == "ainb":
        # Then check AI/Global pack
        global_packfile = TitleVersion.get().ai_global_pack
        if entry := pack_index.get(global_packfile, {}).get(req.internalfile):
            return entry

    # Finally check "Root" from {romfs}/{cat}/*.ainb
    if entry := pack_index.get("Root", {}).get(req.internalfile):
        return entry

    print(f"Failed scoped_pack_lookup! {req}")


@functools.lru_cache
def get_pack_index_by_extension(ext: str) -> Dict[str, Dict[str, PackIndexEntry]]:
    return PackIndex.get_all_entries_by_extension(Connection.get(), ext)


def build_ainb_index_for_unknown_files() -> None:
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    entry_hit = 0
    entry_total = 0

    with Connection.get() as conn:
        ainb_cache = PackIndex.get_all_entries_by_extension(conn, "ainb")

        # Root ainb
        root_all_locations = [] # Hits and misses are both accumulated for pack index because all filenames are persisted together
        root_new_locations = [] # But for ainb node inspection we can't open them all up every time
        # We don't do this for real packs, opening them all up to compare filenames would be a massive waste of time.
        root_dirs = TitleVersion.get().root_pack_dirs
        print(f"Crawling Root {root_dirs} AINBs ", end='', flush=True)
        for catdir in root_dirs:
            for ainbfile in sorted(pathlib.Path(f"{romfs}/{catdir}").rglob("*.ainb")):
                romfs_relative: str = os.path.join(*ainbfile.parts[-2:])
                romfs_relative = PackIndexEntry.fix_backslashes(romfs_relative)
                entry_total += 1
                root_all_locations.append(romfs_relative)
                if ainb_cache["Root"].get(romfs_relative) is not None:
                    entry_hit += 1
                else:
                    root_new_locations.append(romfs_relative)
        if entry_hit < entry_total:
            inspect_ainb_pack(conn, romfs, "Root", {k: None for k in root_new_locations})
        print("")  # \n

        # Global pack ainb
        packfile = TitleVersion.get().ai_global_pack
        print(f"Crawling {packfile} AINBs ", end='', flush=True)
        # Packs with no matches will be present with an empty {}, only unknown packs will be None, serving as negative cache
        cached_ainb_locations = ainb_cache.get(packfile, None)
        if cached_ainb_locations is None:
            global_locations = pack_util.load_ext_files_from_pack(f"{romfs}/{packfile}", "ainb")
            inspect_ainb_pack(conn, romfs, packfile, global_locations)
            entry_total += len(global_locations)
        else:
            entry_hit += len(cached_ainb_locations)
            entry_total += len(cached_ainb_locations)
        print("")  # \n

        # Actor pack ainb
        print("Crawling Pack/Actor AINBs: ", end='', flush=True)
        log_feedback_letter = ''
        for abs_packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
            packfile = os.path.join(*abs_packfile.parts[-3:])
            packfile = PackIndexEntry.fix_backslashes(packfile)
            # Packs with no matches will be present with an empty {}, only unknown packs will be None, serving as negative cache
            cached_ainb_locations = ainb_cache.get(packfile, None)
            if cached_ainb_locations is None:
                pack_locations = pack_util.load_ext_files_from_pack(f"{romfs}/{packfile}", "ainb")
                inspect_ainb_pack(conn, romfs, packfile, pack_locations)
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
            print(f"Ranking param usage... (please wait a long time)", flush=True)
            AinbFileNodeUsageIndex.postprocess(conn)
            print(f"Caching {entry_total-entry_hit} new entries", flush=True)

    print(f"Cache hits {entry_hit}/{entry_total}\n", flush=True)


def inspect_ainb_pack(conn: sqlite3.Connection, rootfs: str, packfile: str, pack_data: Dict[str, memoryview]):
    # XXX rootfs could be romfs or modfs, should be whatever pack_data's source is.
    # currently it won't see modfs at all, and for some reason I put related lookups in edit_context?

    # The ainb-emptiness of packs is cached, so we won't keep opening them up every time
    PackIndex.persist_one_pack_one_extension(conn, packfile, "ainb", pack_data.keys())
    if len(pack_data) == 0:
        return

    # Crawl each ainb to discover param info per node type.
    for internalfile, data in pack_data.items():
        if packfile == "Root":
            data = memoryview(open(f"{rootfs}/{internalfile}", "rb").read())
        ainb_json = AINB(data).output_dict

        # TODO index file level info in another table?
        fullfile = PackIndexEntry(packfile=packfile, internalfile=internalfile, extension="ainb").fullfile
        file_category = ainb_json["Info"]["File Category"]
        #file_globals = ainb_json.get(ParamSectionName.GLOBAL, {})
        #AinbFileInfoIndex.add(fullfile, file_category, file_globals)

        # TODO additional table for userdefined classes/instantiation/??? detail,
        # since just counting userdefineds leaves a lot of type info out.
        # might be able to generally add metadata/flags/etc to all params this way?

        for node_i, aj_node in enumerate(ainb_json.get("Nodes", [])):
            node_type = aj_node["Node Type"]
            if node_type == "UserDefined":
                node_type = aj_node["Name"]

            param_details = {}
            if x := aj_node.get(ParamSectionName.IMMEDIATE):
                param_details[ParamSectionName.IMMEDIATE] = x
            if x := aj_node.get(ParamSectionName.INPUT):
                param_details[ParamSectionName.INPUT] = x
            if x := aj_node.get(ParamSectionName.OUTPUT):
                param_details[ParamSectionName.OUTPUT] = x

            # aj_node.get("Linked Nodes", {})
            AinbFileNodeUsageIndex.persist(conn, file_category, node_type, param_details)

