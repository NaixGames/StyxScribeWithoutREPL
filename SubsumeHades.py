#!/usr/bin/python3
import os
import sys
from pathlib import Path

from Hades.StyxScribe import StyxScribe

os.chdir(Path(sys.argv[0]).parent)

subsume = StyxScribe(
    "Hades",
    "x64",
    [
        "DebugDraw=true",
        "DebugKeysEnabled=true",
        "RequireFocusToUpdate=false",
    ],
)
subsume.LoadPlugins()
subsume.Launch()
