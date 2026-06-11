# Cacheflow - every physics cache in your scene: one panel, one bake queue.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copyright (C) 2026 Jonathan Lamas
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.

bl_info = {
    "name": "Cacheflow",
    "author": "Jonathan Lamas",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N) > Cache",
    "description": "Every physics cache in your scene - one panel, one bake queue",
    "category": "Physics",
}

import bpy
from bpy.props import (StringProperty, IntProperty, BoolProperty,
                       EnumProperty, CollectionProperty, FloatProperty)
from bpy.types import PropertyGroup

from . import core, ops, ui

KIND_ENUM = [(k, k.title(), "") for k in core.KIND_ICONS]
STATUS_ENUM = [(s, s.title(), "") for s in
               ('BAKED', 'BAKING', 'PARTIAL', 'EMPTY', 'UNKNOWN')]


class CACHEFLOW_item(PropertyGroup):
    kind: EnumProperty(items=KIND_ENUM)
    owner: StringProperty()
    label: StringProperty()
    status: EnumProperty(items=STATUS_ENUM, default='EMPTY')
    path: StringProperty()
    frame_start: IntProperty()
    frame_end: IntProperty()
    object_name: StringProperty()
    modifier_name: StringProperty()
    index: IntProperty(default=-1)
    stale: BoolProperty(default=False)
    disk: BoolProperty(default=True)
    # Float: cache sizes routinely exceed the 2 GB limit of a 32-bit int
    size_bytes: FloatProperty(default=-1.0, min=-1.0)


CLASSES = (CACHEFLOW_item,) + ops.CLASSES + ui.CLASSES


def _active_changed(self, context):
    """Clicking a row in the list selects that cache's object(s) in the
    viewport (the whole rigid body collection for the scene-level sim)."""
    items = self.cacheflow_items
    idx = self.cacheflow_active
    if 0 <= idx < len(items):
        try:
            ops.select_item_objects(context, items[idx])
        except Exception:
            pass


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cacheflow_items = CollectionProperty(type=CACHEFLOW_item)
    bpy.types.Scene.cacheflow_active = IntProperty(default=0, update=_active_changed)
    bpy.types.Scene.cacheflow_total_size = FloatProperty(default=0.0)


def unregister():
    del bpy.types.Scene.cacheflow_total_size
    del bpy.types.Scene.cacheflow_active
    del bpy.types.Scene.cacheflow_items
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
