#!/usr/bin/python3
from StyxScribe import StyxScribe

import sys, os
from pathlib import Path
os.chdir(Path(sys.argv[0]).parent)

subsume = StyxScribe("Pyre", "x64", [
    "DebugDraw=true",
    "DebugKeysEnabled=true",
    "RequireFocusToUpdate=false",
    ])
subsume.LoadPlugins()
subsume.Launch()
