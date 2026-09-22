"""把审计判定结果转为 GeoJSON FeatureCollection。

- entry：LineString，包含跨越的全部航迹顶点
  （进入点 -> 途经的各航点 -> 离开点，相邻重复坐标去重）；
- graze：进入点与离开点重合时用 Point，否则用连接两点的 LineString。

Feature 顺序与 /audit 的 violations 顺序完全一致。
坐标统一为三维 ``[经度, 纬度, 高度]``。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .models import Violation


def _coord(pos: Any) -> List[float]:
    return [pos.lon, pos.lat, pos.alt]


def _dedupe_consecutive(coords: List[List[float]]) -> List[List[float]]:
    """合并首尾相接的相邻命中时，共享航点可能重复出现，做相邻去重。"""
    out: List[List[float]] = []
    for c in coords:
        if not out or c != out[-1]:
            out.append(c)
    return out


def _entry_geometry(v: Violation, waypoint_coords: List[List[float]]) -> Dict[str, Any]:
    """entry 违规的 LineString：进入点到离开点之间的全部跨段航迹顶点。"""
    if v.segment_start == v.segment_end:
        coords = [_coord(v.entry_position), _coord(v.exit_position)]
    else:
        coords = [_coord(v.entry_position)]
        # segment_start 与 segment_end 之间的航点下标
        coords.extend(waypoint_coords[v.segment_start + 1:v.segment_end + 1])
        coords.append(_coord(v.exit_position))
    coords = _dedupe_consecutive(coords)
    # 理论上 entry 区间为正长度；防御性退化为点
    if len(coords) == 1:
        return {"type": "Point", "coordinates": coords[0]}
    return {"type": "LineString", "coordinates": coords}


def _graze_geometry(v: Violation) -> Dict[str, Any]:
    """graze 违规：重合为 Point，否则为进入点到离开点的 LineString。"""
    entry, exit_ = _coord(v.entry_position), _coord(v.exit_position)
    if entry == exit_:
        return {"type": "Point", "coordinates": entry}
    return {"type": "LineString", "coordinates": [entry, exit_]}


def _feature(v: Violation, waypoint_coords: List[List[float]]) -> Dict[str, Any]:
    data = v.model_dump(mode="json")  # datetime 按 ISO 8601（UTC 输出为 Z）序列化
    if v.kind == "graze":
        geometry = _graze_geometry(v)
    else:
        geometry = _entry_geometry(v, waypoint_coords)
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "zone_id": data["zone_id"],
            "kind": data["kind"],
            "entry_time": data["entry_time"],
            "exit_time": data["exit_time"],
            "segment_start": data["segment_start"],
            "segment_end": data["segment_end"],
        },
    }


def violations_to_geojson(
    violations: List[Violation],
    waypoint_coords: List[List[float]] | None = None,
) -> Dict[str, Any]:
    """把违规列表包装成 GeoJSON FeatureCollection。

    ``waypoint_coords`` 为全部航点的 ``[lon, lat, alt]`` 坐标，
    entry 的 LineString 借此包含跨段途经的航迹顶点；缺省时只取进入/离开点。
    """
    waypoint_coords = waypoint_coords or []
    return {
        "type": "FeatureCollection",
        "features": [_feature(v, waypoint_coords) for v in violations],
    }
