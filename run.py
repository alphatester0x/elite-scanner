#!/usr/bin/env python3
"""Entry point for GitHub Actions or local execution."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from elite_scanner.main import main

if __name__ == "__main__":
    main()
