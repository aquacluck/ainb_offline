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
                param_names_json TEXT,
                param_details_json TEXT,
                PRIMARY KEY(fullfile ASC, node_index ASC)
            ) WITHOUT ROWID;""",
            f"""CREATE INDEX IF NOT EXISTS idx_lookup ON {cls.TABLE} (node_type, file_category, param_names_json);"""
        ]

    '''
    @classmethod
    def get_all_shapes_for_node_type(cls, conn: sqlite3.Connection, node_type: str) -> List[AinbNodeParamShape]:
        res = conn.execute(f"""
            SELECT { ", ".join(cls.INT_COLUMNS) }
            FROM {cls.TABLE}
            WHERE node_type = ?;
            /* order */
            """, (node_type,))
        return [AinbNodeParamShape(node_type, param_counts=row[1:]) for row in res]
    '''

    @classmethod
    def persist(cls, conn: sqlite3.Connection, fullfile: str, file_category: str, node_type: str, node_index: int, param_names_json: dict, param_details_json: dict):
        conn.execute(f"""
            INSERT OR REPLACE INTO {cls.TABLE}
            (fullfile, file_category, node_type, node_index, param_names_json, param_details_json)
            VALUES (?, ?, ?, ?, ?, ?);
            """, (fullfile, file_category, node_type, node_index, json.dumps(param_names_json), json.dumps(param_details_json)))

