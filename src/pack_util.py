from collections import defaultdict
import functools
from typing import *
import io

import dearpygui.dearpygui as dpg
import sarc
import zstandard as zstd

from .app_types import *


FileDataByExt = Dict["RomfsFileTypes", Dict[str, memoryview]]


@functools.lru_cache
def get_zsdics() -> Dict[str, zstd.ZstdCompressionDict]:
    zsdic_pack = TitleVersion.get().zsdic_pack
    if not zsdic_pack:
        return dict()

    romfs = dpg.get_value(AppConfigKeys.ROMFS_PATH)
    dctx = get_zstd_decompression_ctx(dict_data=None)
    archive = sarc.SARC(dctx.decompress(open(f"{romfs}/{zsdic_pack}", "rb").read()))
    return { fn: zstd.ZstdCompressionDict(archive.get_file_data(fn)) for fn in archive.list_files() }


@functools.lru_cache  # Real Coders would do a thread pool here...
def get_zstd_decompression_ctx(dict_data: Optional[zstd.ZstdCompressionDict] = None) -> zstd.ZstdDecompressor:
    return zstd.ZstdDecompressor(dict_data=dict_data)


@functools.lru_cache
def get_pack_decompression_ctx() -> zstd.ZstdDecompressor:
    pack_zsdic = get_zsdics().get("pack.zsdic")
    return get_zstd_decompression_ctx(dict_data=pack_zsdic)


@functools.lru_cache
def get_pack_compression_ctx() -> zstd.ZstdCompressor:
    pack_zsdic = get_zsdics().get("pack.zsdic")
    return zstd.ZstdCompressor(level=10, dict_data=pack_zsdic)


def save_file_to_pack(packfile: str, internalfile: str, internaldata: io.BytesIO):
    # Make an updated sarc file from existing modfs
    dctx = get_pack_decompression_ctx()
    with open(packfile, "rb") as oldf:
        archive = sarc.SARC(dctx.decompress(oldf.read()))
    writer = sarc.make_writer_from_sarc(archive)
    writer.delete_file(internalfile)
    writer.add_file(internalfile, internaldata.getvalue())
    updated_sarc = io.BytesIO()
    writer.write(updated_sarc)

    # Compress and save
    cctx = get_pack_compression_ctx()
    data = cctx.compress(updated_sarc.getvalue())
    # TODO better sanity check?
    if len(data) < 256:  # arbitrary
        raise Exception(f"Refusing to overwrite {packfile} with only {len(data)}B compressed")
    with open(packfile, "wb") as out:
        out.write(data)


def load_file_from_pack(packfile: str, internalfile: str) -> memoryview:
    dctx = get_pack_decompression_ctx()
    archive = sarc.SARC(dctx.decompress(open(packfile, "rb").read()))
    return archive.get_file_data(internalfile)


def load_all_files_from_pack(packname: str) -> Dict[str, memoryview]:
    dctx = get_pack_decompression_ctx()
    archive = sarc.SARC(dctx.decompress(open(packname, "rb").read()))
    return { fn: archive.get_file_data(fn) for fn in sorted(archive.list_files()) }


def load_ext_files_from_pack(packname: str, extensions: List["RomfsFileTypes"]) -> FileDataByExt:
    out = defaultdict(dict)
    dctx = get_pack_decompression_ctx()
    archive = sarc.SARC(dctx.decompress(open(packname, "rb").read()))
    for f in sorted(archive.list_files()):
        if e:= RomfsFileTypes.get_from_filename(f):
            out[e][f] = archive.get_file_data(f)
    return out


def get_pack_internal_filenames(packname: str) -> List[str]:
    dctx = get_pack_decompression_ctx()
    archive = sarc.SARC(dctx.decompress(open(packname, "rb").read()))
    return sorted(archive.list_files())

# TODO natural sort + ignore case, they're too inconsistent
