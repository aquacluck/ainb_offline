import json
import sqlite3
from typing import *

# Element_Expression is not used in Logic


class AinbFileParamNameUsageIndex:
    TABLE = "ainb_file_param_name_usage_index"

    @classmethod
    def emit_create(cls) -> str:
        return [f"""
            CREATE TABLE IF NOT EXISTS {cls.TABLE}(
                file_category TEXT,
                node_type TEXT,
                param_names_json TEXT,
                usage_count INT,
                is_most_common INT,
                PRIMARY KEY(file_category ASC, node_type ASC, param_names_json ASC)
            ) WITHOUT ROWID;""",
            f"""CREATE INDEX IF NOT EXISTS idx_afpnui_lookup1 ON {cls.TABLE} (file_category, node_type, param_names_json);""",
            f"""CREATE INDEX IF NOT EXISTS idx_afpnui_lookup2 ON {cls.TABLE} (file_category, node_type, is_most_common);""",
        ]

    @classmethod
    def persist(cls, conn: sqlite3.Connection, file_category: str, node_type: str, param_names_json: dict):
        # Count which param names are most often used (to call this node type, in this ainb file category)
        conn.execute(f"""
            INSERT INTO {cls.TABLE}
            (file_category, node_type, param_names_json, usage_count, is_most_common)
            VALUES (?, ?, json(?), 1, 0)
            ON CONFLICT DO UPDATE SET usage_count = usage_count + 1;
            """, (file_category, node_type, json.dumps(param_names_json)))

    @classmethod
    def postprocess(cls, conn: sqlite3.Connection):
        # After all rows are persisted, mark the most common
        conn.execute(f"""
            UPDATE {cls.TABLE} AS t1
            SET is_most_common = 1
            WHERE t1.usage_count = (
                SELECT MAX(usage_count)
                FROM ainb_file_param_name_usage_index AS t2
                WHERE t2.file_category = t1.file_category
                AND t2.node_type = t1.node_type
            );""")

    @classmethod
    def get_node_types(cls, conn: sqlite3.Connection, file_category: str) -> List[Tuple[str, str]]:
        return [(r[0], r[1]) for r in conn.execute(f"""
            SELECT node_type, param_names_json
            FROM {cls.TABLE}
            WHERE file_category = ?
            AND is_most_common = 1
            GROUP BY file_category, node_type
            ORDER BY node_type ASC;
            """, (file_category,)).fetchall()]
