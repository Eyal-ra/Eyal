"""
GUI automation for the Ravgonit Windows desktop app.

This module is intentionally a skeleton. The exact selectors
(window class, control IDs, button labels) must be discovered locally
using `pywinauto`'s inspect.exe or `print_control_identifiers()` and
then plugged in here.

Recommended workflow to populate the selectors:
    from pywinauto import Application
    app = Application(backend="uia").connect(title_re="רבגונית.*")
    app.top_window().print_control_identifiers()
"""

import platform
import time
from dataclasses import dataclass


@dataclass
class RavgonitCustomer:
    customer_number: str
    full_name: str


class RavgonitGUI:
    def __init__(self, config: dict):
        self.exe_path = config["executable_path"]
        self.window_title_regex = config["window_title_regex"]
        self.search_field = config["customer_search_field"]
        self.full_name_field = config["full_name_field"]
        self.save_button = config["save_button"]
        self.startup_wait = config.get("startup_wait_seconds", 5)
        self._app = None

    def connect(self):
        if platform.system() != "Windows":
            raise RuntimeError("Ravgonit GUI automation requires Windows")
        from pywinauto import Application
        try:
            self._app = Application(backend="uia").connect(title_re=self.window_title_regex)
        except Exception:
            self._app = Application(backend="uia").start(self.exe_path)
            time.sleep(self.startup_wait)
            self._app = Application(backend="uia").connect(title_re=self.window_title_regex)

    def find_customer(self, customer_number: str) -> RavgonitCustomer:
        if self._app is None:
            self.connect()
        # TODO: implement once local inspection of Ravgonit windows is done.
        # Steps a human user takes:
        #   1. Open "customers" screen
        #   2. Type customer_number into search box
        #   3. Press Enter / click search
        #   4. Read the "full name" field from the customer card
        raise NotImplementedError("find_customer - inspect Ravgonit windows locally and wire up selectors")

    def update_full_name(self, customer_number: str, new_full_name: str) -> None:
        if self._app is None:
            self.connect()
        # TODO: implement: focus the customer, clear the name field,
        # type the new value, click save, wait for confirmation dialog.
        raise NotImplementedError("update_full_name - inspect Ravgonit windows locally and wire up selectors")
