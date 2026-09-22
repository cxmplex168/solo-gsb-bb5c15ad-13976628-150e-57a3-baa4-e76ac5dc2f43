"""POST /audit/geojson 的端到端测试。

复用与 /audit 相同的请求体；本文件只关注 GeoJSON 表达：
entry=包含全部跨段航迹顶点的 LineString，graze=进入点到离开点的 Point/LineString，
Feature 属性与顺序与审计结果一致。
"""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ZONE = {
    "id": "nfz-1",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
    },
    "active_from": "2026-09-22T10:00:00Z",
    "active_to": "2026-09-22T11:00:00Z",
    "min_alt": 0,
    "max_alt": 100,
}

PROPERTY_KEYS = {"zone_id", "kind", "entry_time", "exit_time", "segment_start", "segment_end"}


def wp(lon, lat, alt, time):
    return {"lon": lon, "lat": lat, "alt": alt, "time": time}


def audit_geojson(waypoints, zones=None):
    payload = {"waypoints": waypoints, "zones": zones if zones is not None else [copy.deepcopy(ZONE)]}
    return client.post("/audit/geojson", json=payload)


def audit_json(waypoints, zones=None):
    payload = {"waypoints": waypoints, "zones": zones if zones is not None else [copy.deepcopy(ZONE)]}
    return client.post("/audit", json=payload)


def assert_matches_violation(props, v):
    """GeoJSON 属性必须与 /audit 的对应违规记录一致。"""
    assert props["zone_id"] == v["zone_id"]
    assert props["kind"] == v["kind"]
    assert props["entry_time"] == v["entry_time"]
    assert props["exit_time"] == v["exit_time"]
    assert props["segment_start"] == v["segment_start"]
    assert props["segment_end"] == v["segment_end"]


# ---------------------------------------------------------------- 结构

def test_response_is_feature_collection():
    r = audit_geojson([wp(-10, 5, 50, "2026-09-22T10:00:00Z"),
                       wp(20, 5, 50, "2026-09-22T10:30:00Z")])
    assert r.status_code == 200, r.text
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    feat = fc["features"][0]
    assert feat["type"] == "Feature"
    assert set(feat["properties"].keys()) == PROPERTY_KEYS


def test_empty_result_is_empty_feature_collection():
    r = audit_geojson([wp(0, 0, 0, "2026-09-22T10:00:00Z"),
                       wp(1, 1, 1, "2026-09-22T10:01:00Z")], [])
    assert r.status_code == 200
    assert r.json() == {"type": "FeatureCollection", "features": []}


# ---------------------------------------------------------------- entry

