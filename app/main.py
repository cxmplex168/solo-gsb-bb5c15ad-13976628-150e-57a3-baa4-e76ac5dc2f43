"""FastAPI 应用入口。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .audit import TrackOrderError, ZoneGeometryError, audit_track
from .geojson import violations_to_geojson
from .models import AuditRequest, AuditResponse

app = FastAPI(
    title="无人机航迹禁飞区审计",
    version="1.1.0",
    description=(
        "按航段（而非仅航点）审计无人机航迹与禁飞区的冲突："
        "平面、生效时段、高度范围三者同时命中才判定违规，"
        "并区分擦边接触（graze）与真正进入（entry）。"
        "/audit/geojson 以 GeoJSON FeatureCollection 返回同样的判定结果。"
    ),
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _run_audit(req: AuditRequest):
    """两个端点共用同一份请求体校验与判定逻辑。"""
    try:
        return audit_track(req.waypoints, req.zones)
    except (TrackOrderError, ZoneGeometryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest) -> AuditResponse:
    violations = _run_audit(req)
    return AuditResponse(violation_count=len(violations), violations=violations)


@app.post("/audit/geojson")
def audit_geojson(req: AuditRequest) -> dict:
    """与 POST /audit 相同的判定结果，输出为 GeoJSON FeatureCollection。"""
    violations = _run_audit(req)
    waypoint_coords = [[w.lon, w.lat, w.alt] for w in req.waypoints]
    return violations_to_geojson(violations, waypoint_coords)
