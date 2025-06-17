"""NumPy-backed loose octree for 3D spatial neighbor queries.

Designed for ATC simulation: full rebuild from ~5000 aircraft positions,
fast radius queries for conflict detection (typical radius 10-20 NM).
No scipy dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class OctreeNode:
    """Single node in the loose octree.

    Attributes:
        center: (3,) float64 -- center of this node's tight bounds.
        half_size: Half the side length of the tight bounding cube.
        loose_half_size: ``half_size * loose_factor`` (default 2x) used for
            containment and intersection tests so that objects near octant
            boundaries are less likely to straddle multiple nodes.
        children: List of 8 child nodes, or ``None`` if this is a leaf.
        indices: Aircraft indices stored in this leaf (empty for internal nodes
            unless an index could not be placed in any child).
        depth: Depth of this node in the tree (root = 0).
    """

    center: np.ndarray
    half_size: float
    loose_half_size: float
    children: Optional[list[Optional["OctreeNode"]]]
    indices: list[int] = field(default_factory=list)
    depth: int = 0


# Pre-computed sign table for the 8 octant offsets.
# Child *i* has its center offset from the parent center by
#   _OCTANT_SIGNS[i] * (parent.half_size / 2)
_OCTANT_SIGNS: np.ndarray = np.array(
    [
        [-1, -1, -1],
        [-1, -1, +1],
        [-1, +1, -1],
        [-1, +1, +1],
        [+1, -1, -1],
        [+1, -1, +1],
        [+1, +1, -1],
        [+1, +1, +1],
    ],
    dtype=np.float64,
)


class Octree:
    """Loose octree for fast 3-D radius neighbor queries.

    Parameters:
        max_depth: Maximum tree depth (root = 0).
        leaf_threshold: A node with this many or fewer indices will not be
            subdivided further.
        loose_factor: Multiplier applied to ``half_size`` to get
            ``loose_half_size``.  The default of 2.0 is the classic "loose
            octree" setting.
    """

    def __init__(
        self,
        max_depth: int = 8,
        leaf_threshold: int = 16,
        loose_factor: float = 2.0,
    ) -> None:
        self.max_depth = max_depth
        self.leaf_threshold = leaf_threshold
        self.loose_factor = loose_factor
        self.root: Optional[OctreeNode] = None
        self._positions: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rebuild(self, positions: np.ndarray) -> None:
        """Build (or completely replace) the tree from an (N, 3) array.

        Parameters:
            positions: Shape ``(N, 3)`` float64 array of aircraft positions
                in km.
        """
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError(f"positions must have shape (N, 3), got {positions.shape}")

        n = positions.shape[0]
        self._positions = positions

        if n == 0:
            self.root = None
            return

        # Compute tight bounding cube that contains all positions.
        mins = positions.min(axis=0)
        maxs = positions.max(axis=0)
        center = (mins + maxs) * 0.5
        # Use the largest extent so the root is a cube, add tiny pad.
        half_size = float(np.max(maxs - mins)) * 0.5 + 1e-6

        self.root = OctreeNode(
            center=center,
            half_size=half_size,
            loose_half_size=half_size * self.loose_factor,
            children=None,
            indices=list(range(n)),
            depth=0,
        )

        self._subdivide(self.root)

    def query_radius(self, point: np.ndarray, radius: float) -> list[int]:
        """Return indices of all aircraft within *radius* km of *point*.

        Parameters:
            point: (3,) query position.
            radius: Search radius in km.

        Returns:
            List of matching aircraft indices (unordered).
        """
        if self.root is None or self._positions is None:
            return []

        result: list[int] = []
        radius_sq = radius * radius
        self._query_recursive(self.root, point, radius, radius_sq, result)
        return result

    def query_neighbors(self, idx: int, radius: float) -> list[int]:
        """Return indices of aircraft within *radius* of aircraft *idx*.

        Convenience wrapper around :meth:`query_radius` that excludes *idx*
        from the result set.
        """
        if self._positions is None:
            return []
        point = self._positions[idx]
        results = self.query_radius(point, radius)
        try:
            results.remove(idx)
        except ValueError:
            pass
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _subdivide(self, node: OctreeNode) -> None:
        """Recursively split *node* into octants while above thresholds."""
        if len(node.indices) <= self.leaf_threshold:
            return
        if node.depth >= self.max_depth:
            return

        positions = self._positions
        assert positions is not None

        child_half = node.half_size * 0.5
        child_loose_half = child_half * self.loose_factor

        # Build 8 child centers using the pre-computed sign table.
        # child_centers shape: (8, 3)
        offsets = _OCTANT_SIGNS * child_half
        child_centers = node.center + offsets

        # Vectorised octant assignment: determine which octant each point
        # belongs to based on which side of the parent center it sits on.
        # This gives an integer in [0..7] per index.
        idx_arr = np.array(node.indices, dtype=np.intp)
        pts = positions[idx_arr]  # (M, 3)
        # For each axis: 0 if < center, 1 if >= center  -->  bits: x*4 + y*2 + z*1
        gt = (pts >= node.center).astype(np.intp)  # (M, 3) of 0/1
        octant_ids = gt[:, 0] * 4 + gt[:, 1] * 2 + gt[:, 2]  # (M,)

        # Create children and distribute indices.
        node.children = [None] * 8
        remaining: list[int] = []

        for oid in range(8):
            mask = octant_ids == oid
            child_indices = idx_arr[mask].tolist()

            child_node = OctreeNode(
                center=child_centers[oid],
                half_size=child_half,
                loose_half_size=child_loose_half,
                children=None,
                indices=child_indices,
                depth=node.depth + 1,
            )
            node.children[oid] = child_node

        # Parent no longer stores indices directly (all distributed).
        node.indices = remaining  # empty list

        # Recurse into non-empty children.
        for child in node.children:
            if child is not None and len(child.indices) > 0:
                self._subdivide(child)

    def _query_recursive(
        self,
        node: OctreeNode,
        center: np.ndarray,
        radius: float,
        radius_sq: float,
        result: list[int],
    ) -> None:
        """Depth-first traversal collecting indices within radius."""
        if not self._intersects_sphere(node, center, radius):
            return

        # If leaf (or has leftover indices), check stored points.
        if node.indices:
            positions = self._positions
            assert positions is not None
            idx_arr = np.array(node.indices, dtype=np.intp)
            pts = positions[idx_arr]  # (M, 3)
            diff = pts - center  # (M, 3)
            dist_sq = np.einsum("ij,ij->i", diff, diff)  # (M,)
            hits = idx_arr[dist_sq <= radius_sq]
            result.extend(hits.tolist())

        # Recurse into children.
        if node.children is not None:
            for child in node.children:
                if child is not None:
                    self._query_recursive(child, center, radius, radius_sq, result)

    @staticmethod
    def _intersects_sphere(node: OctreeNode, center: np.ndarray, radius: float) -> bool:
        """Test whether a sphere intersects the node's *loose* AABB.

        Uses the standard closest-point-on-AABB algorithm:
        for each axis, clamp the sphere center to the AABB extents and
        measure squared distance.
        """
        lhs = node.loose_half_size
        lo = node.center - lhs
        hi = node.center + lhs

        # Closest point on AABB to sphere center.
        clamped = np.clip(center, lo, hi)
        diff = clamped - center
        dist_sq = float(diff.dot(diff))
        return dist_sq <= radius * radius
