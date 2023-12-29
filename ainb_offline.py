#!/usr/bin/env python3
import os

# run from anywhere. might interfere with opening from argv, but we normalize those to project romfs anyways?
abspath = os.path.abspath(__file__)
thisdir = os.path.dirname(abspath)
os.chdir(thisdir)

from src import main
main.main()
