# Cacheflow - operators
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import bpy
from bpy.types import Operator
from bpy.props import IntProperty, BoolProperty, EnumProperty, StringProperty
from . import core


def refresh_items(context):
    scene = context.scene
    coll = scene.cacheflow_items
    coll.clear()
    total = 0
    for d in core.iter_caches(scene):
        it = coll.add()
        it.kind = d['kind']
        it.owner = d['owner']
        it.label = d['label']
        it.status = d['status']
        it.path = d['path'] or ""
        it.frame_start = d['frame_start'] or 0
        it.frame_end = d['frame_end'] or 0
        it.object_name = d['object_name']
        it.modifier_name = d['modifier_name']
        it.index = d['index']
        it.stale = d['stale']
        it.disk = d['disk']
        size = core.dir_size(d['path']) if (d['path'] and os.path.isdir(d['path'])) else None
        it.size_bytes = size if size is not None else -1
        if size:
            total += size
    scene.cacheflow_total_size = total
    return len(coll)


def _override_for_item(context, item):
    """Build temp_override kwargs to run cache ops against a specific item.
    ptcache/fluid bake jobs read scene, window and screen from context too,
    so provide the full set - a bare point_cache override is not enough."""
    over = {"scene": context.scene}
    if context.window is not None:
        over["window"] = context.window
        if context.window.screen is not None:
            over["screen"] = context.window.screen
    cache = core.find_point_cache(context.scene, item)
    if cache is not None:
        over["point_cache"] = cache
    ob = context.scene.objects.get(item.object_name) if item.object_name else None
    if ob is not None:
        over["object"] = ob
        over["active_object"] = ob
        over["selected_objects"] = [ob]
    return over, cache, ob


def _apply_frame_range(context, item, fs, fe):
    """Push a frame range onto the cache that backs this item."""
    scene = context.scene
    if fe < fs:
        fs, fe = fe, fs
    try:
        if item.kind in core.PTCACHE_KINDS:
            cache = core.find_point_cache(scene, item)
            if cache is not None:
                cache.frame_start = fs
                cache.frame_end = fe
        elif item.kind == 'FLUID':
            ob = scene.objects.get(item.object_name)
            md = ob.modifiers.get(item.modifier_name) if ob else None
            if md and md.domain_settings:
                md.domain_settings.cache_frame_start = fs
                md.domain_settings.cache_frame_end = fe
        elif item.kind == 'GNBAKE':
            ob = scene.objects.get(item.object_name)
            md = ob.modifiers.get(item.modifier_name) if ob else None
            if md:
                for bake in md.bakes:
                    if bake.bake_id == item.index:
                        bake.use_custom_simulation_frame_range = True
                        bake.frame_start = fs
                        bake.frame_end = fe
                        break
        elif item.kind == 'OCEAN':
            ob = scene.objects.get(item.object_name)
            md = ob.modifiers.get(item.modifier_name) if ob else None
            if md:
                md.frame_start = fs
                md.frame_end = fe
    except Exception:
        pass


# --- original frame range bookkeeping -------------------------------------
# When the user bakes with a custom range, we remember the range the cache
# had before. Freeing the bake restores it. Stored as ID properties on the
# owning object (or the scene for the rigid body world) so it survives
# file save/reload.
_RANGE_KEY = "cacheflow_saved_ranges"


def _range_target(scene, item):
    return scene if item.kind == 'RIGIDBODY' else scene.objects.get(item.object_name)


def _item_key(item):
    return f"{item.kind}|{item.modifier_name}|{item.index}"


