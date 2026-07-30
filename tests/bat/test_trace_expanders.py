from unittest import mock

from blender_asset_tracer.blendfile import exceptions
from blender_asset_tracer.trace import expanders


def test_nodes_modifier_returns_resolvable_node_group():
    node_group = object()
    modifier = mock.Mock()
    modifier.get_pointer.return_value = node_group

    assert expanders._get_nodes_modifier_node_group(modifier) is node_group
    modifier.get_pointer.assert_called_once_with(b"node_group")


def test_nodes_modifier_ignores_unresolved_node_group_pointer():
    modifier = mock.Mock()
    modifier.get_pointer.side_effect = exceptions.SegmentationFault(
        "address does not exist", 0xDEADBEEF
    )

    assert expanders._get_nodes_modifier_node_group(modifier) is None
