import bpy

################################################################################
# Helper Functions for Channel Expansion
################################################################################

def _expand_rgb(label):
    """Return .R, .G, .B expansions of the given label."""
    return [
        f"{label}.R",
        f"{label}.G",
        f"{label}.B",
    ]

def _expand_rgba(label):
    """Return .R, .G, .B, .A expansions of the given label."""
    return [
        f"{label}.R",
        f"{label}.G",
        f"{label}.B",
        f"{label}.A",
    ]

def _expand_xyz(label):
    """Return .X, .Y, .Z expansions of the given label."""
    return [
        f"{label}.X",
        f"{label}.Y",
        f"{label}.Z",
    ]

def _expand_uv(label):
    """
    Typical UV pass might produce: .U, .V, and optionally .A
    """
    return [
        f"{label}.U",
        f"{label}.V",
        f"{label}.A",  # Sometimes present
    ]

def _expand_vector(label):
    """Vector pass can have .X, .Y, .Z, .W in many builds of Blender."""
    return [
        f"{label}.X",
        f"{label}.Y",
        f"{label}.Z",
        f"{label}.W",
    ]

################################################################################
# Extended Pass -> EXR Channel Mapping
################################################################################

EEVEE_PASS_CHANNELS = {
    "Combined":        _expand_rgba("Combined"),
    "Depth":           ["Depth.Z"],
    "Mist":            ["Mist.Z"],
    "Normal":          _expand_xyz("Normal"),
    "Position":        _expand_xyz("Position"),
    "Vector":          _expand_vector("Vector"),
    "UV":              _expand_uv("UV"),
    "IndexOB":         ["IndexOB.X"],
    "IndexMA":         ["IndexMA.X"],
    # Diffuse
    "DiffuseDirect":   _expand_rgb("DiffDir"),
    "DiffuseIndirect": _expand_rgb("DiffInd"),  # If used
    "DiffuseColor":    _expand_rgb("DiffCol"),
    # Glossy
    "GlossyDirect":    _expand_rgb("GlossDir"),
    "GlossyIndirect":  _expand_rgb("GlossInd"), # If used
    "GlossyColor":     _expand_rgb("GlossCol"),
    # Volume
    "VolumeDirect":    _expand_rgb("VolumeDir"),
    "VolumeIndirect":  _expand_rgb("VolumeInd"), # If used
    # Other
    "Emission":        _expand_rgb("Emit"),
    "Environment":     _expand_rgb("Env"),
    "AO":              _expand_rgb("AO"),
    "Shadow":          _expand_rgb("Shadow"),
    "Transparent":     _expand_rgba("Transp"),
}

CYCLES_PASS_CHANNELS = {
    "Combined":        _expand_rgba("Combined"),
    "Depth":           ["Depth.Z"],
    "Mist":            ["Mist.Z"],
    "Position":        _expand_xyz("Position"),
    "Normal":          _expand_xyz("Normal"),
    "Vector":          _expand_vector("Vector"),
    "UV":              _expand_uv("UV"),
    "IndexOB":         ["IndexOB.X"],
    "IndexMA":         ["IndexMA.X"],
    "Denoising": [
        "Denoising Normal.X", "Denoising Normal.Y", "Denoising Normal.Z",
        "Denoising Albedo.R", "Denoising Albedo.G", "Denoising Albedo.B",
        "Denoising Depth.Z"
    ],
    # Diffuse
    "DiffuseDirect":   _expand_rgb("DiffDir"),
    "DiffuseIndirect": _expand_rgb("DiffInd"),
    "DiffuseColor":    _expand_rgb("DiffCol"),
    # Glossy
    "GlossyDirect":    _expand_rgb("GlossDir"),
    "GlossyIndirect":  _expand_rgb("GlossInd"),
    "GlossyColor":     _expand_rgb("GlossCol"),
    # Transmission
    "TransmissionDirect":   _expand_rgb("TransDir"),
    "TransmissionIndirect": _expand_rgb("TransInd"),
    "TransmissionColor":    _expand_rgb("TransCol"),
    # Volume
    "VolumeDirect":    _expand_rgb("VolumeDir"),
    "VolumeIndirect":  _expand_rgb("VolumeInd"),
    # Other
    "AmbientOcclusion": _expand_rgb("AO"),
    "Shadow":           _expand_rgb("Shadow"),
    "ShadowCatcher":    _expand_rgb("Shadow Catcher"),
    "Emission":         _expand_rgb("Emit"),
    "Environment":      _expand_rgb("Env"),
    "SampleCount":      ["Debug Sample Count.X"],
}

