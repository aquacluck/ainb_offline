from dataclasses import dataclass
import sqlite3
from typing import *

from app_types import *
import db


class PackIndex:
    TABLE = "pack_index"
    @classmethod
    def emit_create(cls) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {cls.TABLE}(
                packfile TEXT,
                extension TEXT,
                internal_filename_csv TEXT,
                PRIMARY KEY(packfile ASC, extension ASC)
            ) WITHOUT ROWID;"""

    @classmethod
    def get_all_entries_by_extension(cls, conn: sqlite3.Connection, ext: str) -> Dict[str, Dict[str, PackIndexEntry]]:
        # {"Pack/Actor/DgnObj_UrMom.pack.zs": {"internalfile1.ainb": PackIndexEntry, "internalfile2.ainb": PackIndexEntry}}
        # {"Root": {"Logic/OpeningField_1856.logic.root.ainb": PackIndexEntry}}

        res = conn.execute(f"""
            SELECT packfile, internal_filename_csv
            FROM {cls.TABLE}
            WHERE extension = ?;
            /* order */
            """, (ext,))

        out = {"Root": {}}
        for packfile, internal_filename_csv in res:
            # Packs with no results stay empty like this, internal_filename_csv="" negative cache
            packfile = PackIndexEntry.fix_backslashes(packfile)
            out[packfile] = {}
            if internal_filename_csv:
                for internalfile in internal_filename_csv.split(","):
                    internalfile = PackIndexEntry.fix_backslashes(internalfile)
                    out[packfile][internalfile] = PackIndexEntry(internalfile=internalfile, packfile=packfile, extension=ext)
        return out

    @classmethod
    def persist_one_pack_one_extension(cls, conn: sqlite3.Connection, packfile: str, extension: str,  internalfiles: List[str]):
        # packfile and extension must match across all internalfiles
        internal_filename_csv = ",".join([PackIndexEntry.fix_backslashes(f) for f in internalfiles])
        conn.execute(f"""
            INSERT OR REPLACE INTO {cls.TABLE}(packfile, extension, internal_filename_csv)
            VALUES (?, ?, ?);
            """, (PackIndexEntry.fix_backslashes(packfile), extension, internal_filename_csv))
