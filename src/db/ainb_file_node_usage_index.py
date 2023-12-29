from collections import OrderedDict
import json
import sqlite3
from typing import *


class AinbFileNodeUsageIndex:
    TABLE = "ainb_file_node_usage_index"

    @classmethod
    def emit_create(cls) -> str:
        return [f"""
            CREATE TABLE IF NOT EXISTS {cls.TABLE}(
                fullfile TEXT,
                file_category TEXT,
                node_type TEXT,
                node_index INT,
                param_details_json TEXT,
                PRIMARY KEY(fullfile ASC, node_index ASC)
            ) WITHOUT ROWID;""",
            f"""CREATE INDEX IF NOT EXISTS idx_afnui_lookup1 ON {cls.TABLE} (file_category, node_type, param_details_json);""",
        ]


    @classmethod
    def get_common_param_details(cls, conn: sqlite3.Connection, file_category: str, node_type: str) -> List[Tuple[dict, int]]:
        cursor = conn.execute(f"""
            SELECT param_details_json, COUNT(*) AS n
            FROM {cls.TABLE}
            WHERE node_type = ?
            AND file_category = ?
            GROUP BY param_details_json
            ORDER BY n DESC LIMIT 5;
            """, (node_type, file_category))

        return [(json.loads(row[0]), row[1]) for row in cursor.fetchall()]


    @classmethod
    def persist(cls, conn: sqlite3.Connection, fullfile: str, file_category: str, node_type: str, node_index: int, param_details_json: dict):
        conn.execute(f"""
            INSERT OR REPLACE INTO {cls.TABLE}
            (fullfile, file_category, node_type, node_index, param_details_json)
            VALUES (?, ?, ?, ?, ?, json(?));
            """, (fullfile, file_category, node_type, node_index, json.dumps(param_details_json)))