def _read_range(context, item):
    """Current native frame range as [start, end, custom_flag], or None."""
    scene = context.scene
    try:
        if item.kind in core.PTCACHE_KINDS:
            c = core.find_point_cache(scene, item)
            if c is not None:
                return [int(c.frame_start), int(c.frame_end), 1]
        elif item.kind == 'FLUID':
            ob = scene.objects.get(item.object_name)
            md = ob.modifiers.get(item.modifier_name) if ob else None
            if md and md.domain_settings:
                d = md.domain_settings
                return [int(d.cache_frame_start), int(d.cache_frame_end), 1]
        elif item.kind == 'GNBAKE':
            ob = scene.objects.get(item.object_name)
            md = ob.modifiers.get(item.modifier_name) if ob else None
            if md:
                for bake in md.bakes:
                    if bake.bake_id == item.index:
                        return [int(bake.frame_start), int(bake.frame_end),
                                int(bake.use_custom_simulation_frame_range)]
        elif item.kind == 'OCEAN':
            ob = scene.objects.get(item.object_name)
            md = ob.modifiers.get(item.modifier_name) if ob else None
            if md:
                return [int(md.frame_start), int(md.frame_end), 1]
    except Exception:
        pass
    return None


def _get_store(tgt):
    raw = tgt.get(_RANGE_KEY)
    if raw is None:
        return {}
    if hasattr(raw, "to_dict"):
        return raw.to_dict()
    return dict(raw)


def _save_original_range(context, item):
    """Remember the pre-bake range (only once - re-bakes keep the oldest)."""
    try:
        tgt = _range_target(context.scene, item)
        if tgt is None:
            return
        cur = _read_range(context, item)
        if cur is None:
            return
        store = _get_store(tgt)
        key = _item_key(item)
        if key not in store:
            store[key] = cur
            tgt[_RANGE_KEY] = store
    except Exception:
        pass


def _restore_original_range(context, item):
    """Put back the range saved by _save_original_range. True if restored."""
    try:
        tgt = _range_target(context.scene, item)
        if tgt is None:
            return False
        store = _get_store(tgt)
        key = _item_key(item)
        if key not in store:
            return False
        fs, fe, flag = (int(v) for v in store[key])
        _apply_frame_range(context, item, fs, fe)
        if item.kind == 'GNBAKE' and not flag:
            # custom sim range was originally OFF - switch it back off
            ob = context.scene.objects.get(item.object_name)
            md = ob.modifiers.get(item.modifier_name) if ob else None
            if md:
                for bake in md.bakes:
                    if bake.bake_id == item.index:
                        bake.use_custom_simulation_frame_range = False
                        break
        del store[key]
        tgt[_RANGE_KEY] = store
        return True
    except Exception:
        return False


def _invalidate_ptcache(context, cache, ob):
    """Actually drop a point cache's RAM frames. free_bake only clears the
    bake flag; assigning any PointCache property fires Blender's RNA update
    callback, which resets the cache and frees its memory frames.
    (A frame jump does NOT work - it re-simulates and re-caches frames.)"""
    try:
        cache.frame_start = cache.frame_start
    except Exception:
        pass
    if ob is not None:
        try:
            ob.update_tag(refresh={'DATA'})
        except Exception:
            pass
    # Rewind to the start frame. Off frame 1, rigid bodies (and some other
    # sims) catch up by re-simulating 1..playhead on the next evaluation,
    # which would instantly re-cache everything we just freed.
    try:
        if context.scene.frame_current != context.scene.frame_start:
            context.scene.frame_set(context.scene.frame_start)
    except Exception:
        pass
    try:
        context.view_layer.update()
    except Exception:
        pass


def select_item_objects(context, item):
    """Select this item's owner in the viewport. For the rigid body world
    (a scene-level sim) that means every object in the rigid body collection."""
    scene = context.scene
    targets = []
    if item.kind == 'RIGIDBODY':
        rbw = scene.rigidbody_world
        if rbw is not None and rbw.collection is not None:
            targets = list(rbw.collection.objects)
    else:
        ob = scene.objects.get(item.object_name)
        if ob is not None:
            targets = [ob]
    if not targets:
        return 0
    try:
        for o in context.selected_objects:
            o.select_set(False)
    except Exception:
        pass
    n = 0
    for o in targets:
        try:
            o.select_set(True)
            n += 1
        except RuntimeError:
            pass
    try:
        context.view_layer.objects.active = targets[0]
    except Exception:
        pass
    return n


