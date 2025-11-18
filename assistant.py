# # assistant.py
# import os, json, sys, re
# from datetime import datetime, timedelta, timezone
# from dotenv import load_dotenv
# from openai import OpenAI

# from auth import ensure_token_via_signup_or_manual
# from rides import (
#     list_ride_types, get_fare, pick_ride_type_id_from_fare, create_ride_request_exact,
#     wait_for_bids, accept_bid, get_customer_ride, cancel_ride_as_customer
# )

# load_dotenv()
# MODEL = os.getenv("MODEL", "gpt-4o-mini")
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# if not OPENAI_API_KEY:
#     print("Please set OPENAI_API_KEY in .env")
#     sys.exit(1)

# client = OpenAI(api_key=OPENAI_API_KEY)

# SYSTEM = """You are LumiDrive, a ride-booking assistant.

# Flow:
# 1) Collect pickup/dropoff. If the user provides place names (e.g., "Gaddafi Stadium to Johar Town"), infer coordinates from your local gazetteer and proceed.
# 2) Ask if they want stops; then ask ride type (e.g., LUMI_GO/Courier). If Courier, collect courier fields.
# 3) First call /api/v1/rides/fare/all (distanceKm/durationMin) and PRESENT the quoted fares per ride type.
# 4) Only AFTER the user confirms, create the ride request via POST /api/v1/rides:
#    - Body MUST match backend expectations, including estimated_time and estimated_distance if available.
# 5) Then poll bids on that ride request and show them to the user.
# 6) Allow: 'accept bid <id>', 'track', 'cancel <reason?>'.

# Keep replies short and action-focused.
# """

# tools = [
#   { "type":"function", "function": {
#       "name":"set_trip_core",
#       "description":"Save pickup, dropoff, addresses, and rideTypeName (optional)",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "pickup":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"]},
#           "dropoff":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"]},
#           "pickup_address":{"type":"string"},
#           "destination_address":{"type":"string"},
#           "rideTypeName":{"type":"string","description":"Name from /ride-types, e.g., LUMI_GO or Courier"}
#         },
#         "required":["pickup","dropoff"]
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"set_stops",
#       "description":"Provide an ordered list of stops (0..N). Each stop may include address.",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "stops":{"type":"array","items":{
#             "type":"object",
#             "properties":{
#               "lat":{"type":"number"},
#               "lng":{"type":"number"},
#               "address":{"type":"string"},
#               "order":{"type":"integer"}
#             },
#             "required":["lat","lng"]
#           }}
#         },
#         "required":["stops"]
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"set_courier_fields",
#       "description":"Set courier-only fields. Use only if ride type is Courier.",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "sender_phone_number":{"type":"string"},
#           "receiver_phone_number":{"type":"string"},
#           "comments_for_courier":{"type":"string"},
#           "package_size":{"type":"integer"},
#           "package_types":{"type":"array","items":{"type":"string"}}
#         }
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"list_ride_types",
#       "description":"Fetch available ride types",
#       "parameters":{"type":"object","properties":{}}
#   }},
#   { "type":"function", "function": {
#       "name":"create_request_and_poll",
#       "description":"FARE → create ride → poll bids (called only after user confirms)",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"]},
#           "is_scheduled":{"type":"boolean"},
#           "scheduled_at":{"type":"string","description":"ISO8601 if is_scheduled==true"},
#           "offered_fair":{"type":"number"},
#           "is_family":{"type":"boolean"}
#         }
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"accept_bid",
#       "description":"Accept a bid by id",
#       "parameters":{"type":"object","properties":{"bidId":{"type":"string"}},"required":["bidId"]}
#   }},
#   { "type":"function", "function": {
#       "name":"track_ride",
#       "description":"Get current ride details",
#       "parameters":{"type":"object","properties":{"rideId":{"type":"string"}},"required":["rideId"]}
#   }},
#   { "type":"function", "function": {
#       "name":"cancel_ride",
#       "description":"Cancel a ride",
#       "parameters":{"type":"object","properties":{"rideId":{"type":"string"},"reason":{"type":"string"}},"required":["rideId"]}
#   }}
# ]

# STATE = {
#   "pickup": None,
#   "dropoff": None,
#   "pickup_address": None,
#   "destination_address": None,
#   "pickup_location": None,
#   "dropoff_location": None,
#   "stops": [],
#   "rideTypeName": None,
#   "rideTypeId": None,
#   "rideRequestId": None,
#   "rideId": None,

#   # courier optionals
#   "sender_phone_number": None,
#   "receiver_phone_number": None,
#   "comments_for_courier": None,
#   "package_size": None,
#   "package_types": None,
# }

# # --- small gazetteer for quick inference (extend as needed) ---
# PLACES = {
#     "gaddafi stadium": {"lat": 31.5204, "lng": 74.3384, "address": "Gaddafi Stadium, Lahore"},
#     "johar town":      {"lat": 31.4676, "lng": 74.2728, "address": "Johar Town, Lahore"},
#     "lahore":          {"lat": 31.5497, "lng": 74.3436, "address": "Lahore"},
# }