################################################################################
# Dictionary of Blender pass props -> pass label
################################################################################

VIEW_LAYER_PASSES_MAP = {
    # Common
    "use_pass_combined": "Combined",
    "use_pass_z": "Depth",
    "use_pass_mist": "Mist",
    "use_pass_normal": "Normal",
    "use_pass_position": "Position",
    "use_pass_vector": "Vector",
    "use_pass_uv": "UV",
    "use_pass_ambient_occlusion": "AO",
    "use_pass_emit": "Emission",
    "use_pass_environment": "Environment",
    "use_pass_shadow": "Shadow",
    "use_pass_object_index": "IndexOB",
    "use_pass_material_index": "IndexMA",
    "use_pass_sample_count": "SampleCount",  # Cycles debug pass
    "use_pass_denoising_data": "Denoising",  # Cycles only

    # Light
    "use_pass_diffuse_direct": "DiffuseDirect",
    "use_pass_diffuse_indirect": "DiffuseIndirect",
    "use_pass_diffuse_color": "DiffuseColor",
    "use_pass_glossy_direct": "GlossyDirect",
    "use_pass_glossy_indirect": "GlossyIndirect",
    "use_pass_glossy_color": "GlossyColor",
    "use_pass_transmission_direct": "TransmissionDirect",
    "use_pass_transmission_indirect": "TransmissionIndirect",
    "use_pass_transmission_color": "TransmissionColor",
    "use_pass_volume_direct": "VolumeDirect",
    "use_pass_volume_indirect": "VolumeIndirect",
    "use_pass_shadow_catcher": "ShadowCatcher",
}

################################################################################
# Utilities for Pass Channels
################################################################################

def gather_exr_channels_for_pass(scene, vlayer, pass_label):
    """Return a list of the actual EXR channel suffixes for the given pass_label."""
    engine = scene.render.engine
    if engine == 'BLENDER_EEVEE':
        return EEVEE_PASS_CHANNELS.get(pass_label, [])
    elif engine == 'CYCLES':
        return CYCLES_PASS_CHANNELS.get(pass_label, [])
    else:
        return []

