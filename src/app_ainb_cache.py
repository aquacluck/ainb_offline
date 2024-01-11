from collections import defaultdict
import functools
import os
import pathlib
import sqlite3
from typing import *

import dearpygui.dearpygui as dpg

from .app_types import *
from .db import Connection, AinbFileNodeUsageIndex, PackIndex
from .dt_tools.ainb import AINB
from . import pack_util


FileListByExt = Dict[str, List[str]]


def scoped_pack_lookup(req: PackIndexEntry) -> PackIndexEntry:
    # ainb external modules only specify name, never pack location,
    # so we need to check all the relevant scopes to locate the pack containing it.
    pack_index = get_pack_index_by_extension(req.extension)

    # First look inside the specified "local" pack
    if entry := pack_index.get(req.packfile, {}).get(req.internalfile):
        return entry

    # Can inject any other "global" packed resources per extension/format/etc here
    if req.extension == RomfsFileTypes.AINB:
        # Then check AI/Global pack
        global_packfile = TitleVersion.get().ai_global_pack
        if entry := pack_index.get(global_packfile, {}).get(req.internalfile):
            return entry
    elif req.extension == RomfsFileTypes.ASB:
        pass  # no global asb pack

    # Finally check "Root" from {romfs}/{cat}/*.ainb, {romfs}/AS/*.asb
    if entry := pack_index.get("Root", {}).get(req.internalfile):
        return entry

    print(f"Failed scoped_pack_lookup! {req}")


@functools.lru_cache
def get_pack_index_by_extension(ext: RomfsFileTypes) -> Dict[str, Dict[str, PackIndexEntry]]:
    return PackIndex.get_all_entries_by_extension(Connection.get(), ext)


def build_indexes_for_unknown_files() -> None:
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    entry_hit = 0
    entry_total = 0

    with Connection.get() as conn:
        ainb_cache = PackIndex.get_all_entries_by_extension(conn, RomfsFileTypes.AINB)
        asb_cache = PackIndex.get_all_entries_by_extension(conn, RomfsFileTypes.ASB)

        # Root folders
        root_new_locations: FileListByExt = defaultdict(list)
        root_dirs = TitleVersion.get().root_pack_dirs
        print(f"Crawling Root {root_dirs}", end='', flush=True)
        for rootdir in root_dirs:
            for path in sorted(pathlib.Path(f"{romfs}/{rootdir}").rglob("*.ainb")):
                romfs_relative: str = os.path.join(*path.parts[-2:])
                romfs_relative = PackIndexEntry.fix_backslashes(romfs_relative)
                entry_total += 1
                if ainb_cache["Root"].get(romfs_relative) is not None:
                    entry_hit += 1
                else:
                    root_new_locations[RomfsFileTypes.AINB].append(romfs_relative)
            for path in sorted(pathlib.Path(f"{romfs}/{rootdir}").rglob("*.asb.zs")):
                romfs_relative: str = os.path.join(*path.parts[-2:])
                romfs_relative = PackIndexEntry.fix_backslashes(romfs_relative)
                entry_total += 1
                if asb_cache["Root"].get(romfs_relative) is not None:
                    entry_hit += 1
                else:
                    root_new_locations[RomfsFileTypes.ASB].append(romfs_relative)
        if entry_hit < entry_total:
            files: pack_util.FileDataByExt = defaultdict(lambda: defaultdict(memoryview))
            for (ext, fl) in root_new_locations.items():
                for f in fl:
                    files[ext][f] = None
            inspect_pack(conn, romfs, "Root", files)
        print("")  # \n

        # Global pack
        packfile = TitleVersion.get().ai_global_pack
        print(f"Crawling {packfile} ", end='', flush=True)
        # Packs with no matches will be present with an empty {}, only unknown packs will be None, serving as negative cache
        cached_ainb_locations = ainb_cache.get(packfile, None)
        cached_asb_locations = asb_cache.get(packfile, None)
        if cached_ainb_locations or cached_asb_locations:
            hits = len(cached_ainb_locations or []) + len(cached_asb_locations or [])
            entry_hit += hits
            entry_total += hits
        else:
            global_locations = pack_util.load_ext_files_from_pack(f"{romfs}/{packfile}", RomfsFileTypes.all())
            inspect_pack(conn, romfs, packfile, global_locations)
            entry_total += len(global_locations[RomfsFileTypes.AINB].keys())
            entry_total += len(global_locations[RomfsFileTypes.ASB].keys())
        print("")  # \n

        # Actor packs
        print("Crawling Pack/Actor: ", end='', flush=True)
        log_feedback_letter = ''
        for abs_packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
            packfile = os.path.join(*abs_packfile.parts[-3:])
            packfile = PackIndexEntry.fix_backslashes(packfile)
            # Packs with no matches will be present with an empty {}, only unknown packs will be None, serving as negative cache
            cached_ainb_locations = ainb_cache.get(packfile, None)
            cached_asb_locations = asb_cache.get(packfile, None)
            if cached_ainb_locations or cached_asb_locations:
                hits = len(cached_ainb_locations or []) + len(cached_asb_locations or [])
                entry_hit += hits
                entry_total += hits
            elif cached_asb_locations is None or cached_asb_locations is None:
                pack_locations = pack_util.load_ext_files_from_pack(f"{romfs}/{packfile}", list(RomfsFileTypes))
                inspect_pack(conn, romfs, packfile, pack_locations)
                entry_total += len(pack_locations[RomfsFileTypes.AINB].keys())
                entry_total += len(pack_locations[RomfsFileTypes.ASB].keys())
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


def inspect_pack(conn: sqlite3.Connection, rootfs: str, packfile: str, pack_data: pack_util.FileDataByExt):
    # XXX rootfs could be romfs or modfs, should be whatever pack_data's source is.
    # currently it won't see modfs at all, and for some reason I put related lookups in edit_context?

    # The ainb-emptiness of packs is cached, so we won't keep opening them up every time
    PackIndex.persist_one_pack_one_extension(conn, packfile, RomfsFileTypes.AINB, pack_data[RomfsFileTypes.AINB].keys())
    PackIndex.persist_one_pack_one_extension(conn, packfile, RomfsFileTypes.ASB, pack_data[RomfsFileTypes.ASB].keys())

    # Crawl each ainb to discover param info per node type.
    for internalfile, data in pack_data[RomfsFileTypes.AINB].items():
        if packfile == "Root":
            data = memoryview(open(f"{rootfs}/{internalfile}", "rb").read())
        ainb_json = AINB(data).output_dict

        # TODO index file level info in another table?
        fullfile = PackIndexEntry(packfile=packfile, internalfile=internalfile, extension=RomfsFileTypes.AINB).fullfile
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

