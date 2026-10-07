"""Pure ranking helpers: Reciprocal Rank Fusion and join-path expansion over foreign keys."""

from collections import deque
from collections.abc import Iterable, Mapping, Sequence

RRF_K = 60  # the constant from Cormack et al. (2009); dampens the weight of top ranks


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]], *, k: int = RRF_K
) -> list[tuple[str, float]]:
    """Fuse ranked lists: ``score(d) = sum over lists of 1 / (k + rank)``, rank starting at 1.

    Args:
        rankings: Ranked item lists by source name (e.g. ``{"vector": [...], "text": [...]}``).
        k: RRF constant.

    Returns:
        ``(item, score)`` by descending score; ties broken by item for determinism.
    """
    scores: dict[str, float] = {}
    for ranking in rankings.values():
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def build_graph(edges: Iterable[tuple[str, str]]) -> dict[str, set[str]]:
    """Undirected adjacency sets from ``(a, b)`` edges (joins work in both directions)."""
    graph: dict[str, set[str]] = {}
    for a, b in edges:
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    return graph


def _shortest_path(graph: Mapping[str, set[str]], sources: set[str], target: str) -> list[str]:
    """Nodes strictly between ``sources`` and ``target`` on a shortest path; [] if none."""
    previous: dict[str, str | None] = dict.fromkeys(sorted(sources))
    queue = deque(sorted(sources))
    while queue:
        node = queue.popleft()
        if node == target:
            path = []
            step = previous[node]
            while step is not None and step not in sources:
                path.append(step)
                step = previous[step]
            return path[::-1]
        for neighbour in sorted(graph.get(node, ())):
            if neighbour not in previous:
                previous[neighbour] = node
                queue.append(neighbour)
    return []


def expand_join_paths(selected: Sequence[str], graph: Mapping[str, set[str]]) -> list[str]:
    """Relations to add so that ``selected`` can be joined together.

    Greedy Steiner-tree approximation: walk ``selected`` in relevance order and connect each one
    to the set built so far by a shortest path in the foreign-key graph. Relations with no path
    (e.g. an isolated table) are left as they are.

    Returns:
        The added relations, in the order they were needed (never any of ``selected``).
    """
    if not selected:
        return []
    connected = {selected[0]}
    added: list[str] = []
    for relation in selected[1:]:
        if relation in connected:
            continue
        # Intermediate nodes only: [] when adjacent to the connected set, or unreachable.
        path = _shortest_path(graph, connected, relation)
        added += [node for node in path if node not in selected and node not in added]
        connected.update(path)
        connected.add(relation)
    return added
