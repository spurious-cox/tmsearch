"""py2app build for TMsearch.app — v1.2.0

    ./venv/bin/python setup.py py2app

The venv is built on the python.org Python, which is universal (arm64 and
x86_64) and built for macOS 11. py2app copies the interpreter it runs under,
so that is what makes the app run on Intel Macs and on older macOS. A
Homebrew Python would tie the app to the macOS it was built on.

TMsearch uses only the standard library.
"""

import re
from pathlib import Path

from setuptools import setup

APP = ["tmsearch.py"]
# The `tmsearch` command. Homebrew links it onto the PATH; it runs the app's
# own executable, so the terminal and Finder use the same Python.
DATA_FILES = [("", ["tmsearch"])]


def app_version():
    """The single source of truth: APP_VERSION in tmsearch.py."""
    source = Path(__file__).with_name("tmsearch.py").read_text()
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', source, re.MULTILINE)
    if not match:
        raise SystemExit("setup.py: APP_VERSION not found in tmsearch.py")
    return match.group(1)


VERSION = app_version()

OPTIONS = {
    "argv_emulation": False,
    "arch": "universal2",
    "excludes": ["tkinter", "test", "unittest", "pydoc_data"],
    # Imported inside try/except, which py2app's import scan skips. Without
    # it the terminal prompts have no arrow keys or line editing.
    "includes": ["readline"],
    "iconfile": "TMsearch.icns",
    "plist": {
        "CFBundleName": "TMsearch",
        "CFBundleDisplayName": "TMsearch",
        "CFBundleIdentifier": "com.timmccoy.tmsearch",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription":
            "TMsearch shows dialogs and reveals restored files.",
        "NSHumanReadableCopyright": "© 2026 Tim McCoy",
    },
}

setup(
    app=APP,
    name="TMsearch",
    version=VERSION,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
