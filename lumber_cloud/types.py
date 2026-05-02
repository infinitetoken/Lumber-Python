from enum import IntEnum


class LogLevel(IntEnum):
    """
    Mirrors Lumber-Kit LogLevel const enum.
    Numeric values are the API wire contract — do not change.
    """
    Debug = 0
    Info  = 1
    Warn  = 2
    Error = 3
    Fatal = 4