def test_entry_single_segment_is_linestring_of_entry_and_exit():
    wps = [wp(-10, 5, 50, "2026-09-22T10:00:00Z"),
           wp(20, 5, 50, "2026-09-22T10:30:00Z")]
    r = audit_geojson(wps)
    v = audit_json(wps).json()["violations"][0]
    feat = r.json()["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    coords = feat["geometry"]["coordinates"]
    assert coords == [[0.0, 5.0, 50.0], [10.0, 5.0, 50.0]]
    assert_matches_violation(feat["properties"], v)
    assert feat["properties"] == {
        "zone_id": "nfz-1",
        "kind": "entry",
        "entry_time": "2026-09-22T10:10:00Z",
        "exit_time": "2026-09-22T10:20:00Z",
        "segment_start": 0,
        "segment_end": 0,
    }


def test_entry_linestring_includes_all_crossed_track_vertices():
    """跨两条航段的 entry：LineString 必须包含进入点、区内途经航点、离开点。"""
    wps = [wp(-10, 5, 50, "2026-09-22T10:00:00Z"),
           wp(5, 5, 50, "2026-09-22T10:15:00Z"),
           wp(20, 5, 50, "2026-09-22T10:30:00Z")]
    feat = audit_geojson(wps).json()["features"][0]
    v = audit_json(wps).json()["violations"][0]
    assert v["segment_start"] == 0 and v["segment_end"] == 1
    assert feat["geometry"]["type"] == "LineString"
    assert feat["geometry"]["coordinates"] == [
        [0.0, 5.0, 50.0],   # 进入点（seg0 插值）
        [5.0, 5.0, 50.0],   # 跨段航迹顶点 wp[1]
        [10.0, 5.0, 50.0],  # 离开点（seg1 插值）
    ]
    assert_matches_violation(feat["properties"], v)


def test_entry_linestring_interpolated_altitudes():
    """高度裁剪场景：坐标高度取插值后的进入/离开高度。"""
    wps = [wp(-10, 5, 0, "2026-09-22T10:00:00Z"),
           wp(20, 5, 200, "2026-09-22T10:30:00Z")]
    feat = audit_geojson(wps).json()["features"][0]
    coords = feat["geometry"]["coordinates"]
    assert coords[0][:2] == [0.0, 5.0]
    assert abs(coords[0][2] - 200 / 3) < 1e-6
    assert coords[1] == [5.0, 5.0, 100.0]


def test_start_inside_zone_entry_at_first_waypoint():
    wps = [wp(5, 5, 50, "2026-09-22T10:00:00Z"),
           wp(20, 5, 50, "2026-09-22T10:15:00Z")]
    feat = audit_geojson(wps).json()["features"][0]
    assert feat["geometry"]["coordinates"] == [[5.0, 5.0, 50.0], [10.0, 5.0, 50.0]]


def test_merged_corner_graze_and_entry_dedupes_shared_vertex():
    """seg0 末端擦角 (0,0) 与 seg1 进入合并为一条 entry：

    进入点与共享航点 wp[1] 坐标相同，LineString 中应相邻去重。
    """
    wps = [wp(-10, 10, 50, "2026-09-22T10:00:00Z"),
           wp(0, 0, 50, "2026-09-22T10:15:00Z"),
           wp(20, 5, 50, "2026-09-22T10:30:00Z")]
    feat = audit_geojson(wps).json()["features"][0]
    v = audit_json(wps).json()["violations"][0]
    assert feat["properties"]["kind"] == "entry" == v["kind"]
    coords = feat["geometry"]["coordinates"]
    assert coords == [[0.0, 0.0, 50.0], [10.0, 2.5, 50.0]]
    assert_matches_violation(feat["properties"], v)


# ---------------------------------------------------------------- graze

def test_graze_tangent_point_is_point_geometry():
    wps = [wp(-10, 10, 50, "2026-09-22T10:00:00Z"),
           wp(10, -10, 50, "2026-09-22T10:30:00Z")]
    feat = audit_geojson(wps).json()["features"][0]
    assert feat["geometry"]["type"] == "Point"
    assert feat["geometry"]["coordinates"] == [0.0, 0.0, 50.0]
    assert feat["properties"]["kind"] == "graze"
    assert feat["properties"]["entry_time"] == feat["properties"]["exit_time"]


def test_graze_along_boundary_is_two_point_linestring():
    wps = [wp(-10, 10, 50, "2026-09-22T10:00:00Z"),
           wp(20, 10, 50, "2026-09-22T10:30:00Z")]
    feat = audit_geojson(wps).json()["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    assert feat["geometry"]["coordinates"] == [[0.0, 10.0, 50.0], [10.0, 10.0, 50.0]]
    assert feat["properties"]["kind"] == "graze"
    assert feat["properties"]["entry_time"] == "2026-09-22T10:10:00Z"
    assert feat["properties"]["exit_time"] == "2026-09-22T10:20:00Z"


# ---------------------------------------------------------------- 顺序与一致性

def test_feature_order_matches_audit_result_order():
    zone2 = copy.deepcopy(ZONE)
    zone2["id"] = "nfz-2"
    zone2["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]],
    }
    wps = [wp(-10, 5, 50, "2026-09-22T10:00:00Z"),
           wp(40, 5, 50, "2026-09-22T10:50:00Z")]
    zones = [zone2, copy.deepcopy(ZONE)]

    violations = audit_json(wps, zones).json()["violations"]
    features = audit_geojson(wps, zones).json()["features"]
    assert len(features) == len(violations) == 2
    for feat, v in zip(features, violations):
        assert_matches_violation(feat["properties"], v)
    assert [f["properties"]["zone_id"] for f in features] == ["nfz-1", "nfz-2"]
    times = [f["properties"]["entry_time"] for f in features]
    assert times == sorted(times)


def test_multipolygon_zone_one_feature_per_interval():
    zone = copy.deepcopy(ZONE)
    zone["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]],
        ],
    }
    wps = [wp(-10, 5, 50, "2026-09-22T10:00:00Z"),
           wp(40, 5, 50, "2026-09-22T10:50:00Z")]
    fc = audit_geojson(wps, [zone]).json()
    assert len(fc["features"]) == 2
    assert all(f["geometry"]["type"] == "LineString" for f in fc["features"])


# ---------------------------------------------------------------- 422 复用

def test_out_of_order_waypoints_422():
    r = audit_geojson([wp(0, 0, 0, "2026-09-22T10:05:00Z"),
                       wp(1, 1, 1, "2026-09-22T10:00:00Z")])
    assert r.status_code == 422
    assert "时间" in r.json()["detail"]


def test_self_intersecting_polygon_422():
    zone = copy.deepcopy(ZONE)
    zone["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]],
    }
    r = audit_geojson([wp(-10, 5, 50, "2026-09-22T10:00:00Z"),
                       wp(20, 5, 50, "2026-09-22T10:30:00Z")], [zone])
    assert r.status_code == 422
    assert "nfz-1" in r.json()["detail"]
