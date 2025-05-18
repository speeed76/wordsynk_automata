# filename: conftest.py
import sys
import os
import logging # Import standard logging for conftest

# Add the project root directory to the Python path
# This ensures that modules like 'parsers', 'utils', etc., can be imported correctly by tests
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Use standard print or basic logging here, as your custom logger might not be set up yet
# or might create circular dependencies if conftest tries to import it too early.
print(f"[conftest.py] Project root added to sys.path: {project_root}")