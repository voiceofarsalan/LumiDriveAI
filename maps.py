from typing import Dict, Any, List
from api import get, post

def get_distance_duration(orig: Dict[str, float], dest: Dict[str, float]) -> Dict[str, Any]:
    """
    Uses /api/v1/maps/distance-matrix to compute distance & duration.
    Returns: {"distanceKm": float, "durationMin": float}
    """
    body = {
        "origins": [f'{orig["lat"]},{orig["lng"]}'],
        "destinations": [f'{dest["lat"]},{dest["lng"]}']
    }
    resp = post("/api/v1/maps/distance-matrix", body)
    if resp.status_code != 200:
        raise RuntimeError(f"distance-matrix failed: {resp.status_code} {resp.text}")
    return resp.json()

def snap_to_road(lat: float, lng: float) -> Dict[str, float]:
    params = {"lat": str(lat), "lng": str(lng)}
    resp = get("/api/v1/maps/snap-to-road", params)
    if resp.status_code != 200:
        # fallback: return original if snap fails
        return {"latitude": lat, "longitude": lng}
    return resp.json()

def route_path(origin: Dict[str, float], dest: Dict[str, float], stops: List[Dict[str, float]] | None = None) -> Dict[str, Any]:
    params = {
        "originLat": str(origin["lat"]),
        "originLng": str(origin["lng"]),
        "destinationLat": str(dest["lat"]),
        "destinationLng": str(dest["lng"]),
    }
    if stops:
        params["stops"] = "|".join([f'{s["lat"]},{s["lng"]}' for s in stops])
    resp = get("/api/v1/maps/route", params)
    return {"status": resp.status_code, "data": resp.json() if resp.status_code == 200 else resp.text}