def _freed_msg(label, nfiles, nbytes, restored=False):
    msg = f"{label}: freed"
    if nfiles:
        msg += f" ({nfiles} file(s), {core.human_size(nbytes)} deleted)"
    if restored:
        msg += "; frame range restored"
    return msg


def _bake_item(context, item, free=False, delete_files=True, from_cache=False):
    """Bake or free one cache item. Returns (ok, message).
    Freeing is VERIFIED (cache state re-checked), RAM frames are dropped via
    a cache reset, and disk files are actually removed when requested."""
    kind = item.kind
    scene = context.scene
    try:
        if kind in core.PTCACHE_KINDS:
            cache = core.find_point_cache(scene, item)
            if cache is None:
                return False, f"{item.label}: cache not found (rescan?)"
            ob = scene.objects.get(item.object_name) if item.object_name else None
            # Minimal override, verified working on Blender 5.x:
            #   with context.temp_override(point_cache=cache):
            #       bpy.ops.ptcache.free_bake()
            # ptcache operators locate the cache owner themselves; extra
            # context members are unnecessary.
            with context.temp_override(point_cache=cache):
                if free:
                    if bpy.ops.ptcache.free_bake.poll():
                        bpy.ops.ptcache.free_bake()
                    else:
                        return False, f"{item.label}: free_bake refused this context"
                elif from_cache:
                    # Convert the frames simulated so far (playback) into a
                    # bake, without re-simulating anything.
                    bpy.ops.ptcache.bake_from_cache()
                else:
                    if cache.is_baked:  # re-bake: release the old bake first
                        bpy.ops.ptcache.free_bake()
                    bpy.ops.ptcache.bake(bake=True)
            if from_cache:
                if cache.is_baked:
                    return True, f"{item.label}: current cache converted to bake"
                return False, (f"{item.label}: nothing to convert - play the "
                               "simulation first, then bake from cache")
            if not free:
                return True, f"{item.label}: baked"
            # -- verify the free actually happened --
            if cache.is_baked:
                return False, f"{item.label}: Blender did not release this bake"
            _invalidate_ptcache(context, cache, ob)
            nfiles = nbytes = 0
            if delete_files and item.disk:
                nfiles, nbytes = core.delete_ptcache_files(scene, item, cache, ob)
            restored = _restore_original_range(context, item)
            return True, _freed_msg(item.label, nfiles, nbytes, restored)
        if kind == 'FLUID':
            over, _c, ob = _override_for_item(context, item)
            if ob is None:
                return False, f"{item.label}: object not found"
            md = ob.modifiers.get(item.modifier_name)
            dom = md.domain_settings if md else None
            with context.temp_override(**over):
                if free:
                    bpy.ops.fluid.free_all()
                else:
                    if dom is not None and dom.has_cache_baked_any:
                        bpy.ops.fluid.free_all()  # re-bake cleanly
                    bpy.ops.fluid.bake_all()
            if free:
                nfiles = nbytes = 0
                if delete_files and item.path:
                    nfiles, nbytes = core.delete_dir_contents(item.path)
                restored = _restore_original_range(context, item)
                return True, _freed_msg(item.label, nfiles, nbytes, restored)
            return True, f"{item.label}: baked"
        if kind == 'GNBAKE':
            ob = context.scene.objects.get(item.object_name)
            if ob is None:
                return False, f"{item.label}: object not found"
            kwargs = dict(session_uid=ob.session_uid,
                          modifier_name=item.modifier_name,
                          bake_id=item.index)
            over, _c, _o = _override_for_item(context, item)
            with context.temp_override(**over):
                if free:
                    try:
                        bpy.ops.object.geometry_node_bake_delete_single(**kwargs)
                    except (AttributeError, RuntimeError):
                        # older 4.x builds: fall back to clearing all sim
                        # caches on this object
                        bpy.ops.object.simulation_nodes_cache_delete(selected=True)
                else:
                    bpy.ops.object.geometry_node_bake_single(**kwargs)
            if free:
                nfiles = nbytes = 0
                if delete_files and item.path:
                    nfiles, nbytes = core.delete_dir_contents(item.path)
                restored = _restore_original_range(context, item)
                return True, _freed_msg(item.label, nfiles, nbytes, restored)
            return True, f"{item.label}: baked"
        if kind == 'OCEAN':
            ob = context.scene.objects.get(item.object_name)
            if ob is None:
                return False, f"{item.label}: object not found"
            over, _c, _o = _override_for_item(context, item)
            with context.temp_override(**over):
                bpy.ops.object.ocean_bake(modifier=item.modifier_name, free=free)
            if free:
                nfiles = nbytes = 0
                if delete_files and item.path:
                    nfiles, nbytes = core.delete_dir_contents(item.path)
                restored = _restore_original_range(context, item)
                return True, _freed_msg(item.label, nfiles, nbytes, restored)
            return True, f"{item.label}: baked"
        return False, f"{item.label}: unsupported kind {kind}"
    except RuntimeError as e:
        return False, f"{item.label}: {str(e).strip()}"


