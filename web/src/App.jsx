import { useEffect, useState } from "react";
import {
  Circle,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  Polygon,
  Polyline,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";

const API_BASE = "http://127.0.0.1:8000";
const CENTER = [39.9005, 116.3006];

// 将 GeoJSON Polygon 坐标转换为 Leaflet 所需的 [纬度, 经度]
function geoJsonPolygonToLeaflet(polygon) {
  return polygon.coordinates[0].map(([longitude, latitude]) => [
    latitude,
    longitude,
  ]);
}

function App() {
  const [buildings, setBuildings] = useState([]);
  const [facilities, setFacilities] = useState([]);
  const [vehicles, setVehicles] = useState([]);

  // 附近车辆刷新及历史轨迹查询状态
  const [minutes, setMinutes] = useState(5);
  const [selectedVehicle, setSelectedVehicle] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [tracks, setTracks] = useState([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const [trackLoading, setTrackLoading] = useState(false);

  // 加载楼宇和周边设施
  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      try {
        const [buildingResponse, facilityResponse] = await Promise.all([
          fetch(`${API_BASE}/buildings?limit=200`),
          fetch(
            `${API_BASE}/facilities/nearby?longitude=116.3006&latitude=39.9005&radius_m=5000&limit=1000`
          ),
        ]);

        if (!buildingResponse.ok || !facilityResponse.ok) {
          throw new Error("楼宇或设施数据请求失败，请检查后端 API");
        }

        const buildingData = await buildingResponse.json();
        const facilityData = await facilityResponse.json();

        if (!cancelled) {
          setBuildings(buildingData.items || []);
          setFacilities(facilityData.items || []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "地图数据加载失败");
        }
      }
    }

    loadData();

    return () => {
      cancelled = true;
    };
  }, []);

  // 附近车辆请求：首次加载，并每 15 秒刷新一次
  useEffect(() => {
    let cancelled = false;

    async function loadVehicles() {
      try {
        const params = new URLSearchParams({
          longitude: "116.3006",
          latitude: "39.9005",
          radius_m: "5000",
          minutes: String(minutes),
        });

        const response = await fetch(
          `${API_BASE}/vehicles/nearby?${params}`
        );

        if (!response.ok) {
          throw new Error(`车辆请求失败：HTTP ${response.status}`);
        }

        const data = await response.json();

        if (!cancelled) {
          setVehicles(data.items || []);
          setError("");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "车辆数据加载失败");
        }
      }
    }

    loadVehicles();

    const timer = window.setInterval(loadVehicles, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [minutes, refreshKey]);

  // 查询指定车辆的历史轨迹
  async function loadTracks() {
    if (!selectedVehicle || !startTime || !endTime) {
      setError("请选择车辆，并填写开始时间和结束时间");
      return;
    }

    const start = new Date(startTime);
    const end = new Date(endTime);

    if (
      Number.isNaN(start.getTime()) ||
      Number.isNaN(end.getTime())
    ) {
      setError("请输入有效的时间范围");
      return;
    }

    if (start >= end) {
      setError("开始时间必须早于结束时间");
      return;
    }

    setTrackLoading(true);
    setError("");

    try {
      const params = new URLSearchParams({
        start_time: start.toISOString(),
        end_time: end.toISOString(),
      });

      const response = await fetch(
        `${API_BASE}/vehicles/${encodeURIComponent(
          selectedVehicle
        )}/tracks?${params}`
      );

      if (!response.ok) {
        throw new Error(`轨迹请求失败：HTTP ${response.status}`);
      }

      const data = await response.json();
      setTracks(data.items || []);
    } catch (err) {
      setTracks([]);
      setError(err.message || "历史轨迹加载失败");
    } finally {
      setTrackLoading(false);
    }
  }

  return (
    <main
      style={{
        height: "100vh",
        width: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* 顶部控制区域 */}
      <section
        style={{
          padding: "12px",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "12px",
          background: "#f8fafc",
          borderBottom: "1px solid #e5e7eb",
          zIndex: 1000,
        }}
      >
        {/* 车辆刷新窗口 */}
        <label>
          最近{" "}
          <select
            value={minutes}
            onChange={(event) =>
              setMinutes(Number(event.target.value))
            }
          >
            <option value={1}>1 分钟</option>
            <option value={5}>5 分钟</option>
            <option value={15}>15 分钟</option>
            <option value={30}>30 分钟</option>
          </select>
        </label>

        <button
          type="button"
          onClick={() => setRefreshKey((value) => value + 1)}
        >
          刷新车辆
        </button>

        <span>当前附近车辆：{vehicles.length} 辆</span>

        {/* 选择需要查询轨迹的车辆 */}
        <label>
          轨迹车辆{" "}
          <select
            value={selectedVehicle}
            onChange={(event) => {
              setSelectedVehicle(event.target.value);
              setTracks([]);
            }}
          >
            <option value="">请选择车辆</option>
            {vehicles.map((vehicle) => {
              const vehicleId = vehicle.vehicle_id;

              if (vehicleId == null) {
                return null;
              }

              return (
                <option key={vehicle._id || vehicleId} value={vehicleId}>
                  {vehicleId}
                </option>
              );
            })}
          </select>
        </label>

        {/* 历史轨迹时间范围 */}
        <label>
          开始时间{" "}
          <input
            type="datetime-local"
            value={startTime}
            onChange={(event) => setStartTime(event.target.value)}
          />
        </label>

        <label>
          结束时间{" "}
          <input
            type="datetime-local"
            value={endTime}
            onChange={(event) => setEndTime(event.target.value)}
          />
        </label>

        <button
          type="button"
          onClick={loadTracks}
          disabled={trackLoading}
        >
          {trackLoading ? "查询中..." : "查询历史轨迹"}
        </button>

        <button
          type="button"
          onClick={() => setTracks([])}
        >
          清除轨迹
        </button>
      </section>

      {/* 错误信息 */}
      {error && (
        <p
          role="alert"
          style={{
            margin: 0,
            padding: "8px 12px",
            color: "#b91c1c",
            background: "#fef2f2",
          }}
        >
          {error}
        </p>
      )}

      {/* 地图 */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <MapContainer
          center={CENTER}
          zoom={16}
          style={{ height: "100%", width: "100%" }}
        >
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {/* 楼宇 300 米覆盖区域 */}
          {buildings.map((building) => {
            const polygon = building.coverage_300m;

            if (
              !polygon ||
              polygon.type !== "Polygon" ||
              !Array.isArray(polygon.coordinates) ||
              !Array.isArray(polygon.coordinates[0]) ||
              polygon.coordinates[0].length < 4
            ) {
              return null;
            }

            return (
              <Polygon
                key={`${building._id}-coverage`}
                positions={geoJsonPolygonToLeaflet(polygon)}
                pathOptions={{
                  color: "#f59e0b",
                  weight: 1,
                  fillColor: "#fbbf24",
                  fillOpacity: 0.12,
                }}
              >
                <Popup>
                  <strong>{building.name || building._id}</strong>
                  <br />
                  楼宇覆盖范围：300 米
                </Popup>
              </Polygon>
            );
          })}

          {/* 楼宇位置标记 */}
          {buildings.map((building) => {
            const point = building.location?.coordinates;

            if (!point || point.length < 2) {
              return null;
            }

            return (
              <Marker
                key={building._id}
                position={[point[1], point[0]]}
              >
                <Popup>
                  <strong>{building.name || building._id}</strong>
                </Popup>
              </Marker>
            );
          })}

          {/* 周边设施 */}
          {facilities.map((facility) => {
            const point = facility.location?.coordinates;

            if (!point || point.length < 2) {
              return null;
            }

            return (
              <Circle
                key={facility._id}
                center={[point[1], point[0]]}
                radius={8}
                pathOptions={{
                  color: "#2563eb",
                  fillColor: "#60a5fa",
                }}
              >
                <Popup>
                  {facility.name || facility.type || facility._id}
                </Popup>
              </Circle>
            );
          })}

          {/* 周边车辆 */}
          {vehicles.map((vehicle) => {
            const point = vehicle.location?.coordinates;

            if (!point || point.length < 2) {
              return null;
            }

            return (
              <Circle
                key={vehicle._id || vehicle.vehicle_id}
                center={[point[1], point[0]]}
                radius={12}
                pathOptions={{
                  color: "#dc2626",
                  fillColor: "#f87171",
                }}
              >
                <Popup>
                  <strong>{vehicle.vehicle_id}</strong>
                  <br />
                  状态：{vehicle.status || "未知"}
                  <br />
                  速度：{vehicle.speed_kmh ?? "-"} km/h
                </Popup>
              </Circle>
            );
          })}

          {/* 历史车辆轨迹：GeoJSON [经度, 纬度] 转为 [纬度, 经度] */}
          {tracks.length > 0 && (
            <Polyline
              positions={tracks
                .filter(
                  (track) =>
                    Array.isArray(track.location?.coordinates) &&
                    track.location.coordinates.length >= 2
                )
                .map((track) => {
                  const [longitude, latitude] =
                    track.location.coordinates;

                  return [latitude, longitude];
                })}
              pathOptions={{
                color: "#d94841",
                weight: 3,
              }}
            >
              <Popup>车辆历史轨迹</Popup>
            </Polyline>
          )}
        </MapContainer>
      </div>
    </main>
  );
}

export default App;
