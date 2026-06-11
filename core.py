# Cacheflow - cache discovery & utilities
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import bpy

# Cache kinds
KIND_ICONS = {
    'CLOTH': 'MOD_CLOTH',
    'SOFTBODY': 'MOD_SOFT',
    'PARTICLES': 'PARTICLES',
    'DYNPAINT': 'MOD_DYNAMICPAINT',
    'RIGIDBODY': 'RIGID_BODY',
    'FLUID': 'MOD_FLUIDSIM',
    'GNBAKE': 'GEOMETRY_NODES',
    'OCEAN': 'MOD_OCEAN',
}

PTCACHE_KINDS = {'CLOTH', 'SOFTBODY', 'PARTICLES', 'DYNPAINT', 'RIGIDBODY'}


def human_size(num):
    if num is None:
        return "-"
    if num == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024.0:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} PB"


def dir_size(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        return None
    return total


def blendcache_dir():
    """Default disk-cache directory used by point caches: //blendcache_<blendname>"""
    if not bpy.data.filepath:
        return None
    blend = os.path.basename(bpy.data.filepath)
    name = os.path.splitext(blend)[0]
    return os.path.join(os.path.dirname(bpy.data.filepath), "blendcache_" + name)


def ptcache_disk_path(cache):
    """Best-effort disk location for a PointCache."""
    if not cache.use_disk_cache:
        return None
    if cache.filepath:
        return bpy.path.abspath(cache.filepath)
    return blendcache_dir()


def ptcache_status(cache):
    if getattr(cache, "is_baking", False):
        return 'BAKING'
    if cache.is_baked:
        return 'BAKED'
    # Playback can leave frames in the cache without a real bake. The info
    # string is the only runtime indicator; parse numbers instead of words
    # so this also works on translated UIs ("120 frames in memory", etc.).
    # Threshold of 2: Blender always re-caches a frame or two at the current
    # playhead right after a free - that residue is not "cached data".
    import re
    info = (getattr(cache, "info", "") or "")
    nums = [int(n) for n in re.findall(r"\d+", info)]
    if nums and max(nums) > 2:
        return 'PARTIAL'
    return 'EMPTY'


def gn_bake_status(bake, mod):
    target = bake.bake_target
    if target == 'INHERIT':
        target = getattr(mod, "bake_target", 'DISK')
    if target == 'PACKED':
        try:
            return 'BAKED' if len(bake.data_blocks) > 0 else 'EMPTY'
        except Exception:
            return 'UNKNOWN'
    d = gn_bake_dir(bake, mod)
    if d and os.path.isdir(d) and any(os.scandir(d)):
        return 'BAKED'
    return 'EMPTY'


def gn_bake_dir(bake, mod):
    if bake.use_custom_path and bake.directory:
        return bpy.path.abspath(bake.directory)
    base = getattr(mod, "bake_directory", "")
    if base:
        return os.path.join(bpy.path.abspath(base), str(bake.bake_id))
    return None


def fluid_status(dom):
    try:
        if getattr(dom, "is_cache_baking_any", False):
            return 'BAKING'
        if dom.has_cache_baked_any:
            return 'BAKED'
        if getattr(dom, "has_cache_baked_data", False):
            return 'PARTIAL'
    except Exception:
        return 'UNKNOWN'
    return 'EMPTY'


def stale_hint(frame_end, scene):
    """Cache range ends before scene end -> likely needs re-bake for full range."""
    try:
        if frame_end and frame_end < scene.frame_end:
            return True
    except Exception:
        pass
    return False


def iter_caches(scene):
    """Yield dicts describing every cache in the scene."""
    # Rigid body world (scene-level)
    rbw = scene.rigidbody_world
    if rbw is not None and rbw.point_cache is not None:
        c = rbw.point_cache
        yield dict(kind='RIGIDBODY', owner="Scene", label="Rigid Body World",
                   status=ptcache_status(c), path=ptcache_disk_path(c),
                   frame_start=c.frame_start, frame_end=c.frame_end,
                   object_name="", modifier_name="", index=-1,
                   stale=stale_hint(c.frame_end, scene),
                   disk=c.use_disk_cache)

    for ob in scene.objects:
        # Particle systems
        for i, psys in enumerate(ob.particle_systems):
            # Static hair (no dynamics) never simulates - its point cache is
            # meaningless noise in a cache list, so skip it.
            st = getattr(psys, "settings", None)
            if (st is not None and getattr(st, "type", "") == 'HAIR'
                    and not getattr(psys, "use_hair_dynamics", False)):
                continue
            c = psys.point_cache
            yield dict(kind='PARTICLES', owner=ob.name, label=psys.name,
                       status=ptcache_status(c), path=ptcache_disk_path(c),
                       frame_start=c.frame_start, frame_end=c.frame_end,
                       object_name=ob.name, modifier_name="", index=i,
                       stale=stale_hint(c.frame_end, scene),
                       disk=c.use_disk_cache)
        for md in ob.modifiers:
            if md.type == 'CLOTH':
                c = md.point_cache
                yield dict(kind='CLOTH', owner=ob.name, label=md.name,
                           status=ptcache_status(c), path=ptcache_disk_path(c),
                           frame_start=c.frame_start, frame_end=c.frame_end,
                           object_name=ob.name, modifier_name=md.name, index=-1,
                           stale=stale_hint(c.frame_end, scene),
                           disk=c.use_disk_cache)
            elif md.type == 'SOFT_BODY':
                c = md.point_cache
                yield dict(kind='SOFTBODY', owner=ob.name, label=md.name,
                           status=ptcache_status(c), path=ptcache_disk_path(c),
                           frame_start=c.frame_start, frame_end=c.frame_end,
                           object_name=ob.name, modifier_name=md.name, index=-1,
                           stale=stale_hint(c.frame_end, scene),
                           disk=c.use_disk_cache)
            elif md.type == 'DYNAMIC_PAINT':
                cs = md.canvas_settings
                if cs:
                    for i, surf in enumerate(cs.canvas_surfaces):
                        c = surf.point_cache
                        if c is None:
                            continue
                        yield dict(kind='DYNPAINT', owner=ob.name,
                                   label=f"{md.name} / {surf.name}",
                                   status=ptcache_status(c), path=ptcache_disk_path(c),
                                   frame_start=c.frame_start, frame_end=c.frame_end,
                                   object_name=ob.name, modifier_name=md.name, index=i,
                                   stale=stale_hint(c.frame_end, scene),
                                   disk=c.use_disk_cache)
            elif md.type == 'FLUID' and getattr(md, "fluid_type", "") == 'DOMAIN':
                dom = md.domain_settings
                if dom:
                    path = bpy.path.abspath(dom.cache_directory) if dom.cache_directory else None
                    yield dict(kind='FLUID', owner=ob.name, label=md.name,
                               status=fluid_status(dom), path=path,
                               frame_start=dom.cache_frame_start, frame_end=dom.cache_frame_end,
                               object_name=ob.name, modifier_name=md.name, index=-1,
                               stale=stale_hint(dom.cache_frame_end, scene),
                               disk=True)
            elif md.type == 'OCEAN':
                if getattr(md, "is_cached", False) or getattr(md, "filepath", ""):
                    path = bpy.path.abspath(md.filepath) if md.filepath else None
                    yield dict(kind='OCEAN', owner=ob.name, label=md.name,
                               status='BAKED' if md.is_cached else 'EMPTY', path=path,
                               frame_start=md.frame_start, frame_end=md.frame_end,
                               object_name=ob.name, modifier_name=md.name, index=-1,
                               stale=False, disk=True)
            elif md.type == 'NODES':
                try:
                    bakes = md.bakes
                except AttributeError:
                    bakes = []
                for bake in bakes:
                    node = bake.node
                    nlabel = node.label or node.name if node else f"Bake {bake.bake_id}"
                    yield dict(kind='GNBAKE', owner=ob.name,
                               label=f"{md.name} / {nlabel}",
                               status=gn_bake_status(bake, md),
                               path=gn_bake_dir(bake, md),
                               frame_start=bake.frame_start, frame_end=bake.frame_end,
                               object_name=ob.name, modifier_name=md.name,
                               index=bake.bake_id,
                               stale=False,
                               disk=(bake.bake_target != 'PACKED'))


def ptcache_file_prefix(cache, ob):
    """Disk filename prefix Blender uses for a point cache:
    the cache name if set, else the owner object's name hex-encoded."""
    if cache is not None and cache.name:
        return cache.name
    if ob is not None:
        return ob.name.encode("utf-8").hex().upper()
    return None


def ptcache_stack_index(scene, item):
    """Blender's PTCacheID stack_index, which is the trailing _NN in .bphys
    filenames. Cloth/softbody: modifier stack position. Particles: psys index.
    Rigid body world: 0. Returns None when unknown."""
    if item.kind == 'RIGIDBODY':
        return 0
    ob = scene.objects.get(item.object_name)
    if ob is None:
        return None
    if item.kind == 'PARTICLES':
        return item.index if item.index >= 0 else None
    if item.kind in {'CLOTH', 'SOFTBODY'}:
        return ob.modifiers.find(item.modifier_name)
    return None


def delete_ptcache_files(scene, item, cache, ob):
    """Delete this cache's .bphys files from disk. Returns (count, bytes).
    Only deletes files whose prefix AND stack index match, so sibling caches
    in the shared blendcache folder are never touched."""
    path = item.path
    if not path or not os.path.isdir(path):
        return 0, 0
    prefix = ptcache_file_prefix(cache, ob)
    if not prefix:
        return 0, 0
    idx = ptcache_stack_index(scene, item)
    count = freed = 0
    for entry in list(os.scandir(path)):
        name = entry.name
        if not name.startswith(prefix + "_") or not name.endswith(".bphys"):
            continue
        # filename: <prefix>_<frame>_<index>.bphys
        parts = name[:-len(".bphys")].rsplit("_", 2)
        if len(parts) == 3 and idx is not None:
            try:
                if int(parts[2]) != idx:
                    continue
            except ValueError:
                continue
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            count += 1
            freed += size
        except OSError:
            pass
    return count, freed


def delete_dir_contents(path):
    """Delete every file under path (keeps the directory). Returns (count, bytes)."""
    if not path or not os.path.isdir(path):
        return 0, 0
    count = freed = 0
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            try:
                freed += os.path.getsize(p)
                os.remove(p)
                count += 1
            except OSError:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass
    return count, freed


def find_point_cache(scene, item):
    """Re-resolve the PointCache for a scanned item (pointers can't be stored)."""
    kind = item.kind
    if kind == 'RIGIDBODY':
        return scene.rigidbody_world.point_cache if scene.rigidbody_world else None
    ob = scene.objects.get(item.object_name)
    if ob is None:
        return None
    if kind == 'PARTICLES':
        try:
            return ob.particle_systems[item.index].point_cache
        except (IndexError, KeyError):
            return None
    md = ob.modifiers.get(item.modifier_name)
    if md is None:
        return None
    if kind in {'CLOTH', 'SOFTBODY'}:
        return md.point_cache
    if kind == 'DYNPAINT':
        try:
            return md.canvas_settings.canvas_surfaces[item.index].point_cache
        except (AttributeError, IndexError):
            return None
    return None
