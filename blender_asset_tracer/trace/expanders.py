# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2014, Blender Foundation - Campbell Barton
# (c) 2018, Blender Foundation - Sybren A. Stüvel
"""Low-level functions called by file2block.

Those can expand data blocks and yield their dependencies (e.g. other data
blocks necessary to render/display/work with the given data block).
"""
import logging
import typing

from .. import blendfile, cdefs
from ..blendfile import iterators
from ..blendfile.exceptions import SegmentationFault

# Don't warn about these types at all.
_warned_about_types = {b"LI", b"DATA"}
_funcs_for_code = {}  # type: typing.Dict[bytes, typing.Callable]
log = logging.getLogger(__name__)


def expand_block(
    block: blendfile.BlendFileBlock,
) -> typing.Iterator[blendfile.BlendFileBlock]:
    """Generator, yield the data blocks used by this data block."""

    try:
        expander = _funcs_for_code[block.code]
    except KeyError:
        if block.code not in _warned_about_types:
            log.debug("No expander implemented for block type %r", block.code.decode())
            _warned_about_types.add(block.code)
        return

    log.debug("Expanding block %r", block)
    for dependency in expander(block):
        if not dependency:
            # Filter out falsy blocks, i.e. None values.
            # Allowing expanders to yield None makes them more consise.
            continue
        if dependency.code == b"DATA":
            log.warn(
                "expander yielded block %s which will be ignored in later iteration",
                dependency,
            )
        yield dependency


def dna_code(block_code: str):
    """Decorator, marks decorated func as expander for that DNA code."""

    assert isinstance(block_code, str)

    def decorator(wrapped):
        _funcs_for_code[block_code.encode()] = wrapped
        return wrapped

    return decorator


def _expand_generic_material(block: blendfile.BlendFileBlock):
    try:
        array_len = block.get(b"totcol")
    except (KeyError, SegmentationFault):
        return

    try:
        for mat in block.iter_array_of_pointers(b"mat", array_len):
            if mat:
                # Handle ID-view blocks from library overrides
                if getattr(mat, "dna_type_name", None) == "ID":
                    # For arrays we can't easily re-dereference, just yield the ID block
                    pass
                yield mat
    except (KeyError, SegmentationFault):
        pass


def _expand_generic_mtex(block: blendfile.BlendFileBlock):
    if not block.dna_type.has_field(b"mtex"):
        # mtex was removed in Blender 2.8
        return

    try:
        for mtex in block.iter_fixed_array_of_pointers(b"mtex"):
            try:
                tex = mtex.get_pointer(b"tex")
                if tex:
                    yield tex
            except (KeyError, SegmentationFault):
                pass
            try:
                obj = mtex.get_pointer(b"object")
                if obj:
                    yield obj
            except (KeyError, SegmentationFault):
                pass
    except (KeyError, SegmentationFault):
        pass


def _expand_generic_nodetree(block: blendfile.BlendFileBlock):
    if block.dna_type.dna_type_id == b"ID":
        # This is a placeholder for a linked node tree.
        yield block
        return

    assert (
        block.dna_type.dna_type_id == b"bNodeTree"
    ), f"Expected bNodeTree, got {block.dna_type.dna_type_id.decode()})"

    try:
        nodes = block.get_pointer((b"nodes", b"first"))
    except (KeyError, SegmentationFault):
        log.debug("Could not get nodes from node tree %s", block)
        return

    # See DNA_node_types.h
    socket_types_with_value_pointer = {
        cdefs.SOCK_OBJECT,  #  bNodeSocketValueObject
        cdefs.SOCK_IMAGE,  #  bNodeSocketValueImage
        cdefs.SOCK_COLLECTION,  #  bNodeSocketValueCollection
        cdefs.SOCK_TEXTURE,  #  bNodeSocketValueTexture
        cdefs.SOCK_MATERIAL,  #  bNodeSocketValueMaterial
    }

    for node in iterators.listbase(nodes):
        try:
            node_type = node[b"type"]
        except (KeyError, SegmentationFault):
            continue

        if node_type == cdefs.CMP_NODE_R_LAYERS:
            continue

        # The 'id' property points to whatever is used by the node
        # (like the image in an image texture node).
        try:
            id_block = node.get_pointer(b"id")
        except (KeyError, SegmentationFault):
            id_block = None

        if id_block:
            # Handle library overrides: the pointer may resolve to a generic ID-view
            # instead of the concrete datablock type. Try re-dereferencing to get
            # the actual block (same pattern as modifier_walkers._get_image).
            if getattr(id_block, "dna_type_name", None) == "ID":
                try:
                    id_ptr = node.get(b"id")
                    if id_ptr:
                        id_block2 = node.bfile.dereference_pointer(id_ptr)
                        if id_block2:
                            id_block = id_block2
                except (KeyError, SegmentationFault):
                    pass
            yield id_block

        # Default values of inputs can also point to ID datablocks.
        try:
            inputs = node.get_pointer((b"inputs", b"first"))
        except (KeyError, SegmentationFault):
            inputs = None

        if not inputs:
            continue

        for input in iterators.listbase(inputs):
            try:
                input_type = input[b"type"]
            except (KeyError, SegmentationFault):
                continue

            if input_type not in socket_types_with_value_pointer:
                continue

            try:
                value_container = input.get_pointer(b"default_value")
            except (KeyError, SegmentationFault):
                continue

            if not value_container:
                continue

            try:
                value = value_container.get_pointer(b"value")
            except (KeyError, SegmentationFault):
                continue

            if value:
                # Same ID re-dereference pattern for socket default values
                if getattr(value, "dna_type_name", None) == "ID":
                    try:
                        value_ptr = value_container.get(b"value")
                        if value_ptr:
                            value2 = value_container.bfile.dereference_pointer(value_ptr)
                            if value2:
                                value = value2
                    except (KeyError, SegmentationFault):
                        pass
                yield value


