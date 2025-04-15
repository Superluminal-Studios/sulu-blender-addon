import bpy

def get_file_extension_from_format(file_format, scene=None, node=None):
    """Return suitable file extension for the given format."""
    base_format_ext_map = {
        'PNG': 'png', 'JPEG': 'jpg', 'JPEG2000': 'jp2', 'TARGA': 'tga',
        'TARGA_RAW': 'tga', 'AVI_JPEG': 'avi', 'AVI_RAW': 'avi',
        'BMP': 'bmp', 'HDR': 'hdr', 'IRIS': 'rgb', 'OPEN_EXR': 'exr',
        'OPEN_EXR_MULTILAYER': 'exr', 'TIFF': 'tif', 'WEBP': 'webp',
    }
    
    ffmpeg_container_ext_map = {
        'MPEG1': 'mpg', 'MPEG2': 'mpg', 'MPEG4': 'mp4', 'AVI': 'avi',
        'QUICKTIME': 'mov', 'DV': 'dv', 'OGG': 'ogg', 'MKV': 'mkv',
        'FLASH': 'flv', 'WEBM': 'webm',
    }
    
    if file_format != 'FFMPEG':
        return base_format_ext_map.get(file_format, file_format.lower())
    
    container = None
    if scene is not None and hasattr(scene.render, "ffmpeg"):
        container = scene.render.ffmpeg.format
    
    if not container:
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
    # Even when there is no composite node, or it is muted, 
    # Blender still writes to the scene output path
    if not scene.use_nodes:
        return True
    if has_sequencer_non_audio_clips(scene):
        return True
    # Always consider scene output active regardless of compositor state
    return True


VIEW_LAYER_PASSES_MAP = {
    # Data
    "use_pass_combined": "Combined", "use_pass_z": "Depth",
    "use_pass_mist": "Mist", "use_pass_position": "Position",
    "use_pass_normal": "Normal", "use_pass_vector": "Vector",
    "use_pass_uv": "UV", "use_pass_denoising_data": "Denoising",
    # Index
    "use_pass_object_index": "IndexOB", "use_pass_material_index": "IndexMA",
    # Debug
    "use_pass_sample_count": "SampleCount",
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
    "use_pass_ambient_occlusion": "AO", "use_pass_shadow": "Shadow",
    "use_pass_shadow_catcher": "ShadowCatcher", "use_pass_emit": "Emission",
    "use_pass_environment": "Environment",
}


def gather_multilayer_scene_passes(scene, used_view_layer_names):
    """Gather enabled render passes across used view layers."""
    passes_set = set()
    
    for vlayer in scene.view_layers:
        if vlayer.name not in used_view_layer_names:
            continue
        
        # Normal passes
        for prop_name, pass_label in VIEW_LAYER_PASSES_MAP.items():
            if hasattr(vlayer, prop_name) and getattr(vlayer, prop_name):
                passes_set.add(pass_label)
        
        # Cryptomatte expansions
        crypt_depth = getattr(vlayer, "pass_cryptomatte_depth", 0)
        crypt_ch_count = crypt_depth // 2
        if crypt_ch_count > 0:
            if getattr(vlayer, "use_pass_cryptomatte_object", False):
                passes_set.update(f"CryptoObject{str(i).zfill(2)}" for i in range(crypt_ch_count))
            if getattr(vlayer, "use_pass_cryptomatte_material", False):
                passes_set.update(f"CryptoMaterial{str(i).zfill(2)}" for i in range(crypt_ch_count))
            if getattr(vlayer, "use_pass_cryptomatte_asset", False):
                passes_set.update(f"CryptoAsset{str(i).zfill(2)}" for i in range(crypt_ch_count))
        
        # AOVs
        passes_set.update(f"AOV_{aov.name}" for aov in vlayer.aovs)
    
    return sorted(passes_set)


def get_used_view_layers(scene, using_cli=False):
    """Return set of view-layer names that will be rendered."""
    used = set()
    
    active_layer_name = bpy.context.view_layer.name if hasattr(bpy.context, "view_layer") and bpy.context.view_layer else None
    single_layer = getattr(scene.render, "use_single_layer", False)
    
    if single_layer and not using_cli:
        if active_layer_name and active_layer_name in scene.view_layers:
            if scene.view_layers[active_layer_name].use:
                used.add(active_layer_name)
    else:
        used = {vl.name for vl in scene.view_layers if vl.use}
    
    return used


