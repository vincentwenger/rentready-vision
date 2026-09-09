from __future__ import annotations

from enum import StrEnum

TAXONOMY_VERSION = "rentready-issues/1.0"


class IssueGroup(StrEnum):
    WALLS = "walls"
    FLOORING = "flooring"
    FIXTURES = "fixtures"
    GENERAL = "general"
    OTHER = "other"


class IssueCategory(StrEnum):
    # Walls
    WALL_HOLE = "wall_hole"
    WALL_CRACK = "wall_crack"
    PAINT_DAMAGE = "paint_damage"
    WALL_STAIN = "wall_stain"
    TRIM_DAMAGE = "trim_damage"

    # Flooring
    FLOOR_DAMAGE = "floor_damage"
    FLOOR_STAIN = "floor_stain"
    BROKEN_TILE = "broken_tile"

    # Fixtures
    FIXTURE_DAMAGE = "fixture_damage"
    MISSING_HARDWARE = "missing_hardware"

    # General
    VISIBLE_STAINING = "visible_staining"
    CLEANLINESS = "cleanliness"
    VISIBLE_DAMAGE = "visible_damage"

    # Escape hatch. The detector must provide other_label when this is used.
    OTHER = "other"


CATEGORY_GROUP: dict[IssueCategory, IssueGroup] = {
    IssueCategory.WALL_HOLE: IssueGroup.WALLS,
    IssueCategory.WALL_CRACK: IssueGroup.WALLS,
    IssueCategory.PAINT_DAMAGE: IssueGroup.WALLS,
    IssueCategory.WALL_STAIN: IssueGroup.WALLS,
    IssueCategory.TRIM_DAMAGE: IssueGroup.WALLS,
    IssueCategory.FLOOR_DAMAGE: IssueGroup.FLOORING,
    IssueCategory.FLOOR_STAIN: IssueGroup.FLOORING,
    IssueCategory.BROKEN_TILE: IssueGroup.FLOORING,
    IssueCategory.FIXTURE_DAMAGE: IssueGroup.FIXTURES,
    IssueCategory.MISSING_HARDWARE: IssueGroup.FIXTURES,
    IssueCategory.VISIBLE_STAINING: IssueGroup.GENERAL,
    IssueCategory.CLEANLINESS: IssueGroup.GENERAL,
    IssueCategory.VISIBLE_DAMAGE: IssueGroup.GENERAL,
    IssueCategory.OTHER: IssueGroup.OTHER,
}

# The user-specified named taxonomy contains 13 categories; `other` is the
# controlled escape hatch and is not counted as one of the 13 named categories.
NAMED_CATEGORIES: tuple[IssueCategory, ...] = tuple(
    category for category in IssueCategory if category is not IssueCategory.OTHER
)
ALL_CATEGORIES: tuple[IssueCategory, ...] = tuple(IssueCategory)


def category_group(category: IssueCategory | str) -> IssueGroup:
    try:
        resolved = category if isinstance(category, IssueCategory) else IssueCategory(category)
    except ValueError:
        resolved = IssueCategory.OTHER
    return CATEGORY_GROUP[resolved]


def taxonomy_payload() -> dict:
    groups: dict[str, list[str]] = {}
    for category in NAMED_CATEGORIES:
        groups.setdefault(CATEGORY_GROUP[category].value, []).append(category.value)
    return {
        "version": TAXONOMY_VERSION,
        "named_category_count": len(NAMED_CATEGORIES),
        "groups": groups,
        "escape_hatch": IssueCategory.OTHER.value,
    }
