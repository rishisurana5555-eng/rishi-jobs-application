"""
Streamlit Community Cloud entry point.

The deployment's main file is app.py at the repo root; the contract generator
lives in contract/. This runs contract/app.py as if it were the main script.
"""

import os
import runpy
import sys

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract")
sys.path.insert(0, APP_DIR)  # so contract/app.py can import api and contract_generator

runpy.run_path(os.path.join(APP_DIR, "app.py"), run_name="__main__")
