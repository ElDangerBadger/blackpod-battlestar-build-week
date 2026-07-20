#!/usr/bin/env python3
"""CLI shim for the read-only LIVE mission demo packager."""

from blackpod_build_week.live_demo_packager import main


if __name__ == "__main__":
    raise SystemExit(main())