class CACHEFLOW_OT_refresh(Operator):
    bl_idname = "cacheflow.refresh"
    bl_label = "Scan Scene"
    bl_description = "Find every physics cache in this scene"

    def execute(self, context):
        n = refresh_items(context)
        self.report({'INFO'}, f"Cacheflow: found {n} cache(s)")
        return {'FINISHED'}


class CACHEFLOW_OT_bake_one(Operator):
    bl_idname = "cacheflow.bake_one"
    bl_label = "Bake Cache"
    bl_description = "Bake this cache now (asks for frame range first)"
    item_index: IntProperty()
    set_range: BoolProperty(name="Set frame range", default=True,
                            description="Apply the range below to this cache before baking")
    frame_start: IntProperty(name="Start", default=1, min=0)
    frame_end: IntProperty(name="End", default=250, min=0)

    def invoke(self, context, event):
        items = context.scene.cacheflow_items
        if 0 <= self.item_index < len(items):
            item = items[self.item_index]
            self.frame_start = item.frame_start or context.scene.frame_start
            self.frame_end = item.frame_end or context.scene.frame_end
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "set_range")
        row = col.row(align=True)
        row.enabled = self.set_range
        row.prop(self, "frame_start")
        row.prop(self, "frame_end")

    def execute(self, context):
        items = context.scene.cacheflow_items
        if not (0 <= self.item_index < len(items)):
            return {'CANCELLED'}
        item = items[self.item_index]
        if self.set_range:
            _save_original_range(context, item)
            _apply_frame_range(context, item, self.frame_start, self.frame_end)
        ok, msg = _bake_item(context, item)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        refresh_items(context)
        return {'FINISHED'} if ok else {'CANCELLED'}


class CACHEFLOW_OT_bake_from_cache(Operator):
    bl_idname = "cacheflow.bake_from_cache"
    bl_label = "Bake From Cache"
    bl_description = ("Keep the simulation exactly as played so far: convert "
                      "the current cached frames into a bake without re-simulating")
    item_index: IntProperty()

    def execute(self, context):
        items = context.scene.cacheflow_items
        if not (0 <= self.item_index < len(items)):
            return {'CANCELLED'}
        item = items[self.item_index]
        if item.kind not in core.PTCACHE_KINDS:
            self.report({'WARNING'},
                        "Bake From Cache only works for point caches "
                        "(cloth, soft body, particles, rigid body, dynamic paint)")
            return {'CANCELLED'}
        ok, msg = _bake_item(context, item, from_cache=True)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        refresh_items(context)
        return {'FINISHED'} if ok else {'CANCELLED'}


