#!/usr/bin/env python3
"""Run GitFlow Assistant from a source checkout: ``python main.py [command]``."""

import sys

from gitflow_assistant.app import main

if __name__ == "__main__":
    sys.exit(main())