# def _lookup_place(text: str):
#     key = text.strip().lower()
#     return PLACES.get(key)

# def _resolve_place_pair_from_text(utterance: str):
#     m = re.split(r"\s+to\s+|→", utterance.strip(), maxsplit=1, flags=re.IGNORECASE)
#     if len(m) != 2:
#         return None
#     p_txt, d_txt = m[0].strip(), m[1].strip()
#     p = _lookup_place(p_txt)
#     d = _lookup_place(d_txt)
#     if p and d:
#         return {
#             "pickup":  {"lat": p["lat"], "lng": p["lng"], "address": p["address"]},
#             "dropoff": {"lat": d["lat"], "lng": d["lng"], "address": d["address"]},
#         }
#     return None

# from datetime import datetime, timedelta, timezone

# def _iso_in(minutes: int) -> str:
#     """
#     Return an ISO8601 timestamp with milliseconds and trailing 'Z',
#     e.g. 2025-09-23T07:25:32.084Z
#     """
#     dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
#     # format to YYYY-MM-DDTHH:MM:SS.mmmZ
#     return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# def ensure_login():
#     from api import TOKEN
#     if TOKEN:
#         return True
#     print("You are not logged in.")
#     phone = input("Phone in E.164 (e.g., +923001234567): ").strip()
#     result = ensure_token_via_signup_or_manual(phone)
#     if result.get("ok"):
#         print("✅ Auth ready.")
#         return True
#     print("❌ Auth failed:", result.get("error"))
#     return False

# # ---------------- tools impl ----------------
# def tool_set_trip_core(pickup, dropoff, pickup_address=None, destination_address=None, rideTypeName=None):
#     STATE["pickup"] = pickup
#     STATE["dropoff"] = dropoff
#     STATE["pickup_address"] = pickup_address or pickup.get("address") or "Pickup"
#     STATE["destination_address"] = destination_address or dropoff.get("address") or "Dropoff"
#     STATE["pickup_location"] = STATE["pickup_address"]
#     STATE["dropoff_location"] = STATE["destination_address"]
#     STATE["rideTypeName"] = rideTypeName or STATE["rideTypeName"]

#     if STATE["rideTypeName"]:
#         for t in list_ride_types():
#             if str(t.get("name", "")).strip().lower() == STATE["rideTypeName"].strip().lower():
#                 STATE["rideTypeId"] = t.get("id")
#                 break

#     return {"ok": True, "state": {
#         "pickup": STATE["pickup"],
#         "dropoff": STATE["dropoff"],
#         "pickup_address": STATE["pickup_address"],
#         "destination_address": STATE["destination_address"],
#         "rideTypeName": STATE["rideTypeName"],
#         "rideTypeId": STATE["rideTypeId"],
#     }}

# def tool_set_stops(stops):
#     norm = []
#     for idx, s in enumerate(stops):
#         norm.append({
#             "lat": s.get("lat") or s.get("latitude"),
#             "lng": s.get("lng") or s.get("longitude"),
#             **({"address": s.get("address")} if s.get("address") else {}),
#             "order": s.get("order", idx + 1),  # ensure order field exists
#         })
#     STATE["stops"] = norm
#     return {"ok": True, "count": len(norm), "stops": norm}

# def tool_set_courier_fields(sender_phone_number=None, receiver_phone_number=None, comments_for_courier=None, package_size=None, package_types=None):
#     STATE["sender_phone_number"] = sender_phone_number
#     STATE["receiver_phone_number"] = receiver_phone_number
#     STATE["comments_for_courier"] = comments_for_courier
#     STATE["package_size"] = package_size
#     STATE["package_types"] = package_types
#     return {"ok": True}

# def tool_create_request_and_poll(payment_via=None, is_scheduled=False, scheduled_at=None, offered_fair=0, is_family=False):
#     # 1) Fare quote first (distance/duration)
#     fare = get_fare(STATE["pickup"], STATE["dropoff"], STATE["stops"])
#     if fare["status"] != 200:
#         return {"ok": False, "stage": "fare", "status": fare["status"], "data": fare["data"]}

#     computed = fare.get("computed", {}) or {}
#     distance_km = computed.get("distanceKm", 0.0)
#     duration_min = computed.get("durationMin", 0.0)

#     # Strings matching your example: "30 mins", "10 km"
#     estimated_distance = f"{distance_km} km"
#     estimated_time = f"{int(round(duration_min))} mins"

#     chosen_name = STATE["rideTypeName"]
#     ride_type_id = pick_ride_type_id_from_fare(fare["data"], chosen_name) or STATE["rideTypeId"]
#     if not ride_type_id:
#         return {
#             "ok": False,
#             "stage": "fare",
#             "error": "Could not resolve ride_type_id for selected ride type.",
#             "quote": fare,
#         }

