"""
WorkMind Version Management
CONFIDENTIAL - PRIVATE REPOSITORY
"""

VERSION = "1.0.0"
VERSION_TUPLE = (1, 0, 0)
BUILD_DATE = "2026-04-03"
CODENAME = "Nexus"

def get_version() -> str:
    return VERSION

def get_full_version() -> str:
    return f"{VERSION} ({CODENAME}) [{BUILD_DATE}]"
