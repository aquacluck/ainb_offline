import os
import pathlib
import sqlite3
import threading
from typing import *

import dearpygui.dearpygui as dpg

from ..app_types import *
from .pack_index import PackIndex
from .ainb_node_param_shape_index import AinbNodeParamShapeIndex


tls = threading.local()

class Connection:
    connection: sqlite3.Connection  = None

    @classmethod
    def get(cls) -> sqlite3.Connection:
        global tls
        if not hasattr(tls, "GLOBAL_INSTANCE"):
            conn = tls.GLOBAL_INSTANCE = cls()
            conn.db_init()
        return tls.GLOBAL_INSTANCE.connection

    def db_init(self):
        appvar = dpg.get_value(AppConfigKeys.APPVAR_PATH)
        title_version = dpg.get_value(AppConfigKeys.TITLE_VERSION)
        db_file = f"{appvar}/{title_version}/project.db"

        pathlib.Path(db_file).parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            # `file:` seems broken on windows? and the uri was the only way to set autocommit till 3.12
            self.connection = sqlite3.connect(db_file)
            if hasattr(self.connection, "autocommit"):
                self.connection.autocommit = False
        else:
            self.connection = sqlite3.connect(f"file:{db_file}?mode=rwc&autocommit=false&cache=shared")

        self.create_tables()

    def create_tables(self):
        with self.connection:
            self.connection.execute(PackIndex.emit_create())
            self.connection.execute(AinbNodeParamShapeIndex.emit_create())