#     out = create_ride_request_exact(
#         pickup=STATE["pickup"],
#         dropoff=STATE["dropoff"],
#         ride_type_id=ride_type_id,
#         pickup_location=STATE["pickup_location"],
#         dropoff_location=STATE["dropoff_location"],
#         pickup_address=STATE["pickup_address"],
#         destination_address=STATE["destination_address"],
#         pickup_coordinates={"lat": STATE["pickup"].get("lat"), "lng": STATE["pickup"].get("lng")},
#         destination_coordinates={"lat": STATE["dropoff"].get("lat"), "lng": STATE["dropoff"].get("lng")},
#         stops=STATE["stops"],
#         # courier optionals
#         sender_phone_number=STATE["sender_phone_number"],
#         receiver_phone_number=STATE["receiver_phone_number"],
#         comments_for_courier=STATE["comments_for_courier"],
#         package_size=STATE["package_size"],
#         package_types=STATE["package_types"],
#         # flags
#         payment_via=payment_via or "WALLET",
#         is_hourly=False,
#         is_scheduled=bool(is_scheduled),
#         scheduled_at=scheduled_at or _iso_in(15),
#         offered_fair=offered_fair if offered_fair is not None else 0,
#         is_family=bool(is_family),
#         estimated_time=estimated_time,
#         estimated_distance=estimated_distance,
#     )

#     if out["status"] not in (200, 201, 202):
#         return {
#             "ok": False,
#             "stage": "create",
#             "status": out["status"],
#             "data": out["data"],
#             "quote": fare,
#             "requestBody": out.get("requestBody"),
#         }

#     rrid = out["rideRequestId"]
#     STATE["rideRequestId"] = rrid

#     bids = wait_for_bids(rrid, timeout_seconds=60, poll_interval=4)
#     slim = []
#     for b in bids:
#         if isinstance(b, dict):
#             slim.append({
#                 "id": b.get("id"),
#                 "price": b.get("price") or b.get("amount") or b.get("fare"),
#                 "etaSeconds": b.get("etaSeconds") or b.get("eta") or b.get("estimatedArrivalSeconds"),
#                 "driver": (b.get("driver") or b.get("rider") or {}),
#             })
#         else:
#             slim.append(b)

#     return {
#         "ok": True,
#         "rideRequestId": rrid,
#         "bids": slim,
#         "quote": fare,
#         "requestBody": out.get("requestBody"),
#     }

# def tool_accept_bid(bidId):
#     out = accept_bid(bidId)
#     data = out.get("data")
#     try:
#         data = json.loads(data) if isinstance(data, str) else data
#     except Exception:
#         pass
#     ride_id = None
#     if isinstance(data, dict):
#         ride_id = data.get("rideId") or data.get("id") or data.get("ride", {}).get("id")
#     if ride_id:
#         STATE["rideId"] = ride_id
#     return {"status": out["status"], "rideId": ride_id, "raw": out["data"]}

# def tool_track_ride(rideId):
#     return get_customer_ride(rideId)

# def tool_cancel_ride(rideId, reason=None):
#     return cancel_ride_as_customer(rideId)

# def call_tool(name, args):
#     if name == "set_trip_core":           return tool_set_trip_core(**args)
#     if name == "set_stops":               return tool_set_stops(**args)
#     if name == "set_courier_fields":      return tool_set_courier_fields(**args)
#     if name == "list_ride_types":         return [{"id": t.get("id"), "name": t.get("name"), "active": t.get("isActive")} for t in list_ride_types()]
#     if name == "create_request_and_poll": return tool_create_request_and_poll(**args)
#     if name == "accept_bid":              return tool_accept_bid(**args)
#     if name == "track_ride":              return tool_track_ride(**args)
#     if name == "cancel_ride":             return tool_cancel_ride(**args)
#     return {"error": "unknown tool"}

# def chat_loop():
#     if not ensure_login():
#         return

#     messages = [
#         {"role": "system", "content": SYSTEM},
#         {"role": "assistant", "content": "Hi! Tell me pickup → dropoff (landmarks or full addresses are fine). Add stops? Then choose ride type (e.g., LUMI_GO). I’ll show the fare quote first."}
#     ]
#     print("LumiDrive ready. (Ctrl+C to exit)\n")

#     while True:
#         user = input("You: ").strip()
#         if not user:
#             continue

#         # Local inference: "X to Y"
#         if not STATE["pickup"] and (" to " in user.lower() or "→" in user):
#             pair = _resolve_place_pair_from_text(user)
#             if pair:
#                 tool_result = tool_set_trip_core(
#                     pickup=pair["pickup"],
#                     dropoff=pair["dropoff"],
#                     pickup_address=pair["pickup"]["address"],
#                     destination_address=pair["dropoff"]["address"],
#                     rideTypeName=None,
#                 )
#                 messages.extend([
#                     {"role": "user", "content": user},
#                     {"role": "tool", "tool_call_id": "bootstrap-set-trip", "name": "set_trip_core", "content": json.dumps(tool_result)},
#                 ])
#             else:
#                 messages.append({"role": "user", "content": user})
#         else:
#             messages.append({"role": "user", "content": user})

#         resp = client.chat.completions.create(
#             model=MODEL,
#             messages=messages,
#             tools=[{"type": "function", "function": t["function"]} for t in tools],
#             tool_choice="auto",
#         )
#         msg = resp.choices[0].message

