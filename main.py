"""
Maritime Domain Awareness System (MDA)
Gulf of Guinea — Dark Vessel & Anti-Piracy Tracking
"""
import asyncio
import json
import math
import random
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from enum import Enum

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Gulf of Guinea MDA", version="1.0")

# ─── UTILITIES ───
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def haversine_nm(lat1, lon1, lat2, lon2) -> float:
    R_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2 * R_nm * math.asin(math.sqrt(a))

# ─── ENUMS ───
class ShipStatus(str, Enum):
    NORMAL = "normal"
    LOITERING = "loitering"
    DARK = "dark"
    RENDEZVOUS = "rendezvous"

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

# ─── MODELS ───
@dataclass
class CoastalStation:
    id: str
    name: str
    lat: float
    lng: float
    status: str = "online"
    vessels_tracked: int = 0
    ais_messages_rx: int = 0

@dataclass
class Ship:
    id: str
    name: str
    type: str  # cargo | tanker | fishing | patrol | unknown
    lat: float
    lng: float
    heading: float
    speed: float  # knots
    ais_active: bool
    status: ShipStatus = ShipStatus.NORMAL
    loitering_ticks: int = 0
    trail: List[Dict] = field(default_factory=list)
    last_update: str = field(default_factory=now_iso)

    def step(self):
        nm_per_min = self.speed / 60.0
        deg_lat = nm_per_min / 60.0
        deg_lng = nm_per_min / (60.0 * max(math.cos(math.radians(self.lat)), 0.3))
        rad = math.radians(self.heading)
        self.lat += deg_lat * math.cos(rad)
        self.lng += deg_lng * math.sin(rad)
        
        if not (2.0 < self.lat < 7.0) or not (2.0 < self.lng < 9.0):
            self.heading = (self.heading + 180) % 360
            
        self.trail.append({"lat": self.lat, "lng": self.lng, "t": now_iso()})
        if len(self.trail) > 30:
            self.trail.pop(0)
        self.last_update = now_iso()

@dataclass
class OffshoreAsset:
    id: str
    name: str
    lat: float
    lng: float
    radius_nm: float

@dataclass
class SARDetection:
    id: str
    lat: float
    lng: float
    confidence: float
    correlated: bool = False
    timestamp: str = field(default_factory=now_iso)

@dataclass
class Incident:
    id: str
    type: str  # dark_vessel | rendezvous | piracy | loitering
    priority: str
    status: str  # open | investigating | responding | resolved
    lat: float
    lng: float
    description: str
    created_at: str = field(default_factory=now_iso)

@dataclass
class AlertLog:
    id: str
    timestamp: str
    category: str  # sar | ais | geofence | system
    severity: str
    message: str
    source: str = ""

@dataclass
class EmergencyBroadcast:
    id: str
    message: str
    severity: str
    sent_at: str = field(default_factory=now_iso)
    acknowledgements: Dict[str, bool] = field(default_factory=dict)
    total_recipients: int = 0
    ack_count: int = 0

@dataclass
class Geofence:
    id: str
    name: str
    fence_type: str  # eez | offshore | restricted
    lat: float
    lng: float
    radius_km: float
    color: str = "#ff4d4d"
    violations: int = 0