def _expand_generic_idprops(block: blendfile.BlendFileBlock):
    """Yield ID datablocks and their libraries referenced from ID properties."""

    # TODO(@sybren): this code is very crude, and happens to work on ID
    # properties of Geometry Nodes modifiers, which is what it was written for.
    # It should probably be rewritten to properly iterate over & recurse into
    # all groups.
    try:
        settings_props = block.get_pointer((b"settings", b"properties"))
    except (KeyError, SegmentationFault):
        return
    if not settings_props:
        return

    try:
        subprops = settings_props.get_pointer((b"data", b"group", b"first"))
    except (KeyError, SegmentationFault):
        return

    for idprop in iterators.listbase(subprops):
        try:
            prop_type = idprop[b"type"]
        except (KeyError, SegmentationFault):
            continue

        if prop_type != cdefs.IDP_ID:
            continue

        try:
            id_datablock = idprop.get_pointer((b"data", b"pointer"))
        except (KeyError, SegmentationFault):
            continue

        if not id_datablock:
            continue

        # Handle ID-view blocks from library overrides
        if getattr(id_datablock, "dna_type_name", None) == "ID":
            try:
                id_ptr = idprop.get((b"data", b"pointer"))
                if id_ptr:
                    id_datablock2 = idprop.bfile.dereference_pointer(id_ptr)
                    if id_datablock2:
                        id_datablock = id_datablock2
            except (KeyError, SegmentationFault):
                pass

        yield id_datablock


def _expand_generic_nodetree_id(block: blendfile.BlendFileBlock):
    try:
        if block.bfile.header.version >= 500 and block.bfile.file_subversion >= 4:
            # Introduced in Blender 5.0, commit bd61e69be5a7c96f1e5da1c86aafc17b839e049f
            block_ntree = block.get_pointer(b"compositing_node_group", None)
        else:
            block_ntree = block.get_pointer(b"nodetree", None)
    except (KeyError, SegmentationFault):
        block_ntree = None

    if block_ntree is not None:
        # Handle ID-view blocks from library overrides
        if getattr(block_ntree, "dna_type_name", None) == "ID":
            try:
                field_name = b"compositing_node_group" if (
                    block.bfile.header.version >= 500 and block.bfile.file_subversion >= 4
                ) else b"nodetree"
                ntree_ptr = block.get(field_name)
                if ntree_ptr:
                    block_ntree2 = block.bfile.dereference_pointer(ntree_ptr)
                    if block_ntree2:
                        block_ntree = block_ntree2
            except (KeyError, SegmentationFault):
                pass
        try:
            yield from _expand_generic_nodetree(block_ntree)
        except (KeyError, SegmentationFault):
            # If expansion fails, at least yield the node tree block itself
            yield block_ntree


def _expand_generic_animdata(block: blendfile.BlendFileBlock):
    try:
        block_adt = block.get_pointer(b"adt")
    except (KeyError, SegmentationFault):
        block_adt = None

    if block_adt:
        try:
            action = block_adt.get_pointer(b"action")
            if action:
                yield action
        except (KeyError, SegmentationFault):
            pass
    # TODO, NLA


@dna_code("AR")
def _expand_armature(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)


