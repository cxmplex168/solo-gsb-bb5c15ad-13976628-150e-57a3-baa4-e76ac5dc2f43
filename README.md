# 无人机航迹禁飞区审计服务

基于 FastAPI + Shapely 的航迹合规审计服务。输入按时间排序的航点序列与带生效时段、高度范围的 GeoJSON 禁飞区，输出按时间排序的违规区间。

## 快速启动（单条命令，端口 8000）

```bash
docker compose up --build
```

服务启动后监听 **8000** 端口：

- 交互式文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

不使用 Docker 时：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
pip install -r requirements-dev.txt
pytest
```

## 接口

### POST /audit

**请求体**

```json
{
  "waypoints": [
    {"lat": 39.905, "lon": 116.29, "alt": 50, "time": "2026-09-22T10:00:00Z"},
    {"lat": 39.905, "lon": 116.34, "alt": 50, "time": "2026-09-22T10:30:00Z"}
  ],
  "zones": [
    {
      "id": "nfz-1",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[116.30, 39.90], [116.32, 39.90], [116.32, 39.92], [116.30, 39.92], [116.30, 39.90]]]
      },
      "active_from": "2026-09-22T10:00:00Z",
      "active_to": "2026-09-22T11:00:00Z",
      "min_alt": 0,
      "max_alt": 120
    }
  ]
}
```

- `waypoints`：至少 2 个，必须按 `time` **严格递增**；`time` 为 ISO 8601（无时区按 UTC 处理）。
- `zones[].geometry`：GeoJSON `Polygon` 或 `MultiPolygon`（坐标顺序为 `[经度, 纬度]`）。
- `min_alt` / `max_alt`：高度范围（含端点），缺省表示不限制。

**响应 200**

```json
{
  "violation_count": 1,
  "violations": [
    {
      "zone_id": "nfz-1",
      "kind": "entry",
      "entry_time": "2026-09-22T10:06:00Z",
      "exit_time": "2026-09-22T10:18:00Z",
      "entry_position": {"lat": 39.905, "lon": 116.30, "alt": 50.0},
      "exit_position": {"lat": 39.905, "lon": 116.32, "alt": 50.0},
      "segment_start": 0,
      "segment_end": 0
    }
  ]
}
```

- `violations` 按 `entry_time` 升序排列。
- `kind = "entry"`：真正进入区域内部；`kind = "graze"`：擦边接触（掠过顶点、沿边界滑行，或仅在边界时刻触碰）。graze 的进入/离开位置可能相同。
- 进入/离开的时间与位置（含高度）均按航段线性插值求得。

**响应 422**（请求无法审计）

- 航点未按时间严格递增（含时间相同）；
- 多边形无效（自相交、面积为零、类型不是 Polygon/MultiPolygon、GeoJSON 无法解析）；
- `active_to` 不晚于 `active_from`、`max_alt` 小于 `min_alt`、航点少于 2 个等参数错误。

## 判定规则

对每一条**相邻航段**（而非仅航点）逐一审计。航段上任意点用分数 f ∈ [0,1] 表示，位置、时间、高度均为 f 的线性函数，因此三个条件各自对应一个 f 区间：

1. **平面命中**：Shapely 求线段与多边形的交，得到进入区间（交为线）或切点（交为点）；
2. **时段命中**：解 `t0 + f·Δt ∈ [active_from, active_to]`；
3. **高度命中**：解 `alt0 + f·Δalt ∈ [min_alt, max_alt]`。

三者交集非空才判定违规——即平面、时段、高度必须**同时**命中。交集为正长度且经过多边形内部记为 `entry`；退化为点或仅沿边界滑行记为 `graze`。跨航段首尾相接的命中会合并为一条连续违规区间（例如航迹在区内途经多个航点只产生一条记录）。

## 项目结构

```
app/
  main.py    # FastAPI 入口与路由
  models.py  # 请求/响应模型与参数校验
  audit.py   # 核心审计算法（平面求交 + f 域三窗口求交 + 区间合并）
tests/
  test_audit.py
Dockerfile
docker-compose.yml
```
