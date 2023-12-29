from typing import *
from dataclasses import dataclass

import dearpygui.dearpygui as dpg

from .app_types import *
from . import db


@dataclass
class QueryHistoryEntry:
    query: str = ""
    rows: tuple = ()
    tag: str = None
    any_success: bool = False


class WindowSqlShell:
    LIMIT_HISTORY = 20

    @classmethod
    def create_anon_oneshot(cls, immediate_query: str = None) -> None:
        window = cls()
        window.create(immediate_query)

    def __init__(self):
        self.query_history: List[QueryHistoryEntry] = []

    def create(self, immediate_query: str = None):
        with dpg.window(label="SQL Shell", width=800, height=600, pos=[600, 200]) as dpg_window:
            self.dpg_window = dpg_window
            self.output_group = dpg.add_group()
            qbox = self.append_new_query_prompt()
            if immediate_query:
                dpg.set_value(qbox, immediate_query)

    def append_new_query_prompt(self):
        def callback(sender, query, entry):
            entry.query = query
            entry_tag = entry.tag

            #is_shift = dpg.is_key_down(0x154) or dpg.is_key_down(0x158)
            #is_enter = dpg.is_key_pressed(0x101)
            err = None
            with db.Connection.get() as conn:
                try:
                    entry.rows = [r for r in conn.execute(query)]
                except Exception as e:
                    err = e

            if err:
                entry.rows = []
                dpg.set_value(f"{entry_tag}/error", str(err))
                dpg.hide_item(f"{entry_tag}/output")
                dpg.delete_item(f"{entry_tag}/output", children_only=True)
                dpg.show_item(f"{entry_tag}/error")
                dpg.focus_item(f"{entry_tag}/input")
            else:
                dpg.hide_item(f"{entry_tag}/error")
                dpg.delete_item(f"{entry_tag}/output", children_only=True)
                # display rows to table
                if len(entry.rows) > 0:
                    with dpg.table(parent=f"{entry_tag}/output"):
                        for i in range(len(entry.rows[0])):
                            dpg.add_table_column()
                        for row in entry.rows:
                            with dpg.table_row():
                                for c in row:
                                    dpg.add_text(c)

                dpg.show_item(f"{entry_tag}/output")
                if not entry.any_success:
                    # add a prompt when a query first succeeds
                    entry.any_success = True
                    self.append_new_query_prompt()
                else:
                    # keep line focused after edits
                    dpg.focus_item(f"{entry_tag}/input")

        with dpg.group(parent=self.output_group) as entry_tag:
            entry = QueryHistoryEntry(tag=entry_tag)
            self.append_history(entry)
            qbox = dpg.add_input_text(tag=f"{entry_tag}/input", hint="select 420", callback=callback, on_enter=True, user_data=entry, width=-1)
            dpg.add_text("", show=False, tag=f"{entry_tag}/error", color=AppStyleColors.ERRTEXT.to_rgba32())
            dpg.add_group(show=False, tag=f"{entry_tag}/output")
            dpg.focus_item(qbox)

        return qbox

    def append_history(self, entry: QueryHistoryEntry):
        self.query_history.append(entry)
        if len(self.query_history) > self.LIMIT_HISTORY:
            dpg.delete_item(self.query_history[0].tag)
            del self.query_history[0]