# ─── SIMULATOR ───
class MDASimulator:
    def __init__(self):
        self.stations = [
            CoastalStation("AIS-LAG", "Lagos AIS Base", 6.45, 3.35),
            CoastalStation("AIS-PH",  "Port Harcourt AIS", 4.81, 7.04),
            CoastalStation("RAD-ESC", "Escravos Coastal Radar", 5.60, 5.20),
        ]
        self.ships = {
            "MMSI-100000": Ship("MMSI-100000", "MV Atlantica",   "cargo",   3.80, 4.50,  85, 14, True),
            "MMSI-100001": Ship("MMSI-100001", "MT Delta Star",   "tanker",  4.45, 7.18, 200, 0.8, True),   # Loiters near Bonny
            "MMSI-100002": Ship("MMSI-100002", "FV Sea Wolf",     "fishing", 5.55, 5.22,  10, 1.2, True),   # Loiters near Escravos
            "MMSI-100003": Ship("MMSI-100003", "UNKNOWN GHOST",   "unknown", 5.10, 6.20, 270, 9,  False),  # DARK VESSEL
            "MMSI-100004": Ship("MMSI-100004", "MV Calabar",      "cargo",   4.20, 6.80,  45, 12, True),
            "MMSI-100005": Ship("MMSI-100005", "MT Bunkering King","tanker", 4.60, 6.00, 180, 2.0, True),  # Rendezvous target
        }
        self.offshore_assets = [
            OffshoreAsset("BONNY",   "Bonny Oil Terminal",      4.45, 7.20, 3.0),
            OffshoreAsset("ESCRAVOS","Escravos Terminal",       5.60, 5.20, 3.0),
            OffshoreAsset("BONGA",   "Bonga FPSO",              4.50, 6.00, 2.5),
        ]
        self.geofences = [
            Geofence("GF-EEZ", "Nigerian EEZ Border", "eez", 4.50, 6.00, 250, "#4a90e2"),
            Geofence("GF-BNY", "Bonny Restricted Zone", "restricted", 4.45, 7.20, 5.5, "#ff4d4d"),
        ]
        self.alerts_log: List[AlertLog] = []
        self.broadcasts: List[EmergencyBroadcast] = []
        self.incidents: List[Incident] = []
        self.sar_detections: List[SARDetection] = []
        self._tick = 0

    def add_log(self, category, severity, message, source=""):
        self.alerts_log.append(AlertLog(
            id=f"LOG-{uuid.uuid4().hex[:6]}",
            timestamp=now_iso(), category=category,
            severity=severity, message=message, source=source
        ))
        self.alerts_log = self.alerts_log[-100:]

    def process(self):
        self._tick += 1
        
        # 1. Move ships & update state
        for ship in self.ships.values():
            ship.step()
            ship.status = ShipStatus.NORMAL
            
            if ship.speed < 2.0:
                ship.loitering_ticks += 1
            else:
                ship.loitering_ticks = 0
                
            if not ship.ais_active:
                ship.status = ShipStatus.DARK

        # 2. Simulate SAR/Radar Scan (Sees all physical objects)
        self.sar_detections.clear()
        for ship in self.ships.values():
            ping = SARDetection(
                id=f"SAR-{uuid.uuid4().hex[:4]}",
                lat=ship.lat + random.uniform(-0.01, 0.01),
                lng=ship.lng + random.uniform(-0.01, 0.01),
                confidence=random.uniform(0.85, 0.99)
            )
            # Correlate with AIS
            if ship.ais_active:
                ping.correlated = True
            self.sar_detections.append(ping)

        # 3. Dark Vessel & Loitering Detection
        for ship in self.ships.values():
            if ship.status == ShipStatus.DARK and self._tick % 10 == 0:
                self.add_log("sar", "critical", f"DARK VESSEL detected at {ship.lat:.3f}, {ship.lng:.3f}. No AIS broadcast.", "Sentinel-1 SAR")
                if not any(i.type == "dark_vessel" and i.status != "resolved" for i in self.incidents):
                    self.incidents.append(Incident(
                        id=f"INC-{len(self.incidents)+1:04d}", type="dark_vessel", priority="critical",
                        status="open", lat=ship.lat, lng=ship.lng, description="Unregistered dark vessel intercepted"
                    ))
            
            # Loitering near offshore asset
            for asset in self.offshore_assets:
                dist = haversine_nm(ship.lat, ship.lng, asset.lat, asset.lng)
                if dist < asset.radius_nm and ship.loitering_ticks > 5 and ship.ais_active:
                    ship.status = ShipStatus.LOITERING
                    if self._tick % 15 == 0:
                        self.add_log("ais", "warning", f"{ship.name} loitering near {asset.name}", "AIS Correlation")

        # 4. Rendezvous Detection
        ship_list = list(self.ships.values())
        for i in range(len(ship_list)):
            for j in range(i+1, len(ship_list)):
                a, b = ship_list[i], ship_list[j]
                dist = haversine_nm(a.lat, a.lng, b.lat, b.lng)
                if dist < 0.5 and a.speed < 3 and b.speed < 3:
                    a.status = ShipStatus.RENDEZVOUS
                    b.status = ShipStatus.RENDEZVOUS
                    if self._tick % 10 == 0:
                        self.add_log("ais", "critical", f"RENDEZVOUS: {a.name} & {b.name} alongside at {dist:.2f} NM", "AIS Analytics")

        # 5. Network Stats
        for stn in self.stations:
            stn.vessels_tracked = len([s for s in self.ships.values() if s.ais_active])
            stn.ais_messages_rx += random.randint(5, 15)

        # 6. Simulate Acks for Broadcasts
        for bc in self.broadcasts:
            for sid in list(bc.acknowledgements.keys()):
                if not bc.acknowledgements[sid] and random.random() < 0.1:
                    bc.acknowledgements[sid] = True
            bc.ack_count = sum(1 for v in bc.acknowledgements.values() if v)

        return {
            "timestamp": now_iso(),
            "network": {
                "gateways": [asdict(s) for s in self.stations], # Reusing UI key
                "nodes": [asdict(s) for s in self.ships.values()], # Reusing UI key
                "health": {
                    "nodes_online": len([s for s in self.ships.values() if s.ais_active]),
                    "nodes_total": len(self.ships),
                    "gateways_online": len(self.stations),
                    "gateways_total": len(self.stations),
                    "coverage_pct": 94.5,
                    "packet_loss_pct": 1.2,
                    "avg_rssi": -85,
                    "avg_snr": 9.5,
                    "avg_latency_ms": 120
                },
                "coverage_points": [{"lat": s.lat, "lng": s.lng, "intensity": 1.0, "range_km": 50, "type": "gateway"} for s in self.stations]
            },
            "sensors": [asdict(s) for s in self.sar_detections],
            "geofences": [asdict(g) for g in self.geofences],
            "offshore_assets": [asdict(a) for a in self.offshore_assets],
            "incidents": [asdict(i) for i in self.incidents],
            "alerts_log": [asdict(l) for l in self.alerts_log],
            "broadcasts": [asdict(b) for b in self.broadcasts],
        }

simulator = MDASimulator()

# ─── API ───
@app.get("/")
async def dashboard():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

class BroadcastCreate(BaseModel):
    message: str
    severity: str = "critical"

@app.post("/api/broadcast")
async def send_broadcast(b: BroadcastCreate):
    bc = EmergencyBroadcast(
        id=f"ALR-{uuid.uuid4().hex[:6]}",
        message=b.message, severity=b.severity
    )
    bc.total_recipients = len(simulator.ships)
    bc.acknowledgements = {s.id: False for s in simulator.ships.values()}
    simulator.broadcasts.append(bc)
    return {"id": bc.id, "recipients": bc.total_recipients}

@app.websocket("/ws/mda")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            payload = simulator.process()
            await websocket.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(3.0)
    except WebSocketDisconnect:
        print("[-] Console disconnected.")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)