#         if msg.tool_calls:
#             messages.append({
#                 "role": "assistant",
#                 "content": msg.content or "",
#                 "tool_calls": [
#                     {
#                         "id": tc.id,
#                         "type": "function",
#                         "function": {
#                             "name": tc.function.name,
#                             "arguments": tc.function.arguments or "{}",
#                         },
#                     }
#                     for tc in msg.tool_calls
#                 ],
#             })

#             for tc in msg.tool_calls:
#                 args = json.loads(tc.function.arguments or "{}")

#                 # Robust fallback if set_trip_core is called without required args
#                 if tc.function.name == "set_trip_core" and (not args or "pickup" not in args or "dropoff" not in args):
#                     last_user_text = user
#                     pair = _resolve_place_pair_from_text(last_user_text) or _resolve_place_pair_from_text(
#                         messages[-3]["content"] if len(messages) >= 3 and messages[-3]["role"] == "user" else ""
#                     )
#                     if pair:
#                         args = {
#                             "pickup": {
#                                 "lat": pair["pickup"]["lat"],
#                                 "lng": pair["pickup"]["lng"],
#                                 "address": pair["pickup"]["address"],
#                             },
#                             "dropoff": {
#                                 "lat": pair["dropoff"]["lat"],
#                                 "lng": pair["dropoff"]["lng"],
#                                 "address": pair["dropoff"]["address"],
#                             },
#                             "pickup_address": pair["pickup"]["address"],
#                             "destination_address": pair["dropoff"]["address"],
#                         }

#                 try:
#                     result = eval(f"tool_{tc.function.name}")(**args)
#                 except TypeError as e:
#                     result = {"ok": False, "error": f"tool_{tc.function.name} invocation error", "details": str(e)}
#                 except NameError:
#                     result = call_tool(tc.function.name, args)

#                 messages.append({
#                     "role": "tool",
#                     "tool_call_id": tc.id,
#                     "name": tc.function.name,
#                     "content": json.dumps(result),
#                 })

#             follow = client.chat.completions.create(model=MODEL, messages=messages)
#             final_msg = follow.choices[0].message
#             print("LumiDrive:", final_msg.content, "\n")
#             messages.append({"role": "assistant", "content": final_msg.content})
#         else:
#             print("LumiDrive:", msg.content, "\n")
#             messages.append({"role": "assistant", "content": msg.content})

# if __name__ == "__main__":
#     try:
#         chat_loop()
#     except KeyboardInterrupt:
#         print("\nBye!")

import os, json, sys, re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from openai import OpenAI

from auth import ensure_token_via_signup_or_manual
from rides import (
    list_ride_types, get_fare, pick_ride_type_id_from_fare, create_ride_request_exact,
    wait_for_bids, accept_bid, get_customer_ride, cancel_ride_as_customer
)

load_dotenv()
MODEL = os.getenv("MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Please set OPENAI_API_KEY in .env")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM = """You are LumiDrive, a ride-booking assistant.

Flow:
1) Collect pickup/dropoff. If the user provides place names (e.g., "Gaddafi Stadium to Johar Town"), infer coordinates from your local gazetteer and proceed.
2) Ask if they want stops; then ask ride type (e.g., LUMI_GO/Courier). If Courier, collect courier fields.
3) First call /api/v1/rides/fare/all (distanceKm/durationMin) and PRESENT the quoted fares per ride type.
4) Only AFTER the user confirms, create the ride request via POST /api/v1/rides:
   - Body MUST match backend expectations, including estimated_time and estimated_distance if available.
5) Then poll bids on that ride request and show them to the user.
6) Allow: 'accept bid <id>', 'accept bid 1', 'accept bid from hasnat', 'wait for more bids', 'track', 'cancel <reason?>'.

Use the tools:
- create_request_and_poll: quote fare, create ride, then poll bids once.
- wait_for_bids: re-poll bids for the current rideRequestId (e.g. when user says "wait for more bids" or "show bids again").
- accept_bid_choice: to accept bid by its index or driver name (e.g. "accept bid 1" or "accept bid from hasnat").
- accept_bid: only if the user explicitly provides a bid UUID.

Keep replies short and action-focused.
"""

