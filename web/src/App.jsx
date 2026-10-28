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
              pathOptions={{ color: "#2563eb", fillColor: "#60a5fa" }}
            >
              <Popup>
                {facility.name || facility.type || facility._id}
              </Popup>
            </Circle>
          );
        })}

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
              pathOptions={{ color: "#dc2626", fillColor: "#f87171" }}
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