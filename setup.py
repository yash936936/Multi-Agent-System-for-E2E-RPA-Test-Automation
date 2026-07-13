# setup.py
#
# Required shim: setuptools calls `setup.py egg_info` internally when performing
# an editable install (`pip install -e .`).  Without a setup() call in this file,
# no .egg-info directory is generated, causing the error:
#   AssertionError: Exactly one .egg-info should have been produced, but found 0
#
# A bare setup() with no arguments is safe — setuptools reads ALL real project
# metadata (name, version, packages, dependencies, entry-points, …) from
# pyproject.toml via PEP 517/518.  This file must NOT do argparse or sys.argv
# inspection because pip invokes it with its own subcommands (egg_info,
# dist_info, bdist_wheel, …) and any arg-handling here will break those calls.
#
# For the AURA one-click installer, run:
#   python install.py
from setuptools import setup

setup()
