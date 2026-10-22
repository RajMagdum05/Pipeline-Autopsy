from datetime import datetime, timezone, timedelta
import pytest
from autopsy.services.reconstruction_service import PipelineReconstructionEngine


@pytest.fixture
def engine():
    return PipelineReconstructionEngine()


def _make_span_dict(
    span_id: str,
    parent_span_id: str = None,
    operation_name: str = "op",
    service_name: str = "service_a",
    start_offset_ms: float = 0,
    duration_ms: float = 10,
    status_code: str = "OK",
):
    base_time = datetime(2026, 9, 22, 1, 0, 0, tzinfo=timezone.utc)
    start_dt = base_time + timedelta(milliseconds=start_offset_ms)
    end_dt = start_dt + timedelta(milliseconds=duration_ms)
    return {
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "operation_name": operation_name,
        "service_name": service_name,
        "kind": "INTERNAL",
        "start_time": start_dt,
        "end_time": end_dt,
        "duration_ms": duration_ms,
        "status_code": status_code,
        "status_message": None,
        "attributes": {"test.id": span_id},
        "events": [],
    }


def test_shape_1_linear(engine):
    """
    TEST 1 — Linear Topology:
    A (root) -> B -> C
    """
    spans = [
        _make_span_dict("span_a", parent_span_id=None, operation_name="A", start_offset_ms=0, duration_ms=100),
        _make_span_dict("span_b", parent_span_id="span_a", operation_name="B", start_offset_ms=10, duration_ms=40),
        _make_span_dict("span_c", parent_span_id="span_b", operation_name="C", start_offset_ms=20, duration_ms=20),
    ]

    graph = engine.reconstruct_from_spans("exec-linear", "trace-linear", spans)

    assert graph.reconstruction_status == "COMPLETE"
    assert len(graph.root_nodes) == 1
    assert len(graph.orphan_nodes) == 0

    node_a = graph.root_nodes[0]
    assert node_a.operation_name == "A"
    assert len(node_a.children) == 1

    node_b = node_a.children[0]
    assert node_b.operation_name == "B"
    assert len(node_b.children) == 1

    node_c = node_b.children[0]
    assert node_c.operation_name == "C"
    assert len(node_c.children) == 0


def test_shape_2_branching(engine):
    """
    TEST 2 — Branching Topology:
    A (root)
      ├── B
      └── C
    """
    spans = [
        _make_span_dict("span_a", parent_span_id=None, operation_name="A", start_offset_ms=0, duration_ms=100),
        _make_span_dict("span_b", parent_span_id="span_a", operation_name="B", start_offset_ms=10, duration_ms=30),
        _make_span_dict("span_c", parent_span_id="span_a", operation_name="C", start_offset_ms=50, duration_ms=30),
    ]

    graph = engine.reconstruct_from_spans("exec-branching", "trace-branching", spans)

    assert graph.reconstruction_status == "COMPLETE"
    assert len(graph.root_nodes) == 1

    node_a = graph.root_nodes[0]
    assert len(node_a.children) == 2

    child_names = [c.operation_name for c in node_a.children]
    assert child_names == ["B", "C"]


def test_shape_3_nested(engine):
    """
    TEST 3 — Deeply Nested Topology:
    A -> B -> C -> D
    """
    spans = [
        _make_span_dict("s_a", parent_span_id=None, operation_name="A"),
        _make_span_dict("s_b", parent_span_id="s_a", operation_name="B"),
        _make_span_dict("s_c", parent_span_id="s_b", operation_name="C"),
        _make_span_dict("s_d", parent_span_id="s_c", operation_name="D"),
    ]

    graph = engine.reconstruct_from_spans("exec-nested", "trace-nested", spans)

    assert len(graph.root_nodes) == 1
    curr = graph.root_nodes[0]
    names = [curr.operation_name]

    while curr.children:
        curr = curr.children[0]
        names.append(curr.operation_name)

    assert names == ["A", "B", "C", "D"]