tools = [
  { "type":"function", "function": {
      "name":"set_trip_core",
      "description":"Save pickup, dropoff, addresses, and rideTypeName (optional)",
      "parameters":{
        "type":"object",
        "properties":{
          "pickup":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"]},
          "dropoff":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"]},
          "pickup_address":{"type":"string"},
          "destination_address":{"type":"string"},
          "rideTypeName":{"type":"string","description":"Name from /ride-types, e.g., LUMI_GO or Courier"}
        },
        "required":["pickup","dropoff"]
      }
  }},
  { "type":"function", "function": {
      "name":"set_stops",
      "description":"Provide an ordered list of stops (0..N). Each stop may include address.",
      "parameters":{
        "type":"object",
        "properties":{
          "stops":{"type":"array","items":{
            "type":"object",
            "properties":{
              "lat":{"type":"number"},
              "lng":{"type":"number"},
              "address":{"type":"string"},
              "order":{"type":"integer"}
            },
            "required":["lat","lng"]
          }}
        },
        "required":["stops"]
      }
  }},
  { "type":"function", "function": {
      "name":"set_courier_fields",
      "description":"Set courier-only fields. Use only if ride type is Courier.",
      "parameters":{
        "type":"object",
        "properties":{
          "sender_phone_number":{"type":"string"},
          "receiver_phone_number":{"type":"string"},
          "comments_for_courier":{"type":"string"},
          "package_size":{"type":"integer"},
          "package_types":{"type":"array","items":{"type":"string"}}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"list_ride_types",
      "description":"Fetch available ride types",
      "parameters":{"type":"object","properties":{}}
  }},
  { "type":"function", "function": {
      "name":"create_request_and_poll",
      "description":"FARE → create ride → poll bids (called only after user confirms)",
      "parameters":{
        "type":"object",
        "properties":{
          "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"]},
          "is_scheduled":{"type":"boolean"},
          "scheduled_at":{"type":"string","description":"ISO8601 if is_scheduled==true"},
          "offered_fair":{"type":"number"},
          "is_family":{"type":"boolean"}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"wait_for_bids",
      "description":"Re-poll bids for the current rideRequestId. Use when the user says 'wait for more bids' or 'show bids again'.",
      "parameters":{
        "type":"object",
        "properties":{
          "timeout_seconds":{"type":"integer","description":"Max seconds to wait for bids.","default":30},
          "poll_interval":{"type":"integer","description":"Polling interval in seconds.","default":4}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"accept_bid_choice",
      "description":"Accept a bid using its index in the last listed bids or by driver name.",
      "parameters":{
        "type":"object",
        "properties":{
          "choice_index":{"type":"integer","description":"1-based index of the bid from the last bids list."},
          "driver_name":{"type":"string","description":"Case-insensitive driver name match, e.g. 'hasnat'."}
        },
        "description":"Provide either choice_index or driver_name to pick which bid to accept."
      }
  }},
  { "type":"function", "function": {
      "name":"accept_bid",
      "description":"Accept a bid by id (UUID). Prefer accept_bid_choice when user gives an index or name.",
      "parameters":{"type":"object","properties":{"bidId":{"type":"string"}},"required":["bidId"]}
  }},
  { "type":"function", "function": {
      "name":"track_ride",
      "description":"Get current ride details",
      "parameters":{"type":"object","properties":{"rideId":{"type":"string"}},"required":["rideId"]}
  }},
  { "type":"function", "function": {
      "name":"cancel_ride",
      "description":"Cancel a ride",
      "parameters":{"type":"object","properties":{"rideId":{"type":"string"},"reason":{"type":"string"}},"required":["rideId"]}
  }}
]

STATE = {
  "pickup": None,
  "dropoff": None,
  "pickup_address": None,
  "destination_address": None,
  "pickup_location": None,
  "dropoff_location": None,
  "stops": [],
  "rideTypeName": None,
  "rideTypeId": None,
  "customerId": None,
  "rideRequestId": None,
  "rideId": None,

  # courier optionals
  "sender_phone_number": None,
  "receiver_phone_number": None,
  "comments_for_courier": None,
  "package_size": None,
  "package_types": None,

  # bidding
  "last_bids": [],
  "last_quote": None,
}

def _extract_customer_id_from_bid(bid: dict | None):
    if not isinstance(bid, dict):
        return None
    ride_request = bid.get("rideRequest") or bid.get("ride_request") or {}
    passenger = (
        bid.get("passenger")
        or bid.get("customer")
        or ride_request.get("passenger")
        or ride_request.get("customer")
        or {}
    )
    return (
        bid.get("passenger_id")
        or bid.get("passengerId")
        or bid.get("customer_id")
        or bid.get("customerId")
        or ride_request.get("passenger_id")
        or ride_request.get("passengerId")
        or ride_request.get("customer_id")
        or ride_request.get("customerId")
        or passenger.get("id")
    )

def _remember_customer_id_from_bid(bid: dict | None):
    cid = _extract_customer_id_from_bid(bid)
    if cid:
        STATE["customerId"] = cid
    return cid

# --- small gazetteer for quick inference (extend as needed) ---
PLACES = {
    "gaddafi stadium": {"lat": 31.5204, "lng": 74.3384, "address": "Gaddafi Stadium, Lahore"},
    "johar town":      {"lat": 31.4676, "lng": 74.2728, "address": "Johar Town, Lahore"},
    "lahore":          {"lat": 31.5497, "lng": 74.3436, "address": "Lahore"},
}

def _lookup_place(text: str):
    key = text.strip().lower()
    return PLACES.get(key)

def _resolve_place_pair_from_text(utterance: str):
    m = re.split(r"\s+to\s+|→", utterance.strip(), maxsplit=1, flags=re.IGNORECASE)
    if len(m) != 2:
        return None
    p_txt, d_txt = m[0].strip(), m[1].strip()
    p = _lookup_place(p_txt)
    d = _lookup_place(d_txt)
    if p and d:
        return {
            "pickup":  {"lat": p["lat"], "lng": p["lng"], "address": p["address"]},
            "dropoff": {"lat": d["lat"], "lng": d["lng"], "address": d["address"]},
        }
    return None

def _iso_in(minutes: int) -> str:
    """
    Return an ISO8601 timestamp with milliseconds and trailing 'Z',
    e.g. 2025-09-23T07:25:32.084Z
    """
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    # format to YYYY-MM-DDTHH:MM:SS.mmmZ
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_login():
    from api import TOKEN
    if TOKEN:
        return True
    print("You are not logged in.")
    phone = input("Phone in E.164 (e.g., +923001234567): ").strip()
    result = ensure_token_via_signup_or_manual(phone)
    if result.get("ok"):
        print("✅ Auth ready.")
        return True
    print("❌ Auth failed:", result.get("error"))
    return False

# ---------------- tools impl ----------------
def tool_set_trip_core(pickup, dropoff, pickup_address=None, destination_address=None, rideTypeName=None):
    STATE["pickup"] = pickup
    STATE["dropoff"] = dropoff
    STATE["pickup_address"] = pickup_address or pickup.get("address") or "Pickup"
    STATE["destination_address"] = destination_address or dropoff.get("address") or "Dropoff"
    STATE["pickup_location"] = STATE["pickup_address"]
    STATE["dropoff_location"] = STATE["destination_address"]
    STATE["rideTypeName"] = rideTypeName or STATE["rideTypeName"]

    if STATE["rideTypeName"]:
        for t in list_ride_types():
            if str(t.get("name", "")).strip().lower() == STATE["rideTypeName"].strip().lower():
                STATE["rideTypeId"] = t.get("id")
                break

    return {"ok": True, "state": {
        "pickup": STATE["pickup"],
        "dropoff": STATE["dropoff"],
        "pickup_address": STATE["pickup_address"],
        "destination_address": STATE["destination_address"],
        "rideTypeName": STATE["rideTypeName"],
        "rideTypeId": STATE["rideTypeId"],
    }}

def tool_set_stops(stops):
    norm = []
    for idx, s in enumerate(stops):
        norm.append({
            "lat": s.get("lat") or s.get("latitude"),
            "lng": s.get("lng") or s.get("longitude"),
            **({"address": s.get("address")} if s.get("address") else {}),
            "order": s.get("order", idx + 1),  # ensure order field exists
        })
    STATE["stops"] = norm
    return {"ok": True, "count": len(norm), "stops": norm}

def tool_set_courier_fields(sender_phone_number=None, receiver_phone_number=None, comments_for_courier=None, package_size=None, package_types=None):
    STATE["sender_phone_number"] = sender_phone_number
    STATE["receiver_phone_number"] = receiver_phone_number
    STATE["comments_for_courier"] = comments_for_courier
    STATE["package_size"] = package_size
    STATE["package_types"] = package_types
    return {"ok": True}

def tool_create_request_and_poll(payment_via=None, is_scheduled=False, scheduled_at=None, offered_fair=0, is_family=False):
    # 1) Fare quote first (distance/duration)
    fare = get_fare(STATE["pickup"], STATE["dropoff"], STATE["stops"])
    if fare["status"] != 200:
        return {"ok": False, "stage": "fare", "status": fare["status"], "data": fare["data"]}

    computed = fare.get("computed", {}) or {}
    distance_km = computed.get("distanceKm", 0.0)
    duration_min = computed.get("durationMin", 0.0)

    # Strings matching your example: "30 mins", "10 km"
    estimated_distance = f"{distance_km} km"
    estimated_time = f"{int(round(duration_min))} mins"

    chosen_name = STATE["rideTypeName"]
    ride_type_id = pick_ride_type_id_from_fare(fare["data"], chosen_name) or STATE["rideTypeId"]
    if not ride_type_id:
        return {
            "ok": False,
            "stage": "fare",
            "error": "Could not resolve ride_type_id for selected ride type.",
            "quote": fare,
        }

    out = create_ride_request_exact(
        pickup=STATE["pickup"],
        dropoff=STATE["dropoff"],
        ride_type_id=ride_type_id,
        pickup_location=STATE["pickup_location"],
        dropoff_location=STATE["dropoff_location"],
        pickup_address=STATE["pickup_address"],
        destination_address=STATE["destination_address"],
        pickup_coordinates={"lat": STATE["pickup"].get("lat"), "lng": STATE["pickup"].get("lng")},
        destination_coordinates={"lat": STATE["dropoff"].get("lat"), "lng": STATE["dropoff"].get("lng")},
        stops=STATE["stops"],
        # courier optionals
        sender_phone_number=STATE["sender_phone_number"],
        receiver_phone_number=STATE["receiver_phone_number"],
        comments_for_courier=STATE["comments_for_courier"],
        package_size=STATE["package_size"],
        package_types=STATE["package_types"],
        # flags
        payment_via=payment_via or "WALLET",
        is_hourly=False,
        is_scheduled=bool(is_scheduled),
        scheduled_at=scheduled_at or _iso_in(15),
        offered_fair=offered_fair if offered_fair is not None else 0,
        is_family=bool(is_family),
        estimated_time=estimated_time,
        estimated_distance=estimated_distance,
    )

    if out["status"] not in (200, 201, 202):
        return {
            "ok": False,
            "stage": "create",
            "status": out["status"],
            "data": out["data"],
            "quote": fare,
            "requestBody": out.get("requestBody"),
        }

    rrid = out["rideRequestId"]
    STATE["rideRequestId"] = rrid
    STATE["customerId"] = None
    STATE["last_quote"] = fare

    bids = wait_for_bids(rrid, timeout_seconds=60, poll_interval=4)
    STATE["last_bids"] = bids or []

    slim = []
    for idx, b in enumerate(STATE["last_bids"], start=1):
        if isinstance(b, dict):
            _remember_customer_id_from_bid(b)
            driver = (
                b.get("rider") or b.get("driver") or {}
            )
            user_profile = driver.get("userProfile", {})
            user = user_profile.get("user", {})
            driver_name = user.get("name") or "Unknown driver"

            slim.append({
                "index": idx,
                "id": b.get("id"),
                "price": b.get("price") or b.get("amount") or b.get("fare"),
                "etaSeconds": b.get("etaSeconds") or b.get("eta") or b.get("estimatedArrivalSeconds"),
                "driverName": driver_name,
                "driverProfile": user.get("profile"),
            })
        else:
            slim.append({"index": idx, "raw": b})

    return {
        "ok": True,
        "rideRequestId": rrid,
        "bids": slim,
        "quote": fare,
        "requestBody": out.get("requestBody"),
    }

def tool_wait_for_bids(timeout_seconds: int = 30, poll_interval: int = 4):
    """
    Re-poll bids for the current rideRequestId and return a summarized list.
    """
    rrid = STATE.get("rideRequestId")
    if not rrid:
        return {"ok": False, "error": "No active rideRequestId in state."}

    bids = wait_for_bids(rrid, timeout_seconds=timeout_seconds, poll_interval=poll_interval)
    STATE["last_bids"] = bids or []

    if not STATE["last_bids"]:
        return {"ok": True, "rideRequestId": rrid, "bids": [], "message": "No bids yet for this ride request."}

    slim = []
    lines = []
    for idx, b in enumerate(STATE["last_bids"], start=1):
        if isinstance(b, dict):
            _remember_customer_id_from_bid(b)
            driver = (b.get("rider") or b.get("driver") or {})
            user_profile = driver.get("userProfile", {})
            user = user_profile.get("user", {})
            driver_name = user.get("name") or "Unknown driver"

            price = b.get("price") or b.get("amount") or b.get("fare")
            status = b.get("status", "PENDING")

            slim.append({
                "index": idx,
                "id": b.get("id"),
                "price": price,
                "status": status,
                "driverName": driver_name,
                "driverProfile": user.get("profile"),
            })
            lines.append(f"{idx}) {driver_name} – {price} ({status})")
        else:
            slim.append({"index": idx, "raw": b})
            lines.append(f"{idx}) {b}")

    message = "Here are the latest bids:\n" + "\n".join(lines) + "\n\nYou can say 'accept bid 1', 'accept bid 2', or 'accept bid from hasnat'."

    return {"ok": True, "rideRequestId": rrid, "bids": slim, "message": message}

def tool_accept_bid(bidId, customer_id=None):
    customer_id = customer_id or STATE.get("customerId")
    if not customer_id:
        return {"status": 400, "error": "Missing customerId from last bids. Please refresh bids and try again."}
    out = accept_bid(bidId, customer_id=customer_id)
    data = out.get("data")
    try:
        data = json.loads(data) if isinstance(data, str) else data
    except Exception:
        pass
    ride_id = None
    if isinstance(data, dict):
        ride_id = data.get("rideId") or data.get("id") or data.get("ride", {}).get("id")
    if ride_id:
        STATE["rideId"] = ride_id
    return {"status": out["status"], "rideId": ride_id, "raw": out["data"]}

def tool_accept_bid_choice(choice_index: int = None, driver_name: str = None):
    """
    Accept a bid by its index in STATE['last_bids'] or by driver_name.
    """
    bids = STATE.get("last_bids") or []
    if not bids:
        return {"ok": False, "error": "No bids cached. Call create_request_and_poll or wait_for_bids first."}

    selected = None

    if choice_index is not None:
        idx0 = choice_index - 1
        if idx0 < 0 or idx0 >= len(bids):
            return {"ok": False, "error": f"Invalid bid index {choice_index}. Only {len(bids)} bids available."}
        selected = bids[idx0]

    elif driver_name:
        dn = driver_name.strip().lower()
        for b in bids:
            if not isinstance(b, dict):
                continue
            driver = (b.get("rider") or b.get("driver") or {})
            user_profile = driver.get("userProfile", {})
            user = user_profile.get("user", {})
            name = (user.get("name") or "").lower()
            if dn == name or dn in name:
                selected = b
                break
        if not selected:
            return {"ok": False, "error": f"No bid found for driver '{driver_name}'."}
    else:
        return {"ok": False, "error": "Must provide either choice_index or driver_name."}

    bid_id = selected.get("id")
    if not bid_id:
        return {"ok": False, "error": "Selected bid has no id."}

    price = selected.get("price")
    driver = (selected.get("rider") or selected.get("driver") or {})
    user_profile = driver.get("userProfile", {})
    user = user_profile.get("user", {})
    driver_name_final = user.get("name") or "the selected driver"

    customer_id = _remember_customer_id_from_bid(selected)

    # Reuse low-level accept tool
    base = tool_accept_bid(bidId=bid_id, customer_id=customer_id)
    ok = base.get("status") in (200, 201, 202)

    msg = f"Bid from {driver_name_final} for {price} has been accepted. Your ride is now confirmed." if ok else \
          f"Failed to accept bid from {driver_name_final}. Status: {base.get('status')}"

    return {
        "ok": ok,
        "message": msg,
        "bidId": bid_id,
        "driverName": driver_name_final,
        "price": price,
        "result": base,
    }

def tool_track_ride(rideId):
    return get_customer_ride(rideId)

def tool_cancel_ride(rideId, reason=None):
    return cancel_ride_as_customer(rideId)

def call_tool(name, args):
    if name == "set_trip_core":           return tool_set_trip_core(**args)
    if name == "set_stops":               return tool_set_stops(**args)
    if name == "set_courier_fields":      return tool_set_courier_fields(**args)
    if name == "list_ride_types":         return [{"id": t.get("id"), "name": t.get("name"), "active": t.get("isActive")} for t in list_ride_types()]
    if name == "create_request_and_poll": return tool_create_request_and_poll(**args)
    if name == "wait_for_bids":           return tool_wait_for_bids(**args)
    if name == "accept_bid_choice":       return tool_accept_bid_choice(**args)
    if name == "accept_bid":              return tool_accept_bid(**args)
    if name == "track_ride":              return tool_track_ride(**args)
    if name == "cancel_ride":             return tool_cancel_ride(**args)
    return {"error": "unknown tool"}

def chat_loop():
    if not ensure_login():
        return

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "assistant", "content": "Hi! Tell me pickup → dropoff (landmarks or full addresses are fine). Add stops? Then choose ride type (e.g., LUMI_GO). I’ll show the fare quote first, then create the ride and show available bids you can accept or wait for more."}
    ]
    print("LumiDrive ready. (Ctrl+C to exit)\n")

    while True:
        user = input("You: ").strip()
        if not user:
            continue

        # Local inference: "X to Y"
        if not STATE["pickup"] and (" to " in user.lower() or "→" in user):
            pair = _resolve_place_pair_from_text(user)
            if pair:
                tool_result = tool_set_trip_core(
                    pickup=pair["pickup"],
                    dropoff=pair["dropoff"],
                    pickup_address=pair["pickup"]["address"],
                    destination_address=pair["dropoff"]["address"],
                    rideTypeName=None,
                )
                messages.extend([
                    {"role": "user", "content": user},
                    {"role": "tool", "tool_call_id": "bootstrap-set-trip", "name": "set_trip_core", "content": json.dumps(tool_result)},
                ])
            else:
                messages.append({"role": "user", "content": user})
        else:
            messages.append({"role": "user", "content": user})

        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[{"type": "function", "function": t["function"]} for t in tools],
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")

                # Robust fallback if set_trip_core is called without required args
                if tc.function.name == "set_trip_core" and (not args or "pickup" not in args or "dropoff" not in args):
                    last_user_text = user
                    pair = _resolve_place_pair_from_text(last_user_text) or _resolve_place_pair_from_text(
                        messages[-3]["content"] if len(messages) >= 3 and messages[-3]["role"] == "user" else ""
                    )
                    if pair:
                        args = {
                            "pickup": {
                                "lat": pair["pickup"]["lat"],
                                "lng": pair["pickup"]["lng"],
                                "address": pair["pickup"]["address"],
                            },
                            "dropoff": {
                                "lat": pair["dropoff"]["lat"],
                                "lng": pair["dropoff"]["lng"],
                                "address": pair["dropoff"]["address"],
                            },
                            "pickup_address": pair["pickup"]["address"],
                            "destination_address": pair["dropoff"]["address"],
                        }

                try:
                    result = eval(f"tool_{tc.function.name}")(**args)
                except TypeError as e:
                    result = {"ok": False, "error": f"tool_{tc.function.name} invocation error", "details": str(e)}
                except NameError:
                    result = call_tool(tc.function.name, args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": json.dumps(result),
                })

            follow = client.chat.completions.create(model=MODEL, messages=messages)
            final_msg = follow.choices[0].message
            print("LumiDrive:", final_msg.content, "\n")
            messages.append({"role": "assistant", "content": final_msg.content})
        else:
            print("LumiDrive:", msg.content, "\n")
            messages.append({"role": "assistant", "content": msg.content})

if __name__ == "__main__":
    try:
        chat_loop()
    except KeyboardInterrupt:
        print("\nBye!")