def gather_multilayer_scene_passes(scene, used_view_layer_names):
    """
    Gather the actual channels that will appear in an OPEN_EXR_MULTILAYER file,
    for all enabled passes across the used view layers in this scene.
    """
    all_channels = set()
    engine = scene.render.engine

    for vlayer in scene.view_layers:
        if vlayer.name not in used_view_layer_names:
            continue

        layer_prefix = vlayer.name

        # 1) Standard pass props
        for prop_name, pass_label in VIEW_LAYER_PASSES_MAP.items():
            if hasattr(vlayer, prop_name) and getattr(vlayer, prop_name):
                suffixes = gather_exr_channels_for_pass(scene, vlayer, pass_label)
                for s in suffixes:
                    all_channels.add(f"{layer_prefix}.{s}")

        # 2) EEVEE-specific checks
        if engine == 'BLENDER_EEVEE':
            if getattr(vlayer.eevee, "use_pass_volume_direct", False):
                for s in EEVEE_PASS_CHANNELS.get("VolumeDirect", []):
                    all_channels.add(f"{layer_prefix}.{s}")
            if getattr(vlayer.eevee, "use_pass_transparent", False):
                for s in EEVEE_PASS_CHANNELS.get("Transparent", []):
                    all_channels.add(f"{layer_prefix}.{s}")

        # 3) Cycles-specific: Light groups
        if engine == 'CYCLES' and hasattr(vlayer, "lightgroups"):
            for lg in vlayer.lightgroups:
                lg_name = lg.name
                for c in ["R", "G", "B"]:
                    all_channels.add(f"{layer_prefix}.Combined_{lg_name}.{c}")

        # 4) Cryptomatte expansions
        crypt_depth = getattr(vlayer, "pass_cryptomatte_depth", 0)
        crypt_ch_count = crypt_depth // 2
        if crypt_ch_count > 0:
            if getattr(vlayer, "use_pass_cryptomatte_object", False):
                for i in range(crypt_ch_count):
                    base = f"CryptoObject{str(i).zfill(2)}"
                    all_channels.update(
                        f"{layer_prefix}.{base}.{ch}" for ch in ["r", "g", "b", "a"]
                    )
            if getattr(vlayer, "use_pass_cryptomatte_material", False):
                for i in range(crypt_ch_count):
                    base = f"CryptoMaterial{str(i).zfill(2)}"
                    all_channels.update(
                        f"{layer_prefix}.{base}.{ch}" for ch in ["r", "g", "b", "a"]
                    )
            if getattr(vlayer, "use_pass_cryptomatte_asset", False):
                for i in range(crypt_ch_count):
                    base = f"CryptoAsset{str(i).zfill(2)}"
                    all_channels.update(
                        f"{layer_prefix}.{base}.{ch}" for ch in ["r", "g", "b", "a"]
                    )

        # 5) AOVs
        for aov in vlayer.aovs:
            aov_prefix = f"{layer_prefix}.{aov.name}"
            if aov.type == 'COLOR':
                for c in ["R", "G", "B", "A"]:
                    all_channels.add(f"{aov_prefix}.{c}")
            else:  # VALUE
                all_channels.add(f"{aov_prefix}.X")

    # Optionally include "Composite.Combined" channels
    all_channels.update([
        "Composite.Combined.R",
        "Composite.Combined.G",
        "Composite.Combined.B",
        "Composite.Combined.A",
    ])

    return sorted(all_channels)

################################################################################
# Node Tree Analysis
################################################################################

def gather_upstream_content(node, node_tree, visited=None):
    """
    Recursively find:
      - Which view layers are upstream
      - Whether we have an un-muted MOVIECLIP or IMAGE node upstream
    Returns a dict:
      {
        "view_layers": set of view-layer names,
        "has_movieclip_or_image": bool
      }
    """
    if visited is None:
        visited = set()
    if node in visited:
        return {"view_layers": set(), "has_movieclip_or_image": False}
    visited.add(node)

    result = {
        "view_layers": set(),
        "has_movieclip_or_image": False,
    }

    # If the node is a Render Layers node, record its layer name
    if node.type == 'R_LAYERS':
        result["view_layers"].add(node.layer)

    # If the node is an un-muted Movie Clip or Image node, mark that as well
    # (If the node is "mute" not typical for these node types, but we check anyway)
    if (not getattr(node, "mute", False)):
        if node.type == 'MOVIECLIP' or node.type == 'IMAGE':
            result["has_movieclip_or_image"] = True

    # Recurse upstream
    for input_socket in node.inputs:
        for link in input_socket.links:
            if link.from_node:
                upstream = gather_upstream_content(link.from_node, node_tree, visited)
                result["view_layers"].update(upstream["view_layers"])
                if upstream["has_movieclip_or_image"]:
                    result["has_movieclip_or_image"] = True

    return result

