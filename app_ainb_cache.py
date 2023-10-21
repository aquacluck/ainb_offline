import functools
import json
import os
import pathlib
from typing import *

import dearpygui.dearpygui as dpg

import pack_util
from app_types import *


"""
cache format: {
    "Pack": {
        "Root": {AinbIndexCacheEntry.ainbfile: AinbIndexCacheEntry },  # From romfs root, ainbfile has category folder
        AinbIndexCacheEntry.packfile: { AinbIndexCacheEntry.ainbfile: AinbIndexCacheEntry },
    },
}
"""


def _load_or_new_empty_ainb_index(filename: str) -> Dict:
    try:
        ainb_cache = json.load(open(filename, "r"))
    except FileNotFoundError as e:
        print(f"Cache {filename} missing, rebuilding - {e}")
        ainb_cache = {"Pack": {"Root": {}}}
    if "Pack" not in ainb_cache:
        ainb_cache["Pack"] = {"Root": {}}
    for packfile, json_entries in ainb_cache["Pack"].items():
        # Rewrite in-place with dataclasses
        for ainbfile, entry in json_entries.items():
            entry = AinbIndexCacheEntry(**entry)
            ainb_cache["Pack"][packfile][entry.ainbfile] = entry
    return ainb_cache


def scoped_ainbfile_lookup(requested_ainb: AinbIndexCacheEntry) -> AinbIndexCacheEntry:
    # Resolves globals from inside packs, hydrates requested entry from index
    ainb_cache = get_ainb_index()

    # First look inside the specified "local" pack
    if entry := ainb_cache["Pack"].get(requested_ainb.packfile, {}).get(requested_ainb.ainbfile):
        return entry

    # Then check AI/Global pack
    global_packfile = "Pack/AI.Global.Product.100.pack.zs"
    if entry := ainb_cache["Pack"].get(global_packfile, {}).get(requested_ainb.ainbfile):
        return entry

    # Finally check "Root" from {romfs}/{cat}/*.ainb
    if entry := ainb_cache["Pack"]["Root"].get(requested_ainb.ainbfile):
        return entry

    print(f"Failed scoped_ainbfile_lookup! {requested_ainb}")


@functools.lru_cache
def get_ainb_index() -> Dict:
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    ainb_file_index_file = dpg.get_value(AppConfigKeys.AINB_FILE_INDEX_FILE)
    ainb_cache = _load_or_new_empty_ainb_index(ainb_file_index_file)

    entry_hit = 0
    entry_total = 0

    # Root ainb
    print("Finding Root AI, Logic, Sequence AINBs ", end='', flush=True)
    for catdir in ("AI", "Logic", "Sequence"):
        for ainbfile in sorted(pathlib.Path(f"{romfs}/{catdir}").rglob("*.ainb")):
            romfs_relative: str = os.path.join(*ainbfile.parts[-2:])
            entry_total += 1
            if ainb_cache["Pack"]["Root"].get(romfs_relative) is not None:
                entry_hit += 1
            else:
                # TODO open AINB(ainbfile) and index stuff?
                ainb_location = AinbIndexCacheEntry(packfile="Root", ainbfile=romfs_relative)
                ainb_cache["Pack"]["Root"][romfs_relative] = ainb_location
    print("")  # \n

    # Global pack ainb
    print("Finding Pack/AI.Global.Product.100 AINBs ", end='', flush=True)
    packfile = "Pack/AI.Global.Product.100.pack.zs"
    cached_ainb_locations = ainb_cache["Pack"].get(packfile, None)  # no {} default = negative cache
    if cached_ainb_locations is None:
        # TODO open AINB and index stuff?
        ainbfiles = [f for f in pack_util.get_pack_internal_filenames(f"{romfs}/{packfile}") if f.endswith(".ainb")]
        cached_ainb_locations = ainb_cache["Pack"][packfile] = { f: AinbIndexCacheEntry(ainbfile=f, packfile=packfile) for f in ainbfiles }
    else:
        entry_hit += len(cached_ainb_locations)
    entry_total += len(cached_ainb_locations)
    print("")  # \n

    # Actor pack ainb
    print("Finding Pack/Actor AINBs: ", end='', flush=True)
    log_feedback_letter = ''
    for abs_packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
        packfile = os.path.join(*abs_packfile.parts[-3:])
        cached_ainb_locations = ainb_cache["Pack"].get(packfile, None)  # no {} default = negative cache
        if cached_ainb_locations is None:
            # TODO open AINB and index stuff?
            ainbfiles = [f for f in pack_util.get_pack_internal_filenames(abs_packfile) if f.endswith(".ainb")]
            cached_ainb_locations = ainb_cache["Pack"][packfile] = { f: AinbIndexCacheEntry(ainbfile=f, packfile=packfile) for f in ainbfiles }
        else:
            entry_hit += len(cached_ainb_locations)
        entry_total += len(cached_ainb_locations)
        packname = pathlib.Path(packfile).name.rsplit(".pack.zs", 1)[0]
        if log_feedback_letter != packname[0]:
            log_feedback_letter = packname[0]
            print(log_feedback_letter, end='', flush=True)
    print("")  # \n

    if entry_hit < entry_total:
        # TODO: zstd this to disk, and replace json with something streamable, 4MB string already here
        print(f"Caching {entry_total-entry_hit} new entries", end='')
        out = json.dumps(ainb_cache, default=vars, indent=4)
        ainb_file_index_file = dpg.get_value(AppConfigKeys.AINB_FILE_INDEX_FILE)
        with open(ainb_file_index_file, "w") as outfile:
            outfile.write(out)
    else:
        print(f"Cache hits {entry_hit}/{entry_total}\n")

    return ainb_cache
