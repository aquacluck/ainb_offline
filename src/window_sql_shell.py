from typing import *
from dataclasses import dataclass

import dearpygui.dearpygui as dpg

from app_types import *
import db


@dataclass
class QueryHistoryEntry:
    query: str
    rows: list
    tag: str = None


class WindowSqlShell:
    LIMIT_HISTORY = 20;

    @classmethod
    def create_anon_oneshot(cls) -> None:
        window = cls()
        window.create()

    def __init__(self):
        self.query_history: List[QueryHistoryEntry] = []

    def create(self):
        with dpg.window(label="SQL Shell", width=800, height=600, pos=[600, 200]) as dpg_window:
            self.dpg_window = dpg_window
            self.output_group = dpg.add_group()

            def callback(sender, query, u):
                is_shift = dpg.is_key_down(0x154) or dpg.is_key_down(0x158)
                is_enter = dpg.is_key_pressed(0x101)
                if is_shift and is_enter:
                    # Shift enter to run
                    with db.Connection.get() as conn:
                        rows = [r for r in conn.execute(query)]
                        self.append_output(QueryHistoryEntry(query, rows, tag=None))
                        # clearing input text is harder than it should be...
                        # these ideas seem to crash https://github.com/hoffstadt/DearPyGui/issues/1783

            dpg.add_input_text(callback=callback, multiline=True, tab_input=True, width=-1, height=200)

    def append_output(self, entry: QueryHistoryEntry):
        self.query_history.append(entry)
        with dpg.group(parent=self.output_group) as entry_tag:
            entry.tag = entry_tag
            dpg.add_text(entry.query)
            dpg.add_text(str(entry.rows))

        if len(self.query_history) > self.LIMIT_HISTORY:
            dpg.delete_item(self.query_history[0].tag)
            del self.query_history[0]

