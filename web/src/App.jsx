
import { useEffect, useState } from "react";
import {
  Circle,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  Polygon,
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

  useEffect(() => {
    async function loadData() {
      const [buildingResponse, facilityResponse, vehicleResponse] =
        await Promise.all([
          fetch(`${API_BASE}/buildings?limit=200`),
          fetch(
            `${API_BASE}/facilities/nearby?longitude=116.3006&latitude=39.9005&radius_m=5000&limit=1000`
          ),
          fetch(
            `${API_BASE}/vehicles/nearby?longitude=116.3006&latitude=39.9005&radius_m=5000&minutes=30`
          ),
        ]);

      // 检查 HTTP 请求是否成功
      if (
        !buildingResponse.ok ||
        !facilityResponse.ok ||
        !vehicleResponse.ok
      ) {
        throw new Error("地图数据请求失败，请检查后端 API");
      }

      const buildingData = await buildingResponse.json();
      const facilityData = await facilityResponse.json();
      const vehicleData = await vehicleResponse.json();

      setBuildings(buildingData.items || []);
      setFacilities(facilityData.items || []);
      setVehicles(vehicleData.items || []);
    }

    loadData().catch(console.error);
  }, []);

  return (
    <main style={{ height: "100vh" }}>
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
              key={vehicle._id}
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
      </MapContainer>
    </main>
  );
}

export default App;
