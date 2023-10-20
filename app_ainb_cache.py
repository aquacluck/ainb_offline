import functools
import json
import os
import pathlib
from typing import *

import dearpygui.dearpygui as dpg

import pack_util
from app_types import *
from window_ainb_graph import open_ainb_graph_window


"""
cache format: {
    "Bare": {
        "AI": { AinbIndexCacheEntry.ainbfile: AinbIndexCacheEntry },
        "Logic": { AinbIndexCacheEntry.ainbfile: AinbIndexCacheEntry },
        "Sequence": { AinbIndexCacheEntry.ainbfile: AinbIndexCacheEntry },
    },
    "Pack": {AinbIndexCacheEntry.packfile: List[AinbIndexCacheEntry]},
}
we might not really want toplevels separated by cat, we might want *everything* by cat, idk yet but it's messy this way
"""


def _load_or_new_empty_ainb_index(filename: str) -> Dict:
    try:
        ainb_cache = json.load(open(filename, "r"))
    except FileNotFoundError:
        # Skip load cache, we'll be rebuilding misses anyways
        ainb_cache = {"Bare": {"AI": {}, "Logic": {}, "Sequence": {}}, "Pack": {}}
    else:
        # Load cache
        if "Bare" not in ainb_cache:
            ainb_cache["Bare"] = {}
        for catdir in ("AI", "Logic", "Sequence"):
            if catdir not in ainb_cache["Bare"]:
                ainb_cache["Bare"][catdir] = {}
            for ainbfile, json_entry in ainb_cache["Bare"][catdir].items():
                # Rewrite in-place with dataclasses
                ainb_cache["Bare"][catdir][ainbfile] = AinbIndexCacheEntry(**json_entry)

        if "Pack" not in ainb_cache:
            ainb_cache["Pack"] = {}
        for packfile, json_entries in ainb_cache["Pack"].items():
            # Rewrite in-place with dataclasses
            ainb_cache["Pack"][packfile] = [AinbIndexCacheEntry(**kw) for kw in json_entries]
    return ainb_cache


@functools.lru_cache
def get_ainb_index() -> Dict:
    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    ainb_file_index_file = dpg.get_value(AppConfigKeys.AINB_FILE_INDEX_FILE)
    ainb_cache = _load_or_new_empty_ainb_index(ainb_file_index_file)

    entry_hit = 0
    entry_total = 0

    # Bare ainb
    print("Finding toplevel AI, Logic, Sequence AINBs ", end='', flush=True)
    for catdir in ("AI", "Logic", "Sequence"):
        for ainbfile in sorted(pathlib.Path(f"{romfs}/{catdir}").rglob("*.ainb")):
            romfs_relative: str = os.path.join(*ainbfile.parts[-2:])
            entry_total += 1
            if ainb_cache["Bare"][catdir].get(romfs_relative) is not None:
                entry_hit += 1
            else:
                # TODO open AINB(ainbfile) and index stuff?
                # TODO store folder? A/S/L category?
                ainb_location = AinbIndexCacheEntry(ainbfile=romfs_relative)
                ainb_cache["Bare"][catdir][romfs_relative] = ainb_location
    print("")  # \n

    # Global pack ainb
    print("Finding Pack/AI.Global.Product.100 AINBs ", end='', flush=True)
    packfile = "Pack/AI.Global.Product.100.pack.zs"
    cached_ainb_locations = ainb_cache["Pack"].get(packfile, None)  # no [] default = negative cache
    if cached_ainb_locations is None:
        # TODO open AINB and index stuff?
        ainbfiles = [f for f in pack_util.get_pack_internal_filenames(f"{romfs}/{packfile}") if f.endswith(".ainb")]
        cached_ainb_locations = ainb_cache["Pack"][packfile] = [AinbIndexCacheEntry(f, packfile=packfile) for f in ainbfiles]
    else:
        entry_hit += len(cached_ainb_locations)
    entry_total += len(cached_ainb_locations)
    print("")  # \n

    # Actor pack ainb
    print("Finding Pack/Actor AINBs: ", end='', flush=True)
    log_feedback_letter = ''
    for packfile in sorted(pathlib.Path(f"{romfs}/Pack/Actor").rglob("*.pack.zs")):
        romfs_relative: str = os.path.join(*packfile.parts[-3:])
        cached_ainb_locations = ainb_cache["Pack"].get(romfs_relative, None)  # no [] default = negative cache
        if cached_ainb_locations is None:
            # TODO open AINB and index stuff?
            ainbfiles = [f for f in pack_util.get_pack_internal_filenames(packfile) if f.endswith(".ainb")]
            cached_ainb_locations = ainb_cache["Pack"][romfs_relative] = [AinbIndexCacheEntry(f, packfile=romfs_relative) for f in ainbfiles]
        else:
            entry_hit += len(cached_ainb_locations)
        entry_total += len(cached_ainb_locations)
        packname = pathlib.Path(romfs_relative).name.rsplit(".pack.zs", 1)[0]
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
        print(f"Cache hits {entry_hit}/{entry_total}")

    return ainb_cache
