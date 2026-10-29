import { useEffect, useState } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Polygon,
  Polyline,
  Popup,
  TileLayer,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";

const API = "http://127.0.0.1:8000";

const STATUS_LABELS = {
  active: "可用",
  disabled: "停用",
  occupied: "占用",
  zombie: "僵尸车",
};

function ClickCatcher({ mode, onPick, onAddVertex }) {
  useMapEvents({
    click(event) {
      const longitude = event.latlng.lng;
      const latitude = event.latlng.lat;
      if (mode === "within") onAddVertex(longitude, latitude);
      else onPick(longitude, latitude);
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

function toLocalInput(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function distanceMeters(lon1, lat1, lon2, lat2) {
  const radius = 6371008.8;
  const toRad = (degree) => (degree * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(a)));
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
  const [heatStart, setHeatStart] = useState("");
  const [heatEnd, setHeatEnd] = useState("");
  const [draft, setDraft] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState([]);
  const [facilities, setFacilities] = useState([]);
  const [bikes, setBikes] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [heatmap, setHeatmap] = useState([]);
  const [highlight, setHighlight] = useState(null);
  const [coverageArea, setCoverageArea] = useState(null);
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
        const end = metaData.dataset?.simulation_end;
        if (end) {
          const endDate = new Date(end);
          setHeatEnd(toLocalInput(endDate));
          setHeatStart(toLocalInput(endDate.getTime() - 60 * 60 * 1000));
        }
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

  function statusLabel(value) {
    return STATUS_LABELS[value] || value || "未知";
  }

  function switchMode(next) {
    setMode(next);
    if (next !== "heatmap") setHeatmap([]);
  }

  async function loadTrack(id = bikeId) {
    const data = await request(
      `/bikes/${encodeURIComponent(id)}/tracks?hours=1&limit=2000`,
    );
    setTrack(data.items || []);
    return data;
  }

  async function fetchWithin(polygon) {
    const pageSize = 200;
    let page = 1;
    let total = 0;
    const items = [];
    let pages = 0;
    do {
      const data = await request("/facilities/within", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          polygon,
          facility_type: facilityType,
          page,
          page_size: pageSize,
        }),
      });
      total = data.total;
      pages = data.total_pages;
      items.push(...(data.items || []));
      page += 1;
    } while (items.length < total && page <= pages);
    return { items, total, pages };
  }

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
              `${item.name || item._id}，${types[item.type] || item.type}，${statusLabel(item.status)}，${item.distance_m} 米`,
          ),
        );
      } else if (mode === "within") {
        if (draft.length < 3) {
          throw new Error("请在地图上至少点 3 个点，再闭合查询");
        }
        const ring = draft.map(([pointLon, pointLat]) => [pointLon, pointLat]);
        ring.push(ring[0]);
        const polygon = { type: "Polygon", coordinates: [ring] };
        const data = await fetchWithin(polygon);
        setQueryPolygon(polygon);
        setFacilities(data.items);
        setSummary([
          `范围内共 ${data.total} 个设施，已按每页 200 条自动载入 ${data.pages} 页`,
          ...data.items.slice(0, 12).map(
            (item) =>
              `${item.name || item._id}，${types[item.type] || item.type}，${statusLabel(item.status)}`,
          ),
        ]);
      } else if (mode === "contains") {
        const data = await request(`/buildings/contains?lon=${longitude}&lat=${latitude}`);
        const hit = data.items?.[0];
        setHighlight(hit?.boundary || null);
        setCoverageArea(null);
        setSummary(
          data.count
            ? data.items.map((item) => item.name || item._id)
            : ["这个点不在任何楼里"],
        );
      } else if (mode === "coverage") {
        const found = await request(`/buildings/contains?lon=${longitude}&lat=${latitude}`);
        const hit = found.items?.[0];
        if (!hit) {
          setHighlight(null);
          setCoverageArea(null);
          setSummary(["这个点不在任何楼里"]);
        } else {
          const data = await request(`/buildings/${encodeURIComponent(hit._id)}/coverage`);
          setHighlight(hit.boundary || null);
          setCoverageArea(data.coverage_300m || null);
          const counts = data.facility_count_by_type || {};
          setSummary([
            `${data.building_name || hit.name}：${data.category_count} 类，共 ${data.facility_count} 个`,
            ...Object.entries(counts).map(
              ([key, count]) => `${types[key] || key} ${count} 个`,
            ),
          ]);
        }
      } else if (mode === "heatmap") {
        if (!heatStart || !heatEnd) {
          throw new Error("请填写热力的开始和结束时间");
        }
        const start = new Date(heatStart).toISOString();
        const end = new Date(heatEnd).toISOString();
        const data = await request(
          `/bikes/heatmap?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
        );
        setHeatmap(data.items || []);
        setSummary([
          `${data.grid_size_m} 米网格，${data.cell_count} 个格子，窗口内 ${data.report_count} 次上报`,
          data.grid_reason,
        ]);
      } else if (mode === "anomaly") {
        const data = await request("/bikes/anomalies?hours=2&limit=500");
        const points = (data.items || [])
          .map((item) => {
            const point = item.to_location?.coordinates;
            if (!point) return null;
            return {
              bike_id: item.bike_id,
              location: item.to_location,
              distance_m: item.distance_m,
              status: "jump",
            };
          })
          .filter(Boolean);
        setAnomalies(points);
        setSummary(
          points.length
            ? points.slice(0, 12).map(
                (item) => `${item.bike_id}，跳变 ${item.distance_m} 米`,
              )
            : ["最近 2 小时没有位置跳变"],
        );
      } else if (mode === "status") {
        const data = await request(`/facilities/${encodeURIComponent(facilityId)}/status`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
        const item = data.fresh_read || data.item || {};
        const point = item.location?.coordinates;
        const distance = point
          ? distanceMeters(longitude, latitude, point[0], point[1]).toFixed(1)
          : null;
        setFacilities(point ? [item] : []);
        setSummary([
          `${item.name || facilityId}，${types[item.type] || item.type || "未知类型"}，${statusLabel(item.status)}，距当前位置 ${distance ?? "未知"} 米`,
        ]);
      } else if (mode === "bikes") {
        const data = await request(
          `/bikes/nearby?longitude=${longitude}&latitude=${latitude}&radius_m=800&limit=30`,
        );
        setBikes(data.items || []);
        setTrack([]);
        setSummary(
          (data.items || []).map(
            (item) => `${item.bike_id}，${statusLabel(item.status)}，${item.distance_m} 米`,
          ),
        );
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const dataset = meta?.dataset || {};
  const maxHeat = Math.max(1, ...heatmap.map((cell) => cell.report_count || 0));
  const draftPolygon = draft.length >= 3
    ? {
        type: "Polygon",
        coordinates: [[...draft, draft[0]]],
      }
    : null;

  return (
    <main className="app">
      <section className="panel">
        <h1>校园设施查询</h1>
        <p className="muted">
          {mode === "within"
            ? "区域检索：在地图上依次点选范围，至少 3 个点后闭合。结果会自动按页载入。"
            : "点地图设置当前位置。热力只在「单车热力」下显示，换功能后会从地图上清掉。"}
        </p>
        <div className="meta">
          <span>楼宇 {dataset.building_count ?? "-"}</span>
          <span>设施 {dataset.facility_count ?? "-"}</span>
          <span>单车 {dataset.bike_count ?? "-"}</span>
          <span>上报 {dataset.report_count ?? "-"}</span>
        </div>
        <label>
          功能
          <select value={mode} onChange={(event) => switchMode(event.target.value)}>
            <option value="nearby">附近查找</option>
            <option value="within">区域检索</option>
            <option value="contains">所在楼宇名</option>
            <option value="coverage">覆盖分析</option>
            <option value="heatmap">单车热力</option>
            <option value="anomaly">车辆异常识别</option>
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
          <div className="actions">
            <span>已选 {draft.length} 个顶点</span>
            <button className="secondary" type="button" onClick={() => setDraft((points) => points.slice(0, -1))}>
              撤销一点
            </button>
            <button className="secondary" type="button" onClick={() => { setDraft([]); setQueryPolygon(null); }}>
              清除范围
            </button>
          </div>
        )}
        {mode === "heatmap" && (
          <>
            <label>
              开始时间
              <input type="datetime-local" value={heatStart} onChange={(event) => setHeatStart(event.target.value)} />
            </label>
            <label>
              结束时间
              <input type="datetime-local" value={heatEnd} onChange={(event) => setHeatEnd(event.target.value)} />
            </label>
          </>
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
            <button
              className="secondary"
              type="button"
              onClick={() => loadTrack().catch((err) => setError(err.message))}
            >
              最近 1 小时轨迹
            </button>
          </div>
        )}
        <button type="button" onClick={runQuery} disabled={loading}>
          {loading ? "查询中..." : mode === "within" ? "闭合查询" : "查询"}
        </button>
        {error && <p className="error">{error}</p>}
        <ul className="result">
          {summary.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}
        </ul>
      </section>
      <div className="map-wrap">
        <MapContainer center={[39.905, 116.312]} zoom={16} style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution="&copy; OpenStreetMap"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <ClickCatcher
            mode={mode}
            onPick={(nextLon, nextLat) => {
              setLon(nextLon.toFixed(6));
              setLat(nextLat.toFixed(6));
            }}
            onAddVertex={(nextLon, nextLat) => {
              setDraft((points) => [...points, [Number(nextLon.toFixed(6)), Number(nextLat.toFixed(6))]]);
            }}
          />
          {buildings.map((building) => {
            const positions = toLatLngs(building.boundary);
            if (!positions) return null;
            return (
              <Polygon
                key={building._id}
                positions={positions}
                pathOptions={{ color: "#1d4e89", weight: 1, fillOpacity: 0.12 }}
              />
            );
          })}
          {mode === "within" && (queryPolygon || draftPolygon) && (
            <Polygon
              positions={toLatLngs(queryPolygon || draftPolygon)}
              pathOptions={{ color: "#0f766e", weight: 2, fillOpacity: 0.08 }}
            />
          )}
          {(mode === "contains" || mode === "coverage") && highlight && (
            <Polygon
              positions={toLatLngs(highlight)}
              pathOptions={{ color: "#b45309", weight: 3, fillOpacity: 0.25 }}
            />
          )}
          {mode === "coverage" && coverageArea && (
            <Polygon
              positions={toLatLngs(coverageArea)}
              pathOptions={{ color: "#ca8a04", weight: 1, fillOpacity: 0.08 }}
            />
          )}
          {(mode === "nearby" || mode === "within" || mode === "status") && facilities.map((facility) => {
            const point = facility.location?.coordinates;
            if (!point) return null;
            return (
              <CircleMarker
                key={facility._id}
                center={[point[1], point[0]]}
                radius={5}
                pathOptions={{ color: "#0f766e", fillColor: "#14b8a6", fillOpacity: 0.95, weight: 1 }}
              >
                <Popup>
                  {facility.name || facility._id}
                  <br />
                  {types[facility.type] || facility.type}，{statusLabel(facility.status)}
                </Popup>
              </CircleMarker>
            );
          })}
          {mode === "bikes" && bikes.map((bike) => {
            const point = bike.location?.coordinates;
            if (!point) return null;
            return (
              <CircleMarker
                key={bike.bike_id}
                center={[point[1], point[0]]}
                radius={6}
                pathOptions={{ color: "#c2410c", fillColor: "#fdba74", fillOpacity: 0.95, weight: 1 }}
                eventHandlers={{
                  click: () => {
                    setBikeId(bike.bike_id);
                    loadTrack(bike.bike_id).catch((err) => setError(err.message));
                  },
                }}
              >
                <Popup>
                  {bike.bike_id}
                  <br />
                  {statusLabel(bike.status)}，{bike.distance_m} 米
                </Popup>
              </CircleMarker>
            );
          })}
          {mode === "anomaly" && anomalies.map((bike) => {
            const point = bike.location?.coordinates;
            if (!point) return null;
            return (
              <CircleMarker
                key={`${bike.bike_id}-${point[0]}-${point[1]}`}
                center={[point[1], point[0]]}
                radius={6}
                pathOptions={{ color: "#9a3412", fillColor: "#fb923c", fillOpacity: 0.95, weight: 1 }}
                eventHandlers={{
                  click: () => {
                    setBikeId(bike.bike_id);
                    loadTrack(bike.bike_id).catch((err) => setError(err.message));
                  },
                }}
              >
                <Popup>
                  {bike.bike_id}
                  <br />
                  跳变 {bike.distance_m} 米
                </Popup>
              </CircleMarker>
            );
          })}
          {mode === "heatmap" && heatmap.map((cell) => {
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
          {track.length > 1 && (mode === "bikes" || mode === "anomaly") && (
            <Polyline
              positions={track
                .filter((item) => item.location?.coordinates)
                .map((item) => [item.location.coordinates[1], item.location.coordinates[0]])}
              pathOptions={{ color: "#9a3412", weight: 3 }}
            />
          )}
        </MapContainer>
      </div>
    </main>
  );
}
