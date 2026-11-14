"""Strict YAML loader that rejects duplicated mapping keys.

``safe_load`` keeps the last value for a repeated key, so a card with two
``rates`` blocks would silently drop one. A pricing error is worse than a
startup failure, so the duplicate is rejected instead. The loader lives here
so the card parser stays within the repository's file-size limit.
"""

import collections.abc as cabc

import yaml
import yaml.constructor
import yaml.resolver


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects a mapping with a duplicated key."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    *,
    deep: bool = False,
) -> dict[object, object]:
    """Build a mapping, failing on the first duplicated key."""
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, cabc.Hashable):
            # A sequence key such as ``? [a, b]`` constructs to a list, which
            # cannot be a mapping key; report it as a YAML error so the caller
            # still gets a catalogue error naming the file.
            msg = f"found unhashable key {key!r}"
            raise yaml.constructor.ConstructorError(  # ruff: ignore[raise-vanilla-args]  # PyYAML needs the context and problem marks.
                "while constructing a mapping",
                node.start_mark,
                msg,
                key_node.start_mark,
            )
        if key in mapping:
            msg = f"found duplicate key {key!r}"
            raise yaml.constructor.ConstructorError(  # ruff: ignore[raise-vanilla-args]  # PyYAML needs the context and problem marks.
                "while constructing a mapping",
                node.start_mark,
                msg,
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)
