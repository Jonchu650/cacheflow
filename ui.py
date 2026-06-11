# Cacheflow - UI
# SPDX-License-Identifier: GPL-3.0-or-later
from bpy.types import Panel, UIList
from . import core

STATUS_ICON = {
    'BAKED': 'CHECKMARK',
    'BAKING': 'SORTTIME',
    'PARTIAL': 'LAYER_USED',
    'EMPTY': 'RADIOBUT_OFF',
    'UNKNOWN': 'QUESTION',
}


class CACHEFLOW_UL_caches(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text="", icon=core.KIND_ICONS.get(item.kind, 'PHYSICS'))
        split = row.split(factor=0.32)
        split.label(text=item.owner)
        right = split.row(align=True)
        right.label(text=item.label)
        status = right.row(align=True)
        status.alignment = 'RIGHT'
        if item.stale and item.status == 'BAKED':
            status.label(text="", icon='ERROR')
        if item.status in {'BAKED', 'BAKING', 'PARTIAL'}:
            status.label(text="", icon=STATUS_ICON.get(item.status, 'QUESTION'))
        if item.size_bytes >= 0:
            status.label(text=core.human_size(item.size_bytes))
        elif not item.disk:
            status.label(text="RAM")
        # Inline action: bake if there's nothing cached, free otherwise.
        # While a bake runs, show no button at all.
        if item.status != 'BAKING':
            action = status.row(align=True)
            if item.status in {'BAKED', 'PARTIAL'}:
                op = action.operator("cacheflow.free_one", text="", icon='TRASH',
                                     emboss=False)
            else:
                op = action.operator("cacheflow.bake_one", text="", icon='PLAY',
                                     emboss=False)
            op.item_index = index


class CACHEFLOW_PT_main(Panel):
    bl_label = "Cacheflow"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Cache"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        row = layout.row(align=True)
        row.operator("cacheflow.refresh", icon='FILE_REFRESH')
        n = len(scene.cacheflow_items)
        if n:
            row.label(text=f"{n} cache(s)")

        if not n:
            box = layout.box()
            box.label(text="No caches scanned yet.", icon='INFO')
            box.label(text="Click Scan Scene to find cloth, fluid,")
            box.label(text="particles, rigid body & node bakes.")
            return

        layout.template_list("CACHEFLOW_UL_caches", "", scene, "cacheflow_items",
                             scene, "cacheflow_active", rows=min(max(n, 3), 10))

        idx = scene.cacheflow_active
        if 0 <= idx < n:
            item = scene.cacheflow_items[idx]
            box = layout.box()
            col = box.column(align=True)
            col.label(text=f"{item.owner}  >  {item.label}",
                      icon=core.KIND_ICONS.get(item.kind, 'PHYSICS'))
            sub = col.row()
            sub.label(text=f"Frames {item.frame_start}-{item.frame_end}")
            sub.label(text=item.status.title(),
                      icon=STATUS_ICON.get(item.status, 'QUESTION'))
            if item.stale and item.status == 'BAKED':
                col.label(text="Cache ends before scene end frame", icon='ERROR')
            if item.size_bytes >= 0:
                col.label(text=f"Disk: {core.human_size(item.size_bytes)}", icon='DISK_DRIVE')

            row = box.row(align=True)
            op = row.operator("cacheflow.bake_one", icon='PLAY')
            op.item_index = idx
            op = row.operator("cacheflow.free_one", icon='TRASH')
            op.item_index = idx
            if item.kind in core.PTCACHE_KINDS:
                # Convert played-back frames into a bake (no re-sim)
                op = box.operator("cacheflow.bake_from_cache", icon='FILE_TICK')
                op.item_index = idx

            if item.kind == 'RIGIDBODY':
                # The rigid body world is one global sim - list its members
                # so each can be picked out in the viewport individually.
                rbw = context.scene.rigidbody_world
                objs = (list(rbw.collection.objects)
                        if (rbw is not None and rbw.collection is not None) else [])
                sub = box.box()
                sub.label(text=f"Rigid Bodies ({len(objs)})", icon='RIGID_BODY')
                col = sub.column(align=True)
                for ob in objs[:80]:
                    rb = getattr(ob, "rigid_body", None)
                    passive = bool(rb and rb.type == 'PASSIVE')
                    op = col.operator("cacheflow.select_named",
                                      text=ob.name + ("  (passive)" if passive else ""),
                                      icon='OBJECT_DATA', emboss=False)
                    op.object_name = ob.name
                if len(objs) > 80:
                    col.label(text=f"... and {len(objs) - 80} more")
            row = box.row(align=True)
            op = row.operator("cacheflow.select_object", icon='RESTRICT_SELECT_OFF')
            op.item_index = idx
            op = row.operator("cacheflow.open_folder", icon='FILE_FOLDER')
            op.item_index = idx
            if item.disk and item.path:
                op = box.operator("cacheflow.purge_folder", icon='BRUSH_DATA')
                op.item_index = idx

        layout.separator()
        col = layout.column(align=True)
        col.operator("cacheflow.bake_all", icon='RENDER_ANIMATION')
        col.operator("cacheflow.free_all", icon='TRASH')
        if scene.cacheflow_total_size > 0:
            layout.label(text=f"Total on disk: {core.human_size(scene.cacheflow_total_size)}",
                         icon='DISK_DRIVE')


CLASSES = (
    CACHEFLOW_UL_caches,
    CACHEFLOW_PT_main,
)
