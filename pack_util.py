import functools
from typing import *

import zstandard as zstd
from sarc import SARC
import dearpygui.dearpygui as dpg

from app_types import *


@functools.lru_cache
def get_zsdics(zsdic_filename: str) -> Dict[str, zstd.ZstdCompressionDict]:
    dctx = get_zstd_decompression_ctx(dict_data=None)
    archive = SARC(dctx.decompress(open(zsdic_filename, "rb").read()))
    return { fn: zstd.ZstdCompressionDict(archive.get_file_data(fn)) for fn in archive.list_files() }


@functools.lru_cache  # Real Coders would do a thread pool here...
def get_zstd_decompression_ctx(dict_data: Optional[zstd.ZstdCompressionDict] = None) -> zstd.ZstdDecompressor:
    return zstd.ZstdDecompressor(dict_data=dict_data)


@functools.lru_cache
def get_pack_decompression_ctx() -> zstd.ZstdDecompressor:
    filename = dpg.get_value(AppConfigKeys.ZSDIC_FILENAME)
    pack_zsdic = get_zsdics(filename)["pack.zsdic"]
    return get_zstd_decompression_ctx(dict_data=pack_zsdic)


def load_file_from_pack(packfile: str, internalfile: str) -> memoryview:
    dctx = get_pack_decompression_ctx()
    archive = SARC(dctx.decompress(open(packfile, "rb").read()))
    return archive.get_file_data(internalfile)


def load_all_files_from_pack(packname: str) -> Dict[str, memoryview]:
    dctx = get_pack_decompression_ctx()
    archive = SARC(dctx.decompress(open(packname, "rb").read()))
    return { fn: archive.get_file_data(fn) for fn in sorted(archive.list_files()) }


def get_pack_internal_filenames(packname: str) -> List[str]:
    dctx = get_pack_decompression_ctx()
    archive = SARC(dctx.decompress(open(packname, "rb").read()))
    return sorted(archive.list_files())