class CACHEFLOW_OT_free_one(Operator):
    bl_idname = "cacheflow.free_one"
    bl_label = "Free"
    bl_description = "Delete this cache's baked data (and its files on disk)"
    item_index: IntProperty()
    delete_files: BoolProperty(
        name="Also delete cache files on disk", default=True,
        description="Remove the cache's files from disk, not just Blender's bake flag")

    def execute(self, context):
        items = context.scene.cacheflow_items
        if not (0 <= self.item_index < len(items)):
            return {'CANCELLED'}
        ok, msg = _bake_item(context, items[self.item_index], free=True,
                             delete_files=self.delete_files)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        refresh_items(context)
        return {'FINISHED'} if ok else {'CANCELLED'}


class CACHEFLOW_OT_purge_folder(Operator):
    """Escape hatch for stubborn caches: wipe the item's cache folder contents."""
    bl_idname = "cacheflow.purge_folder"
    bl_label = "Purge Cache Folder"
    bl_description = ("Delete ALL files inside this cache's folder on disk. "
                      "Use when Free leaves orphaned files behind")
    item_index: IntProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        items = context.scene.cacheflow_items
        if not (0 <= self.item_index < len(items)):
            return {'CANCELLED'}
        item = items[self.item_index]
        if not item.path:
            self.report({'WARNING'}, "This cache has no folder on disk")
            return {'CANCELLED'}
        n, b = core.delete_dir_contents(item.path)
        refresh_items(context)
        self.report({'INFO'}, f"Purged {n} file(s), {core.human_size(b)}")
        return {'FINISHED'}


class CACHEFLOW_OT_bake_all(Operator):
    """Queue-bake every cache in the scene, one at a time, with progress."""
    bl_idname = "cacheflow.bake_all"
    bl_label = "Bake All (Queue)"
    bl_description = ("Bake every cache in the list sequentially "
                      "(choose: simulate a frame range, or keep current caches)")
    mode: EnumProperty(name="Mode", items=[
        ('SIMULATE', "Simulate frame range",
         "Re-simulate and bake every cache over the chosen frame range"),
        ('FROMCACHE', "Bake current caches as-is",
         "Convert frames already simulated during playback into bakes "
         "without re-simulating (point caches only)"),
    ], default='SIMULATE')
    set_range: BoolProperty(name="Set frame range on all caches", default=True)
    frame_start: IntProperty(name="Start", default=1, min=0)
    frame_end: IntProperty(name="End", default=250, min=0)

    _timer = None
    _queue = None
    _done = 0
    _failed = None

    def invoke(self, context, event):
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Bake all caches:")
        col.prop(self, "mode", expand=True)
        if self.mode == 'SIMULATE':
            col.separator()
            col.prop(self, "set_range")
            row = col.row(align=True)
            row.enabled = self.set_range
            row.prop(self, "frame_start")
            row.prop(self, "frame_end")

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        wm = context.window_manager
        if not self._queue:
            return self.finish(context)
        idx = self._queue.pop(0)
        items = context.scene.cacheflow_items
        if 0 <= idx < len(items):
            item = items[idx]
            context.workspace.status_text_set(
                f"Cacheflow: baking {item.owner} / {item.label} "
                f"({self._done + 1}/{self._total})...")
            if self.mode == 'FROMCACHE':
                ok, msg = _bake_item(context, item, from_cache=True)
            else:
                if self.set_range:
                    _save_original_range(context, item)
                    _apply_frame_range(context, item, self.frame_start, self.frame_end)
                ok, msg = _bake_item(context, item)
            if not ok:
                self._failed.append(msg)
            self._done += 1
            wm.progress_update(self._done)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        refresh_items(context)
        items = context.scene.cacheflow_items
        # Bake EVERYTHING in the list (already-baked caches are re-baked).
        # From-cache mode only applies to point caches.
        self._queue = [i for i, it in enumerate(items)
                       if it.status != 'BAKING'
                       and (self.mode != 'FROMCACHE' or it.kind in core.PTCACHE_KINDS)]
        if not self._queue:
            self.report({'INFO'}, "Nothing to bake for this mode")
            return {'CANCELLED'}
        self._total = len(self._queue)
        self._done = 0
        self._failed = []
        wm = context.window_manager
        wm.progress_begin(0, self._total)
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def finish(self, context):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
        wm.progress_end()
        context.workspace.status_text_set(None)
        refresh_items(context)
        if self._failed:
            self.report({'WARNING'},
                        f"Baked {self._done - len(self._failed)}/{self._total}; "
                        f"failed: {'; '.join(self._failed[:3])}")
        else:
            self.report({'INFO'}, f"Cacheflow: baked {self._done} cache(s)")
        return {'FINISHED'}