def get_upstream_content_for_file_output(scene, fon):
    """
    Check all input sockets for a FileOutput node and gather:
      - Which view layers are upstream
      - Whether there are un-muted Movie Clip / Image nodes upstream
    """
    if not scene.node_tree:
        return {"view_layers": set(), "has_movieclip_or_image": False}

    total = {
        "view_layers": set(),
        "has_movieclip_or_image": False,
    }
    for socket in fon.inputs:
        for link in socket.links:
            if link.from_node:
                upstream_data = gather_upstream_content(link.from_node, scene.node_tree)
                total["view_layers"].update(upstream_data["view_layers"])
                if upstream_data["has_movieclip_or_image"]:
                    total["has_movieclip_or_image"] = True
    return total

################################################################################
# Existing Utility Functions
################################################################################

def get_file_extension_from_format(file_format, scene=None, node=None):
    """
    Return a suitable file extension for the given format.
    If 'FFMPEG', we look up the container in scene.render.ffmpeg.format,
    otherwise we refer to the base_format_ext_map.
    """

    base_format_ext_map = {
        # Complete list of recognized image formats in Blender:
        'BMP': 'bmp',
        'IRIS': 'rgb',
        'PNG': 'png',
        'JPEG': 'jpg',
        'JPEG2000': 'jp2',
        'TARGA': 'tga',
        'TARGA_RAW': 'tga',
        'CINEON': 'cin',
        'DPX': 'dpx',
        'OPEN_EXR_MULTILAYER': 'exr',
        'OPEN_EXR': 'exr',
        'HDR': 'hdr',
        'TIFF': 'tif',
        'WEBP': 'webp',
        'FFMPEG': 'ffmpeg',
    }

    ffmpeg_container_ext_map = {
        'MPEG1': 'mpg',
        'MPEG2': 'mpg',
        'MPEG4': 'mp4',
        'AVI': 'avi',
        'QUICKTIME': 'mov',
        'DV': 'dv',
        'OGG': 'ogg',
        'MKV': 'mkv',
        'FLASH': 'flv',
        'WEBM': 'webm',
    }

    if file_format != 'FFMPEG':
        return base_format_ext_map.get(file_format, file_format.lower())

    # If file_format == 'FFMPEG', check the container:
    container = None
    if scene is not None and hasattr(scene.render, "ffmpeg"):
        container = scene.render.ffmpeg.format

    if not container:
        # Default container if not set, typically "MPEG4" → ".mp4"
        return "mp4"

    return ffmpeg_container_ext_map.get(container, container.lower())

def is_using_compositor(scene):
    """Check if scene has active compositor."""
    if not scene.use_nodes or not scene.node_tree:
        return False
    return any(node.type == 'COMPOSITE' and not node.mute for node in scene.node_tree.nodes)

def has_sequencer_non_audio_clips(scene):
    """Check if scene has non-audio sequencer clips."""
    seq_ed = scene.sequence_editor
    if not seq_ed:
        return False
    return any(seq.type != 'SOUND' for seq in seq_ed.sequences_all)

def scene_output_is_active(scene):
    """Determine if scene's output path is used."""
    # Even if no composite node, Blender writes to scene output path.
    return True

def get_used_view_layers(scene, using_cli=False):
    """Return set of view-layer names that will be rendered."""
    used = set()
    active_layer_name = (bpy.context.view_layer.name if hasattr(bpy.context, "view_layer")
                         and bpy.context.view_layer else None)
    single_layer = getattr(scene.render, "use_single_layer", False)

    if single_layer and not using_cli:
        if active_layer_name and active_layer_name in scene.view_layers:
            if scene.view_layers[active_layer_name].use:
                used.add(active_layer_name)
    else:
        used = {vl.name for vl in scene.view_layers if vl.use}
    return used

