#!/usr/bin/python3
import os
import sys
from pathlib import Path

from StyxScribe import StyxScribe

os.chdir(Path(sys.argv[0]).parent)

subsume = StyxScribe(
    "Pyre",
    "x64",
    [
        "DebugDraw=true",
        "DebugKeysEnabled=true",
        "RequireFocusToUpdate=false",
    ],
)
subsume.LoadPlugins()
subsume.Launch()