def test_shape_4_parallel_timing(engine):
    """
    TEST 4 — Parallel Operations with Overlapping Timestamps:
    A
      ├── B (starts t=10ms, duration=50ms)
      └── C (starts t=15ms, duration=40ms)  <-- overlaps with B

    B and C must remain sibling children of A, not serialized into A -> B -> C.
    """
    spans = [
        _make_span_dict("span_a", parent_span_id=None, operation_name="A", start_offset_ms=0, duration_ms=100),
        _make_span_dict("span_b", parent_span_id="span_a", operation_name="B", start_offset_ms=10, duration_ms=50),
        _make_span_dict("span_c", parent_span_id="span_a", operation_name="C", start_offset_ms=15, duration_ms=40),
    ]

    graph = engine.reconstruct_from_spans("exec-parallel", "trace-parallel", spans)

    node_a = graph.root_nodes[0]
    assert len(node_a.children) == 2
    assert node_a.children[0].operation_name == "B"
    assert node_a.children[1].operation_name == "C"
    # Neither child should be nested inside the other
    assert len(node_a.children[0].children) == 0
    assert len(node_a.children[1].children) == 0


def test_shape_5_orphan_span(engine):
    """
    TEST 5 — Orphan Span:
    A (root)
    B (parent_span_id = 'MISSING_PARENT_X')

    Expected: B is preserved as an orphan node, graph status set to WARNINGS, warning emitted.
    """
    spans = [
        _make_span_dict("span_a", parent_span_id=None, operation_name="A"),
        _make_span_dict("span_b", parent_span_id="MISSING_PARENT_X", operation_name="B"),
    ]

    graph = engine.reconstruct_from_spans("exec-orphan", "trace-orphan", spans)

    assert graph.reconstruction_status == "WARNINGS"
    assert len(graph.root_nodes) == 1
    assert graph.root_nodes[0].operation_name == "A"

    assert len(graph.orphan_nodes) == 1
    orphan = graph.orphan_nodes[0]
    assert orphan.operation_name == "B"
    assert orphan.is_orphan is True

    # Check structural warning
    warning_codes = [w["code"] for w in graph.warnings]
    assert "ORPHAN_SPAN" in warning_codes


def test_shape_6_multiple_roots(engine):
    """
    TEST 6 — Multiple Root Spans:
    A (parent = None)
    B (parent = None)

    Expected: Both roots preserved, graph status set to WARNINGS, MULTIPLE_ROOT_SPANS warning emitted.
    """
    spans = [
        _make_span_dict("span_a", parent_span_id=None, operation_name="A", start_offset_ms=0),
        _make_span_dict("span_b", parent_span_id=None, operation_name="B", start_offset_ms=5),
    ]

    graph = engine.reconstruct_from_spans("exec-multi-roots", "trace-multi-roots", spans)

    assert graph.reconstruction_status == "WARNINGS"
    assert len(graph.root_nodes) == 2
    root_names = [r.operation_name for r in graph.root_nodes]
    assert root_names == ["A", "B"]

    warning_codes = [w["code"] for w in graph.warnings]
    assert "MULTIPLE_ROOT_SPANS" in warning_codes


def test_shape_7_duplicate_span(engine):
    """
    TEST 7 — Duplicate Span Identifiers:
    Two span records with the same span_id 'span_dup'.

    Expected: Graph status set to WARNINGS, DUPLICATE_SPAN_ID warning emitted without crash.
    """
    spans = [
        _make_span_dict("span_root", parent_span_id=None, operation_name="Root"),
        _make_span_dict("span_dup", parent_span_id="span_root", operation_name="FirstInstance"),
        _make_span_dict("span_dup", parent_span_id="span_root", operation_name="SecondInstance"),
    ]

    graph = engine.reconstruct_from_spans("exec-dup", "trace-dup", spans)

    assert graph.reconstruction_status == "WARNINGS"
    warning_codes = [w["code"] for w in graph.warnings]
    assert "DUPLICATE_SPAN_ID" in warning_codes
