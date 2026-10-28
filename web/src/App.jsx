import { useEffect, useState } from "react";
import {
  Circle,
  MapContainer,
  Polygon,
  Polyline,
  TileLayer,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";

const API = "http://127.0.0.1:8000";

function ClickCatcher({ onPick }) {
  useMapEvents({
    click(event) {
      onPick(event.latlng.lng, event.latlng.lat);
    },
  });
  return null;
}

function toLatLngs(polygon) {
  if (!polygon || polygon.type !== "Polygon" || !polygon.coordinates?.[0]) {
    return null;
  }
  return polygon.coordinates[0].map(([lon, lat]) => [lat, lon]);
}

async function request(path, options) {
  const response = await fetch(`${API}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item.msg).join("；")
        : `请求失败 ${response.status}`;
    throw new Error(message);
  }
  return data;
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [buildings, setBuildings] = useState([]);
  const [mode, setMode] = useState("nearby");
  const [lon, setLon] = useState("116.312");
  const [lat, setLat] = useState("39.905");
  const [facilityType, setFacilityType] = useState("water_dispenser");
  const [status, setStatus] = useState("disabled");
  const [facilityId, setFacilityId] = useState("facility_000001");
  const [bikeId, setBikeId] = useState("bike_0001");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState([]);
  const [facilities, setFacilities] = useState([]);
  const [bikes, setBikes] = useState([]);
  const [heatmap, setHeatmap] = useState([]);
  const [highlight, setHighlight] = useState(null);
  const [queryPolygon, setQueryPolygon] = useState(null);
  const [track, setTrack] = useState([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [metaData, buildingData] = await Promise.all([
          request("/meta"),
          request("/buildings?limit=200&view=map"),
        ]);
        if (cancelled) return;
        setMeta(metaData);
        setBuildings(buildingData.items || []);
        setLon(String(metaData.center.lon));
        setLat(String(metaData.center.lat));
        setQueryPolygon(metaData.sample_polygon);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const types = meta?.facility_types || {
    water_dispenser: "饮水机",
    restroom: "卫生间",
    study_seat: "自习座位",
    charging_station: "充电桩",
    printing_point: "打印点",
    parcel_locker: "快递柜",
  };

  async function runQuery() {
    setLoading(true);
    setError("");
    const longitude = Number(lon);
    const latitude = Number(lat);
    try {
      if (mode === "nearby") {
        const data = await request(
          `/facilities/nearby?longitude=${longitude}&latitude=${latitude}&radius_m=500&facility_type=${facilityType}&limit=10`,
        );
        setFacilities(data.items || []);
        setSummary(
          (data.items || []).map(
            (item) =>
              `${types[item.type] || item.type} ${item._id}  ${item.distance_m} 米（精度 ${item.accuracy_meters} 米，${item.coordinate_accuracy}）`,
          ),
        );
      } else if (mode === "within") {
        const data = await request("/facilities/within", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            polygon: meta.sample_polygon,
            facility_type: facilityType,
            page: Number(page),
            page_size: 20,
          }),
        });
        setFacilities(data.items || []);
        setQueryPolygon(meta.sample_polygon);
        setSummary([
          `第 ${data.page}/${data.total_pages} 页，共 ${data.total} 条，本页 ${data.count} 条，${data.elapsed_ms} ms`,
          ...(data.items || []).map((item) => `${item._id}  ${types[item.type] || item.type}  ${item.status}`),
        ]);
      } else if (mode === "contains") {
        const data = await request(`/buildings/contains?lon=${longitude}&lat=${latitude}`);
        const hit = data.items?.[0];
        setHighlight(hit?.boundary || null);
        setSummary(
          data.count
            ? data.items.map((item) => `${item.name || item._id}（${item._id}）`)
            : ["这个点不在任何楼里"],
        );
      } else if (mode === "coverage") {
        const data = await request("/coverage");
        const lines = data.items.slice(0, 12).map(
          (item) => `${item.name}：${item.category_count} 类 / ${item.total} 个`,
        );
        setSummary([
          `${data.building_count} 栋楼统计完成，${data.elapsed_ms} ms。下面是前 12 栋。`,
          ...lines,
        ]);
      } else if (mode === "heatmap") {
        const data = await request("/bikes/heatmap?hours=1");
        setHeatmap(data.items || []);
        setSummary([
          `${data.cell_count} 个 50 米格子，窗口内 ${data.report_count} 次上报，${data.elapsed_ms} ms`,
          data.grid_reason,
        ]);
      } else if (mode === "anomaly") {
        const data = await request("/bikes/anomalies?hours=2");
        setSummary(
          data.count
            ? data.items.slice(0, 12).map(
                (item) => `${item.bike_id}  ${item.distance_m} 米  ${item.implied_speed_kmh} km/h`,
              )
            : ["最近 2 小时没有跳变"],
        );
      } else if (mode === "status") {
        const data = await request(`/facilities/${encodeURIComponent(facilityId)}/status`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
        setSummary([
          `${facilityId} 已改为 ${data.fresh_read?.status}，耗时 ${data.elapsed_ms} ms`,
          "新连接读到的状态和写入结果一致。",
        ]);
      } else if (mode === "bikes") {
        const data = await request(
          `/bikes/nearby?longitude=${longitude}&latitude=${latitude}&radius_m=800&limit=30`,
        );
        setBikes(data.items || []);
        setSummary(
          (data.items || []).slice(0, 10).map(
            (item) => `${item.bike_id}  ${item.distance_m} 米  ${item.status}`,
          ),
        );
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadTrack() {
    setError("");
    try {
      const data = await request(`/bikes/${encodeURIComponent(bikeId)}/tracks?hours=1&limit=2000`);
      setTrack(data.items || []);
    } catch (err) {
      setError(err.message);
    }
  }

  const dataset = meta?.dataset || {};
  const maxHeat = Math.max(1, ...heatmap.map((cell) => cell.report_count || 0));

  return (
    <main className="app">
      <section className="panel">
        <h1>校园设施查询</h1>
        <p className="muted">点地图选坐标。车辆历史不进附近查询，附近的车只看最新位置。</p>
        <div className="meta">
          <span>楼宇 {dataset.building_count ?? "-"}</span>
          <span>设施 {dataset.facility_count ?? "-"}</span>
          <span>单车 {dataset.bike_count ?? "-"}</span>
          <span>上报 {dataset.report_count ?? "-"}</span>
        </div>
        <label>
          功能
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="nearby">附近 10 个设施</option>
            <option value="within">区域检索（分页）</option>
            <option value="contains">点在哪栋楼</option>
            <option value="coverage">每栋楼 300 米覆盖</option>
            <option value="heatmap">单车热力</option>
            <option value="anomaly">两小时跳变</option>
            <option value="status">修改设施状态</option>
            <option value="bikes">附近单车</option>
          </select>
        </label>
        <div className="inline">
          <label>
            经度
            <input value={lon} onChange={(event) => setLon(event.target.value)} />
          </label>
          <label>
            纬度
            <input value={lat} onChange={(event) => setLat(event.target.value)} />
          </label>
        </div>
        {(mode === "nearby" || mode === "within") && (
          <label>
            设施类型
            <select value={facilityType} onChange={(event) => setFacilityType(event.target.value)}>
              {Object.entries(types).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </label>
        )}
        {mode === "within" && (
          <label>
            页码
            <input value={page} onChange={(event) => setPage(event.target.value)} />
          </label>
        )}
        {mode === "status" && (
          <>
            <label>
              设施编号
              <input value={facilityId} onChange={(event) => setFacilityId(event.target.value)} />
            </label>
            <label>
              新状态
              <select value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="active">可用</option>
                <option value="disabled">停用</option>
                <option value="occupied">占用</option>
              </select>
            </label>
          </>
        )}
        {mode === "bikes" && (
          <div className="inline">
            <label>
              轨迹车辆
              <input value={bikeId} onChange={(event) => setBikeId(event.target.value)} />
            </label>
            <button className="secondary" type="button" onClick={loadTrack}>最近 1 小时轨迹</button>
          </div>
        )}
        <button type="button" onClick={runQuery} disabled={loading}>
          {loading ? "查询中..." : "查询"}
        </button>
        {error && <p className="error">{error}</p>}
        <ul className="result">
          {summary.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>
      <div className="map-wrap">
        <MapContainer center={[39.905, 116.312]} zoom={15} style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution="&copy; OpenStreetMap"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <ClickCatcher onPick={(nextLon, nextLat) => {
            setLon(nextLon.toFixed(6));
            setLat(nextLat.toFixed(6));
          }} />
          {buildings.map((building) => {
            const positions = toLatLngs(building.boundary);
            if (!positions) return null;
            return (
              <Polygon
                key={building._id}
                positions={positions}
                pathOptions={{ color: "#1d4e89", weight: 1, fillOpacity: 0.15 }}
              />
            );
          })}
          {queryPolygon && mode === "within" && (
            <Polygon
              positions={toLatLngs(queryPolygon)}
              pathOptions={{ color: "#0f766e", weight: 2, fillOpacity: 0.05 }}
            />
          )}
          {highlight && (
            <Polygon
              positions={toLatLngs(highlight)}
              pathOptions={{ color: "#b45309", weight: 3, fillOpacity: 0.25 }}
            />
          )}
          {facilities.map((facility) => {
            const point = facility.location?.coordinates;
            if (!point) return null;
            return (
              <Circle
                key={facility._id}
                center={[point[1], point[0]]}
                radius={10}
                pathOptions={{ color: "#0f766e", fillColor: "#14b8a6", fillOpacity: 0.8 }}
              />
            );
          })}
          {bikes.map((bike) => {
            const point = bike.location?.coordinates;
            if (!point) return null;
            const zombie = bike.status === "zombie";
            return (
              <Circle
                key={bike.bike_id}
                center={[point[1], point[0]]}
                radius={zombie ? 8 : 12}
                pathOptions={{
                  color: zombie ? "#57534e" : "#b45309",
                  fillColor: zombie ? "#a8a29e" : "#fdba74",
                  fillOpacity: 0.85,
                }}
              />
            );
          })}
          {heatmap.map((cell) => {
            const point = cell.center?.coordinates;
            if (!point) return null;
            return (
              <Circle
                key={cell.grid_id}
                center={[point[1], point[0]]}
                radius={25}
                pathOptions={{
                  color: "#dc2626",
                  weight: 0,
                  fillColor: "#dc2626",
                  fillOpacity: 0.15 + 0.6 * (cell.report_count / maxHeat),
                }}
              />
            );
          })}
          {track.length > 1 && (
            <Polyline
              positions={track
                .filter((item) => item.location?.coordinates)
                .map((item) => [item.location.coordinates[1], item.location.coordinates[0]])}
              pathOptions={{ color: "#7f1d1d", weight: 3 }}
            />
          )}
        </MapContainer>
      </div>
    </main>
  );
}