@dna_code("CU")
def _expand_curve(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_material(block)

    for fieldname in (
        b"vfont",
        b"vfontb",
        b"vfonti",
        b"vfontbi",
        b"bevobj",
        b"taperobj",
        b"textoncurve",
    ):
        try:
            ptr = block.get_pointer(fieldname)
            if ptr:
                yield ptr
        except (KeyError, SegmentationFault):
            pass


@dna_code("GR")
def _expand_group(block: blendfile.BlendFileBlock):
    log.debug("Collection/group Block: %s (name=%s)", block, block.id_name)

    try:
        objects = block.get_pointer((b"gobject", b"first"))
    except (KeyError, SegmentationFault):
        objects = None

    if objects:
        for item in iterators.listbase(objects):
            try:
                ob = item.get_pointer(b"ob")
                if ob:
                    # Handle ID-view blocks from library overrides
                    if getattr(ob, "dna_type_name", None) == "ID":
                        try:
                            ob_ptr = item.get(b"ob")
                            if ob_ptr:
                                ob2 = item.bfile.dereference_pointer(ob_ptr)
                                if ob2:
                                    ob = ob2
                        except (KeyError, SegmentationFault):
                            pass
                    yield ob
            except (KeyError, SegmentationFault):
                pass

    # Recurse through child collections.
    try:
        children = block.get_pointer((b"children", b"first"))
    except (KeyError, SegmentationFault):
        # 'children' was introduced in Blender 2.8 collections
        # or pointer dereference failed
        children = None

    if children:
        for child in iterators.listbase(children):
            try:
                subcoll = child.get_pointer(b"collection")
            except (KeyError, SegmentationFault):
                continue

            if subcoll is None:
                continue

            if subcoll.dna_type_id == b"ID":
                # This issue happened while recursing a linked-in 'Hidden'
                # collection in the Chimes set of the Spring project. Such
                # collections named 'Hidden' were apparently created while
                # converting files from Blender 2.79 to 2.80. This error
                # isn't reproducible with just Blender 2.80.
                yield subcoll
                continue

            log.debug(
                "recursing into child collection %s (name=%r, type=%r)",
                subcoll,
                subcoll.id_name,
                subcoll.dna_type_name,
            )
            try:
                yield from _expand_group(subcoll)
            except (KeyError, SegmentationFault):
                # If recursion fails, at least yield the collection itself
                yield subcoll


@dna_code("LA")
def _expand_lamp(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_nodetree_id(block)
    yield from _expand_generic_mtex(block)


@dna_code("MA")
def _expand_material(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_nodetree_id(block)
    yield from _expand_generic_mtex(block)

    try:
        group = block.get_pointer(b"group")
        if group:
            yield group
    except (KeyError, SegmentationFault):
        # Groups were removed from Blender 2.8, or pointer dereference failed
        pass


@dna_code("MB")
def _expand_metaball(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_material(block)


@dna_code("ME")
def _expand_mesh(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_material(block)
    yield block.get_pointer(b"texcomesh")
    # TODO, TexFace? - it will be slow, we could simply ignore :S


@dna_code("NT")
def _expand_node_tree(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_nodetree(block)


@dna_code("OB")
def _expand_object(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_material(block)

    try:
        data_block = block.get_pointer(b"data")
        if data_block:
            # Handle ID-view blocks from library overrides
            if getattr(data_block, "dna_type_name", None) == "ID":
                try:
                    data_ptr = block.get(b"data")
                    if data_ptr:
                        data_block2 = block.bfile.dereference_pointer(data_ptr)
                        if data_block2:
                            data_block = data_block2
                except (KeyError, SegmentationFault):
                    pass
            yield data_block
    except (KeyError, SegmentationFault):
        pass

    try:
        transflag = block[b"transflag"]
        if transflag & cdefs.OB_DUPLIGROUP:
            try:
                yield block.get_pointer(b"dup_group")
            except (KeyError, SegmentationFault):
                pass
    except (KeyError, SegmentationFault):
        pass

    try:
        yield block.get_pointer(b"proxy")
    except (KeyError, SegmentationFault):
        pass

    try:
        yield block.get_pointer(b"proxy_group")
    except (KeyError, SegmentationFault):
        pass

    # 'ob->pose->chanbase[...].custom'
    try:
        block_pose = block.get_pointer(b"pose")
    except (KeyError, SegmentationFault):
        block_pose = None

    if block_pose:
        try:
            assert block_pose.dna_type.dna_type_id == b"bPose"
            # sdna_index_bPoseChannel = block_pose.file.sdna_index_from_id[b'bPoseChannel']
            channels = block_pose.get_pointer((b"chanbase", b"first"))
            for pose_chan in iterators.listbase(channels):
                try:
                    yield pose_chan.get_pointer(b"custom")
                except (KeyError, SegmentationFault):
                    pass
        except (KeyError, SegmentationFault, AssertionError):
            pass

    # Expand the objects 'ParticleSettings' via 'ob->particlesystem[...].part'
    # sdna_index_ParticleSystem = block.file.sdna_index_from_id.get(b'ParticleSystem')
    # if sdna_index_ParticleSystem is not None:
    try:
        psystems = block.get_pointer((b"particlesystem", b"first"))
    except (KeyError, SegmentationFault):
        psystems = None

    if psystems:
        for psystem in iterators.listbase(psystems):
            try:
                yield psystem.get_pointer(b"part")
            except (KeyError, SegmentationFault):
                pass

    # Modifiers can also refer to other datablocks, which should also get expanded.
    for block_mod in iterators.modifiers(block):
        try:
            mod_type = block_mod[b"modifier", b"type"]
        except (KeyError, SegmentationFault):
            continue

        # Currently only node groups are supported. If the support should expand
        # to more types, something more intelligent than this should be made.
        if mod_type == cdefs.eModifierType_Nodes:
            yield from _expand_generic_idprops(block_mod)
            try:
                node_group = block_mod.get_pointer(b"node_group")
                if node_group:
                    # Handle ID-view blocks
                    if getattr(node_group, "dna_type_name", None) == "ID":
                        try:
                            ng_ptr = block_mod.get(b"node_group")
                            if ng_ptr:
                                node_group2 = block_mod.bfile.dereference_pointer(ng_ptr)
                                if node_group2:
                                    node_group = node_group2
                        except (KeyError, SegmentationFault):
                            pass
                    yield node_group
            except (KeyError, SegmentationFault):
                pass


@dna_code("PA")
def _expand_particle_settings(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_mtex(block)

    try:
        block_ren_as = block[b"ren_as"]
    except (KeyError, SegmentationFault):
        return

    if block_ren_as == cdefs.PART_DRAW_GR:
        try:
            dup_group = block.get_pointer(b"dup_group")
            if dup_group:
                yield dup_group
        except (KeyError, SegmentationFault):
            pass
    elif block_ren_as == cdefs.PART_DRAW_OB:
        try:
            dup_ob = block.get_pointer(b"dup_ob")
            if dup_ob:
                yield dup_ob
        except (KeyError, SegmentationFault):
            pass


@dna_code("SC")
def _expand_scene(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_nodetree_id(block)

    for field_name in (b"camera", b"world"):
        try:
            ptr = block.get_pointer(field_name)
            if ptr:
                yield ptr
        except (KeyError, SegmentationFault):
            pass

    for field_name in (b"set", b"clip"):
        try:
            ptr = block.get_pointer(field_name, default=None)
            if ptr:
                yield ptr
        except (KeyError, SegmentationFault):
            pass

    # sdna_index_Base = block.file.sdna_index_from_id[b'Base']
    # for item in bf_utils.iter_ListBase(block.get_pointer((b'base', b'first'))):
    #     yield item.get_pointer(b'object', sdna_index_refine=sdna_index_Base)
    try:
        bases = block.get_pointer((b"base", b"first"))
    except (KeyError, SegmentationFault):
        bases = None

    if bases:
        for base in iterators.listbase(bases):
            try:
                obj = base.get_pointer(b"object")
                if obj:
                    # Handle ID-view blocks from library overrides
                    if getattr(obj, "dna_type_name", None) == "ID":
                        try:
                            obj_ptr = base.get(b"object")
                            if obj_ptr:
                                obj2 = base.bfile.dereference_pointer(obj_ptr)
                                if obj2:
                                    obj = obj2
                        except (KeyError, SegmentationFault):
                            pass
                    yield obj
            except (KeyError, SegmentationFault):
                pass

    # Sequence Editor
    try:
        block_ed = block.get_pointer(b"ed")
    except (KeyError, SegmentationFault):
        block_ed = None

    if not block_ed:
        return

    strip_type_to_field = {
        cdefs.SEQ_TYPE_SCENE: b"scene",
        cdefs.SEQ_TYPE_MOVIECLIP: b"clip",
        cdefs.SEQ_TYPE_MASK: b"mask",
        cdefs.SEQ_TYPE_SOUND_RAM: b"sound",
    }
    for strip, strip_type in iterators.sequencer_strips(block_ed):
        try:
            field_name = strip_type_to_field[strip_type]
        except KeyError:
            continue
        try:
            ptr = strip.get_pointer(field_name)
            if ptr:
                yield ptr
        except (KeyError, SegmentationFault):
            pass


@dna_code("TE")
def _expand_texture(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_nodetree_id(block)
    try:
        ima = block.get_pointer(b"ima")
        if ima:
            # Handle ID-view blocks from library overrides
            if getattr(ima, "dna_type_name", None) == "ID":
                try:
                    ima_ptr = block.get(b"ima")
                    if ima_ptr:
                        ima2 = block.bfile.dereference_pointer(ima_ptr)
                        if ima2:
                            ima = ima2
                except (KeyError, SegmentationFault):
                    pass
            yield ima
    except (KeyError, SegmentationFault):
        pass


@dna_code("WO")
def _expand_world(block: blendfile.BlendFileBlock):
    yield from _expand_generic_animdata(block)
    yield from _expand_generic_nodetree_id(block)
    yield from _expand_generic_mtex(block)