def gather_upstream_view_layers(node, node_tree, visited=None):
    """Find all view-layer names upstream from node."""
    if visited is None:
        visited = set()
    
    if node in visited:
        return set()
    visited.add(node)
    
    result = set()
    if node.type == 'R_LAYERS':
        result.add(node.layer)
    
    for input_socket in node.inputs:
        for link in input_socket.links:
            if link.from_node:
                result |= gather_upstream_view_layers(link.from_node, node_tree, visited)
    
    return result


def get_render_layer_nodes_connected_to_file_output(scene, fon):
    """Get view-layer names that feed into the FileOutput node."""
    if not scene.node_tree:
        return set()
    
    used_view_layers = set()
    for socket in fon.inputs:
        for link in socket.links:
            if link.from_node:
                used_view_layers |= gather_upstream_view_layers(link.from_node, scene.node_tree)
    return used_view_layers


def gather_file_output_node_outputs(scene, fon, used_view_layer_names, using_cli=False):
    """Gather outputs for a FileOutput node."""
    connected_vlayers = get_render_layer_nodes_connected_to_file_output(scene, fon)
    
    if not connected_vlayers or connected_vlayers.isdisjoint(used_view_layer_names):
        return []
    
    fon_format = fon.format.file_format
    fon_extension = get_file_extension_from_format(fon_format, scene=scene, node=fon)
    
    base_path = fon.base_path or "//"
    if fon_format != 'OPEN_EXR_MULTILAYER' and base_path and not base_path.endswith(("/", "\\")):
        base_path += "/"
    
    outputs = []
    if fon_format == 'OPEN_EXR_MULTILAYER':
        # Single multi-layer EXR
        layer_names = [ls.name for ls in fon.layer_slots]
        outputs.append({
            "filepath": f"{base_path}####.{fon_extension}",
            "file_extension": fon_extension,
            "node": fon.name,
            "layers": layer_names
        })
    else:
        # One file per slot
        for slot in fon.file_slots:
            outputs.append({
                "filepath": f"{base_path}{slot.path}####.{fon_extension}",
                "file_extension": fon_extension,
                "node": fon.name,
                "layers": None
            })
    
    return outputs


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


def gather_warnings(scene, outputs):
    """Generate warnings for scene and its render outputs."""
    warnings = []
    
    # Check for duplicate file outputs
    filepath_dict = {}  # Maps filepath to [outputs with that path]
    for output in outputs:
        filepath = output["filepath"]
        if filepath not in filepath_dict:
            filepath_dict[filepath] = []
        filepath_dict[filepath].append(output)
    
    for filepath, output_list in filepath_dict.items():
        if len(output_list) > 1:
            # Get the responsible nodes
            nodes = [output.get("node", "Scene Output") for output in output_list]
            nodes_str = ", ".join([n for n in nodes if n]) or "Scene Output"
            
            warnings.append({
                "severity": "warning",
                "type": "duplicate_fileoutput",
                "message": f"Duplicate file output: {filepath} used {len(output_list)} times",
                "node": nodes_str,
                "view_layer": None
            })
    
    # Check for view layers that are enabled but not used in compositor
    used_view_layer_names = get_used_view_layers(scene)
    
    if scene.use_nodes and scene.node_tree:
        # Find all view layers connected to any output in the compositor
        all_connected_view_layers = set()
        for node in scene.node_tree.nodes:
            if node.type == 'OUTPUT_FILE' and not node.mute:
                connected_vlayers = get_render_layer_nodes_connected_to_file_output(scene, node)
                all_connected_view_layers.update(connected_vlayers)
            elif node.type == 'COMPOSITE' and not node.mute:
                connected_vlayers = gather_upstream_view_layers(node, scene.node_tree)
                all_connected_view_layers.update(connected_vlayers)
        
        # Find view layers that are enabled but not connected
        for vlayer in scene.view_layers:
            if vlayer.name in used_view_layer_names and vlayer.name not in all_connected_view_layers:
                warnings.append({
                    "severity": "warning",
                    "type": "unused_view_layer",
                    "message": f"View layer '{vlayer.name}' is enabled but not used in compositor",
                    "node": None,
                    "view_layer": vlayer.name
                })
    
    # Check for sequencer enabled with non-sound sequences
    if has_sequencer_non_audio_clips(scene):
        warnings.append({
            "severity": "info",
            "type": "sequencer_with_non_audio",
            "message": "Sequencer contains non-audio sequences",
            "node": None,
            "view_layer": None
        })
    
    # Check for nodes present but use_nodes not enabled
    if not scene.use_nodes and scene.node_tree and len(scene.node_tree.nodes) > 0:
        warnings.append({
            "severity": "warning",
            "type": "nodes_without_use_nodes",
            "message": "Nodes present but 'use nodes' not enabled",
            "node": None,
            "view_layer": None
        })
    
    return warnings