def replicate_single_layer_views(scene, output_list):
    """Create view-specific outputs for stereoscopic rendering."""
    if not scene.render.use_multiview or scene.render.image_settings.views_format != 'INDIVIDUAL':
        return output_list

    new_list = []
    for entry in output_list:
        try:
            path_without_ext, ext_part = entry["filepath"].rsplit('.', 1)
        except ValueError:
            path_without_ext = entry["filepath"]
            ext_part = entry["file_extension"]

        for v in scene.render.views:
            suffix = v.file_suffix
            out_fp = f"{path_without_ext}{suffix}.{ext_part}" if suffix else f"{path_without_ext}.{ext_part}"
            new_list.append({
                "filepath": out_fp,
                "file_extension": entry["file_extension"],
                "node": entry["node"],
                "layers": entry["layers"]
            })
    return new_list

################################################################################
# Gathering File Output Nodes
################################################################################

def gather_file_output_node_outputs(scene, fon, used_view_layer_names, using_cli=False):
    """Gather outputs for a FileOutput node if it has valid upstream content."""
    upstream_data = get_upstream_content_for_file_output(scene, fon)

    # Only produce outputs if:
    # - There's an intersection of upstream view layers with the used layers, OR
    # - There's a MOVIECLIP/IMAGE node upstream
    if (upstream_data["view_layers"].isdisjoint(used_view_layer_names)
            and not upstream_data["has_movieclip_or_image"]):
        return []

    fon_format = fon.format.file_format
    fon_extension = get_file_extension_from_format(fon_format, scene=scene, node=fon)

    base_path = fon.base_path or "//"
    if fon_format != 'OPEN_EXR_MULTILAYER' and base_path and not base_path.endswith(("/", "\\")):
        base_path += "/"

    outputs = []
    if fon_format == 'OPEN_EXR_MULTILAYER':
        layer_names = [ls.name for ls in fon.layer_slots]
        outputs.append({
            "filepath": f"{base_path}####.{fon_extension}",
            "file_extension": fon_extension,
            "node": fon.name,
            "layers": layer_names
        })
    else:
        for slot in fon.file_slots:
            outputs.append({
                "filepath": f"{base_path}{slot.path}####.{fon_extension}",
                "file_extension": fon_extension,
                "node": fon.name,
                "layers": None
            })
    return outputs

################################################################################
# Warnings & Main Gathering Logic
################################################################################

def gather_warnings(scene, outputs, sequencer_forcing_single=False):
    """Generate warnings for scene and its render outputs."""
    warnings = []

    # If the sequencer has non-audio strips, mention ignoring all other file outputs:
    if sequencer_forcing_single:
        warnings.append({
            "severity": "warning",
            "type": "sequencer_with_non_audio",
            "message": "Sequencer is enabled with non-audio clips. Only scene output is used; all other file outputs are ignored.",
            "node": None,
            "view_layer": None
        })

    # Check for duplicate file outputs
    filepath_dict = {}
    for output in outputs:
        filepath = output["filepath"]
        if filepath not in filepath_dict:
            filepath_dict[filepath] = []
        filepath_dict[filepath].append(output)

    for filepath, output_list in filepath_dict.items():
        if len(output_list) > 1:
            nodes = [output.get("node", "Scene Output") for output in output_list]
            nodes_str = ", ".join(n for n in nodes if n) or "Scene Output"
            warnings.append({
                "severity": "warning",
                "type": "duplicate_fileoutput",
                "message": f"Duplicate file output: {filepath} used {len(output_list)} times",
                "node": nodes_str,
                "view_layer": None
            })

    # Check for view layers that are enabled but not used in compositor
    used_view_layer_names = get_used_view_layers(scene)
    if scene.use_nodes and scene.node_tree and not sequencer_forcing_single:
        all_connected_view_layers = set()
        for node in scene.node_tree.nodes:
            if node.type == 'OUTPUT_FILE' and not node.mute:
                upstream_data = get_upstream_content_for_file_output(scene, node)
                all_connected_view_layers.update(upstream_data["view_layers"])
            elif node.type == 'COMPOSITE' and not node.mute:
                # For the composite node, we only gather R_LAYERS or MOVIECLIP/IMAGE if needed
                # but typically "Composite" is final; so for completeness:
                # we can re-use gather_upstream_content to see if there's a Render Layers node
                comp_upstream = gather_upstream_content(node, scene.node_tree)
                all_connected_view_layers.update(comp_upstream["view_layers"])

        for vlayer in scene.view_layers:
            if vlayer.name in used_view_layer_names and vlayer.name not in all_connected_view_layers:
                warnings.append({
                    "severity": "warning",
                    "type": "unused_view_layer",
                    "message": f"View layer '{vlayer.name}' is enabled but not used in compositor",
                    "node": None,
                    "view_layer": vlayer.name
                })

    # Check for nodes present but 'use_nodes' not enabled
    if not scene.use_nodes and scene.node_tree and len(scene.node_tree.nodes) > 0:
        warnings.append({
            "severity": "warning",
            "type": "nodes_without_use_nodes",
            "message": "Nodes present but 'use nodes' is not enabled",
            "node": None,
            "view_layer": None
        })

    return warnings

