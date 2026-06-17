from enum import StrEnum


class StatName(StrEnum):
    CURRENCY = "currency"
    BUMPS = "bumps"
    XP = "xp"
    LEVEL = "level"


class PlainStat(StrEnum):
    BUMPS = "bumps"
    XP = "xp"