def gather_render_outputs(scene, using_cli=False):
    """Get all outputs for this scene."""
    outputs = []
    used_view_layer_names = get_used_view_layers(scene, using_cli=using_cli)
    
    # Scene's own output
    scene_render_path = scene.render.filepath
    scene_format = scene.render.image_settings.file_format
    scene_extension = get_file_extension_from_format(scene_format, scene=scene)
    
    if scene_output_is_active(scene):
        # When sequencer has non-audio clips, only a single "image" pass/layer is output
        if scene_format == 'OPEN_EXR_MULTILAYER' and not has_sequencer_non_audio_clips(scene):
            pass_list = gather_multilayer_scene_passes(scene, used_view_layer_names)
            outputs.append({
                "filepath": f"{scene_render_path}####.{scene_extension}",
                "file_extension": scene_extension,
                "node": None,
                "layers": pass_list
            })
        else:
            # For sequencer or non-multilayer formats, just a single layer
            outputs.append({
                "filepath": f"{scene_render_path}####.{scene_extension}",
                "file_extension": scene_extension,
                "node": None,
                "layers": None
            })
    
    # File Output Nodes - Only process if sequencer is not active with non-audio clips
    if not has_sequencer_non_audio_clips(scene) and scene.use_nodes and scene.node_tree:
        for node in scene.node_tree.nodes:
            if node.type == 'OUTPUT_FILE' and not node.mute:
                # Skip duplicates of scene's EXR multilayer path
                node_format = node.format.file_format
                if (node_format == 'OPEN_EXR_MULTILAYER' and 
                    scene_format == 'OPEN_EXR_MULTILAYER' and
                    scene_render_path and node.base_path and
                    bpy.path.abspath(node.base_path) == bpy.path.abspath(scene_render_path)):
                    continue
                
                node_outputs = gather_file_output_node_outputs(
                    scene, node, used_view_layer_names, using_cli=using_cli
                )
                outputs.extend(node_outputs)
    
    # Handle stereoscopic views
    outputs = replicate_single_layer_views(scene, outputs)
    
    # Generate warnings
    warnings = gather_warnings(scene, outputs)

    return {"outputs": outputs, "warnings": warnings}


def gather_all_scenes_outputs(using_cli=False):
    """Get render outputs for all scenes."""
    return {scn.name: gather_render_outputs(scn, using_cli) for scn in bpy.data.scenes}


if __name__ == "__main__":
    # Single scene usage
    scn = bpy.context.scene
    scene_data = gather_render_outputs(scn)
    print("=== Outputs for current scene:", scn.name, "===")
    for out_item in scene_data["outputs"]:
        print(out_item)
    
    print("\n=== Warnings for current scene:", scn.name, "===")
    for warning in scene_data["warnings"]:
        print(f"{warning['severity'].upper()}: {warning['message']}")
        if warning["node"]:
            print(f"  Node: {warning['node']}")
        if warning["view_layer"]:
            print(f"  View Layer: {warning['view_layer']}")
    
    # All scenes usage
    print("\n=== Gathering for all scenes: ===")
    all_scenes_dict = gather_all_scenes_outputs()
    for scene_name, data in all_scenes_dict.items():
        print(f"\nScene '{scene_name}' outputs:")
        for item in data["outputs"]:
            print("  ", item)
        
        print(f"\nScene '{scene_name}' warnings:")
        for warning in data["warnings"]:
            print(f"  {warning['severity'].upper()}: {warning['message']}")
            if warning["node"]:
                print(f"    Node: {warning['node']}")
            if warning["view_layer"]:
                print(f"    View Layer: {warning['view_layer']}")