def gather_render_outputs(scene, using_cli=False):
    """Get all outputs for this scene, factoring in sequencer behavior."""
    outputs = []
    used_view_layer_names = get_used_view_layers(scene, using_cli=using_cli)

    scene_render_path = scene.render.filepath
    scene_format = scene.render.image_settings.file_format
    scene_extension = get_file_extension_from_format(scene_format, scene=scene)

    # Detect if the sequencer has non-audio clips
    sequencer_has_non_audio = has_sequencer_non_audio_clips(scene)
    sequencer_forcing_single = False

    if scene_output_is_active(scene):
        if sequencer_has_non_audio:
            # Sequencer has non-audio: only scene file output is used
            sequencer_forcing_single = True

            if scene_format == 'OPEN_EXR_MULTILAYER':
                # Only R/G/B channels in the “layers” field
                pass_list = ["R", "G", "B"]
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": pass_list
                })
            else:
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": None
                })

        else:
            # Normal case: no forced single pass from sequencer
            if scene_format == 'OPEN_EXR_MULTILAYER':
                pass_list = gather_multilayer_scene_passes(scene, used_view_layer_names)
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": pass_list
                })
            else:
                outputs.append({
                    "filepath": f"{scene_render_path}####.{scene_extension}",
                    "file_extension": scene_extension,
                    "node": None,
                    "layers": None
                })

    # If sequencer is forcing single, we skip all File Output nodes
    if (not sequencer_forcing_single) and scene.use_nodes and scene.node_tree:
        for node in scene.node_tree.nodes:
            if node.type == 'OUTPUT_FILE' and not node.mute:
                node_format = node.format.file_format
                # Avoid duplicating if scene & node produce the same MLEXR path
                if (
                    node_format == 'OPEN_EXR_MULTILAYER'
                    and scene_format == 'OPEN_EXR_MULTILAYER'
                    and scene_render_path
                    and node.base_path
                    and bpy.path.abspath(node.base_path) == bpy.path.abspath(scene_render_path)
                ):
                    continue

                node_outputs = gather_file_output_node_outputs(
                    scene, node, used_view_layer_names, using_cli=using_cli
                )
                outputs.extend(node_outputs)

    # Handle stereoscopic views
    outputs = replicate_single_layer_views(scene, outputs)

    # Generate warnings
    warnings = gather_warnings(scene, outputs, sequencer_forcing_single=sequencer_forcing_single)

    return {"outputs": outputs, "warnings": warnings}

def gather_all_scenes_outputs(using_cli=False):
    """Get render outputs for all scenes."""
    return {scn.name: gather_render_outputs(scn, using_cli) for scn in bpy.data.scenes}


# if __name__ == "__main__":
#     # Single scene usage
#     scn = bpy.context.scene
#     scene_data = gather_render_outputs(scn)