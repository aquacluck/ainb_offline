import sqlite3
from typing import *

import orjson

# Element_Expression is not used in Logic
# Element_Expression is the only node type with multiple signatures (userdefined param class sig uniqueness tbd)


class AinbFileNodeUsageIndex:
    TABLE = "ainb_file_node_usage_index"

    @classmethod
    def emit_create(cls) -> List[str]:
        return [f"""
            CREATE TABLE IF NOT EXISTS {cls.TABLE}(
                file_category TEXT,
                node_type TEXT,
                param_details_json TEXT,
                detailset_usage_count INT,
                is_most_common INT,
                PRIMARY KEY(file_category ASC, node_type ASC, param_details_json ASC)
            ) WITHOUT ROWID;""",
            f"""CREATE INDEX IF NOT EXISTS idx_afnui_lookup1 ON {cls.TABLE} (file_category, node_type, is_most_common);""",
        ]

    @classmethod
    def persist(cls, conn: sqlite3.Connection, file_category: str, node_type: str, param_details_json: dict) -> None:
        # Count which full param data are most often used (to call this node type, in this ainb file category)
        conn.execute(f"""
            INSERT INTO {cls.TABLE}
            (file_category, node_type, param_details_json, detailset_usage_count, is_most_common)
            VALUES (?, ?, ?, 1, 0)
            ON CONFLICT DO UPDATE SET detailset_usage_count = detailset_usage_count + 1
            """, (file_category, node_type, orjson.dumps(param_details_json)))

    @classmethod
    def postprocess(cls, conn: sqlite3.Connection) -> None:
        # After all rows are persisted, mark the most common
        conn.execute(f"""
            UPDATE {cls.TABLE} AS t1
            SET is_most_common = 1
            WHERE t1.detailset_usage_count = (
                SELECT MAX(detailset_usage_count)
                FROM {cls.TABLE} AS t2
                WHERE t2.file_category = t1.file_category
                AND t2.node_type = t1.node_type
            );""")

    @classmethod
    def get_node_types(cls, conn: sqlite3.Connection, file_category: str) -> List[Tuple[str, dict]]:
        return [(r[0], orjson.loads(r[1])) for r in conn.execute(f"""
            SELECT node_type, param_details_json
            FROM {cls.TABLE}
            WHERE file_category = ?
            AND is_most_common = 1
            GROUP BY file_category, node_type
            ORDER BY node_type ASC;
            """, (file_category,)).fetchall()]
