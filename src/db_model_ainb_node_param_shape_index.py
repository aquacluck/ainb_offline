from dataclasses import dataclass
import json
from typing import *
import sqlite3


# observations
# each node type has only one shape, except for Element_Expression which is heavily overloaded.
# iff user defined, the effective node type is the "Name" field which is always defined.
# iff not user defined, the "Node Type" will start with "Element_" and the "Name" field is always empty.

@dataclass
class AinbNodeParamShape:
    node_type: str
    #param_details_json
    param_counts: Tuple[int]


class AinbNodeParamShapeIndex:
    TABLE = "ainb_node_param_shape_index"
    # XXX should we hash the row into a primary key to make uniqueness simpler?
    # Column for each: {immediate, input, output} x {int, bool, float, string, vec3f, userdefined}
    INT_COLUMNS = (
        "imm_int_n",
        "imm_bool_n",
        "imm_float_n",
        "imm_string_n",
        "imm_vec3f_n",
        "imm_userdefined_n",
        "in_int_n",
        "in_bool_n",
        "in_float_n",
        "in_string_n",
        "in_vec3f_n",
        "in_userdefined_n",
        "out_int_n",
        "out_bool_n",
        "out_float_n",
        "out_string_n",
        "out_vec3f_n",
        "out_userdefined_n",
    )

    @classmethod
    def emit_create(cls) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {cls.TABLE}(
                node_type TEXT,
                param_details_json TEXT,
                /* { ", ".join([f"{name} INT" for name in cls.INT_COLUMNS]) }, */
                UNIQUE(
                    node_type,
                    param_details_json
                    /* { ", ".join(cls.INT_COLUMNS) } */
                )
            );"""

    pass

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
    def persist_shape(cls, conn: sqlite3.Connection, node_type: str, param_details_json: str): # param_counts: Tuple[int]):
        conn.execute(f"""
            INSERT OR IGNORE INTO {cls.TABLE}
            (node_type, param_details_json /* { ", ".join(cls.INT_COLUMNS) } */)
            VALUES (?, ? /* { ", ".join("?" * len(cls.INT_COLUMNS)) } */);
            """, (node_type, json.dumps(param_details_json))) #*param_counts))

