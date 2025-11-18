# estimates.py
import math
from typing import List, Dict, Tuple
from maps import distance_matrix_leg

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    from math import radians, sin, cos, asin, sqrt
    phi1 = radians(lat1); phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlmb/2)**2
    return 2 * R * asin(sqrt(a))

def _fallback_minutes(distance_km: float) -> int:
    speed_kmh = 30.0 if distance_km <= 10 else 40.0
    mins = int(round((distance_km / max(speed_kmh, 1e-6)) * 60))
    return max(mins, 3)

def _legs(pickup: Dict, dropoff: Dict, stops: List[Dict]) -> List[Tuple[Dict, Dict]]:
    pts = [pickup] + (stops or []) + [dropoff]
    return [(pts[i], pts[i+1]) for i in range(len(pts)-1)]

def _as_latlng(d: Dict) -> Tuple[float, float]:
    return (float(d.get("lat") or d.get("latitude")), float(d.get("lng") or d.get("longitude")))

def _sum_distance_time_via_maps(legs_list):
    total_km = 0.0
    total_min = 0
    all_ok = True
    for (a, b) in legs_list:
        a_lat, a_lng = _as_latlng(a); b_lat, b_lng = _as_latlng(b)
        res = distance_matrix_leg(a_lat, a_lng, b_lat, b_lng)
        if not res.get("ok"):
            all_ok = False
            break
        total_km += float(res["distance_km"])
        total_min += int(res["duration_min"])
    return total_km, total_min, all_ok

def build_estimates_strings(pickup: Dict, dropoff: Dict, stops: List[Dict] | None = None):
    legs_list = _legs(pickup, dropoff, stops or [])
    km, mins, ok = _sum_distance_time_via_maps(legs_list)
    if ok:
        return f"{mins} mins", f"{km:.1f} km"
    total_km = 0.0
    for (a, b) in legs_list:
        a_lat, a_lng = _as_latlng(a); b_lat, b_lng = _as_latlng(b)
        total_km += _haversine_km(a_lat, a_lng, b_lat, b_lng)
    total_min = _fallback_minutes(total_km)
    return f"{total_min} mins", f"{total_km:.1f} km"