class CACHEFLOW_OT_free_all(Operator):
    bl_idname = "cacheflow.free_all"
    bl_label = "Free All"
    bl_description = "Delete all baked physics data in the scene"
    delete_files: BoolProperty(
        name="Also delete cache files on disk", default=True)

    def execute(self, context):
        refresh_items(context)
        items = context.scene.cacheflow_items
        failed = []
        n = 0
        # Free EVERYTHING, regardless of displayed status: RAM playback
        # frames don't always register as baked, and freeing an already
        # empty cache is a harmless no-op.
        for it in items:
            if it.status == 'BAKING':
                continue
            ok, msg = _bake_item(context, it, free=True,
                                 delete_files=self.delete_files)
            if ok:
                n += 1
            else:
                failed.append(msg)
        refresh_items(context)
        if failed:
            self.report({'WARNING'}, "Some caches could not be freed: " + "; ".join(failed[:3]))
        else:
            self.report({'INFO'}, f"Freed {n} cache(s)")
        return {'FINISHED'}


class CACHEFLOW_OT_select_object(Operator):
    bl_idname = "cacheflow.select_object"
    bl_label = "Select Owner"
    bl_description = "Select and frame the object that owns this cache"
    item_index: IntProperty()

    def execute(self, context):
        items = context.scene.cacheflow_items
        if not (0 <= self.item_index < len(items)):
            return {'CANCELLED'}
        item = items[self.item_index]
        n = select_item_objects(context, item)
        if n == 0:
            self.report({'WARNING'}, "Nothing to select for this cache")
            return {'CANCELLED'}
        if item.kind == 'RIGIDBODY':
            self.report({'INFO'}, f"Selected {n} rigid body object(s)")
        return {'FINISHED'}


class CACHEFLOW_OT_select_named(Operator):
    bl_idname = "cacheflow.select_named"
    bl_label = "Select Object"
    bl_description = "Select this object in the viewport"
    object_name: StringProperty()

    def execute(self, context):
        ob = context.scene.objects.get(self.object_name)
        if ob is None:
            self.report({'WARNING'}, f"Object '{self.object_name}' not found")
            return {'CANCELLED'}
        try:
            for o in context.selected_objects:
                o.select_set(False)
        except Exception:
            pass
        ob.select_set(True)
        try:
            context.view_layer.objects.active = ob
        except Exception:
            pass
        return {'FINISHED'}


class CACHEFLOW_OT_open_folder(Operator):
    bl_idname = "cacheflow.open_folder"
    bl_label = "Open Cache Folder"
    bl_description = "Open this cache's folder in your file browser"
    item_index: IntProperty()

    def execute(self, context):
        items = context.scene.cacheflow_items
        if not (0 <= self.item_index < len(items)):
            return {'CANCELLED'}
        path = items[self.item_index].path
        if not path or not os.path.isdir(path):
            self.report({'WARNING'}, "No cache folder on disk for this item")
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


CLASSES = (
    CACHEFLOW_OT_refresh,
    CACHEFLOW_OT_bake_one,
    CACHEFLOW_OT_bake_from_cache,
    CACHEFLOW_OT_free_one,
    CACHEFLOW_OT_purge_folder,
    CACHEFLOW_OT_bake_all,
    CACHEFLOW_OT_free_all,
    CACHEFLOW_OT_select_object,
    CACHEFLOW_OT_select_named,
    CACHEFLOW_OT_open_folder,
)
