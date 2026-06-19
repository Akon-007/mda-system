import asyncio
import json
import math
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from shapely.geometry import Point, Polygon

app = FastAPI()

# --- 1. GEOGRAPHIC PROFILING (GULF OF GUINEA) ---
# Simulating a basic Exclusive Economic Zone (EEZ) boundary box near Lagos/Delta coast
EEZ_POLYGON = Polygon([
    (2.5, 6.3),  # Northwest corner
    (8.5, 6.3),  # Northeast corner
    (8.5, 2.0),  # Southeast corner
    (2.5, 2.0),  # Southwest corner
    (2.5, 6.3)   # Close loop
])

class MDASimulator:
    def __init__(self):
        # Tracking true state of 5 vessels in our sector
        self.vessels = {
            f"MMSI-{100000 + i}": {
                "id": f"MMSI-{100000 + i}",
                "name": f"Cargo_Vessel_{i}",
                "lat": random.uniform(3.5, 5.5),
                "lng": random.uniform(3.0, 7.0),
                "heading": random.uniform(0, 360),
                "speed": random.uniform(5, 18),
                "ais_active": True if i != 3 else False,  # Vessel 3 is running DARK
                "loitering_ticks": 0
            } for i in range(5)
        }

    def update_positions(self):
        """Simulates vessel physics updates and dead reckoning."""
        for vid, v in self.vessels.items():
            # Convert speed (knots) and heading to raw degree offsets
            speed_deg = (v["speed"] * 0.514) / 111000  # meters per second to degrees approx
            rad = math.radians(v["heading"])
            v["lat"] += speed_deg * math.cos(rad)
            v["lng"] += speed_deg * math.sin(rad)
            
            # Keep vessels looping in our sector boundary if they wander too far
            if not (2.0 < v["lat"] < 7.0) or not (2.0 < v["lng"] < 9.0):
                v["heading"] = (v["heading"] + 180) % 360

            # Intentional behavior: make vessel 1 loiter (suspicious behavior)
            if vid == "MMSI-100001":
                v["speed"] = 1.2  # Very slow speed
                v["loitering_ticks"] += 1
            else:
                v["loitering_ticks"] = 0

    def process_analytics(self):
        """
        CORRELATION ENGINE:
        Compares simulated radar scans against active AIS transponders to flag anomalies.
        """
        self.update_positions()
        telemetry_payload = []

        # 1. Simulate what a SAR Satellite sees (Absolute physical location of every metal object)
        sar_radar_pings = [{"lat": v["lat"], "lng": v["lng"]} for v in self.vessels.values()]

        # 2. Extract Active AIS Transponder reports
        ais_broadcasts = {vid: v for vid, v in self.vessels.items() if v["ais_active"]}

        # 3. Correlation Loop
        for ping in sar_radar_pings:
            correlated = False
            associated_vessel = None
            anomaly_type = "Clear"
            risk_level = "Low"

            # Check if this radar point matches any active AIS position within a tolerance zone
            for vid, ais in ais_broadcasts.items():
                distance = math.sqrt((ping["lat"] - ais["lat"])**2 + (ping["lng"] - ais["lng"])**2)
                if distance < 0.05:  # Tolerance threshold
                    correlated = True
                    associated_vessel = ais
                    break

            point_geo = Point(ping["lng"], ping["lat"])
            inside_eez = EEZ_POLYGON.contains(point_geo)

            if not correlated:
                # CRITICAL ANOMALY: Radar detects a ship, but no AIS signature exists!
                anomaly_type = "DARK VESSEL DETECTED"
                risk_level = "Critical"
                telemetry_payload.append({
                    "id": "UNKNOWN-TARGET",
                    "name": "🚨 UNREGISTERED DARK TARGET",
                    "lat": ping["lat"],
                    "lng": ping["lng"],
                    "anomaly": anomaly_type,
                    "risk": risk_level,
                    "inside_eez": inside_eez
                })
            else:
                # Evaluate behavior profiles for known, broadcasting tracks
                if associated_vessel["loitering_ticks"] > 5 and inside_eez:
                    anomaly_type = "SUSPICIOUS LOITERING IN EEZ"
                    risk_level = "Medium"
                elif not inside_eez:
                    anomaly_type = "Transit - Outside Territory"
                    risk_level = "Low"
                else:
                    anomaly_type = "Normal Route Operations"
                    risk_level = "Low"

                telemetry_payload.append({
                    "id": associated_vessel["id"],
                    "name": associated_vessel["name"],
                    "lat": associated_vessel["lat"],
                    "lng": associated_vessel["lng"],
                    "anomaly": anomaly_type,
                    "risk": risk_level,
                    "inside_eez": inside_eez
                })

        return telemetry_payload

simulator = MDASimulator()

# --- 3. CORE ROUTING & REAL-TIME STREAMING ---
@app.get("/")
async def get_dashboard():
    with open("templates/index.html", "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)

@app.websocket("/ws/mda")
async def mda_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[+] Tactical Command Workstation Connected.")
    try:
        while True:
            # Process correlation pass
            current_tactical_picture = simulator.process_analytics()
            # Send serialized stream to tactical map UI
            await websocket.send_text(json.dumps(current_tactical_picture))
            await asyncio.sleep(2)  # Update tick interval
    except WebSocketDisconnect:
        print("[-] Tactical Command Workstation Disconnected.")