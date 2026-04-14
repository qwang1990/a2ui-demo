from __future__ import annotations

# v0.8 standard catalog component keys (see google/A2UI specification).
# https://github.com/google/A2UI/blob/main/specification/v0_8/json/standard_catalog_definition.json
STANDARD_CATALOG_COMPONENT_NAMES: frozenset[str] = frozenset(
    {
        "Text",
        "Image",
        "Icon",
        "Video",
        "AudioPlayer",
        "Row",
        "Column",
        "List",
        "Card",
        "Tabs",
        "Divider",
        "Modal",
        "Button",
        "CheckBox",
        "TextField",
        "DateTimeInput",
        "MultipleChoice",
        "Slider",
    }
)
