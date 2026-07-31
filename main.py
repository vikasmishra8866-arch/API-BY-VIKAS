import asyncio
from typing import Any, Dict
import os
import re
from difflib import SequenceMatcher
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Parivahan Vehicle Details Master API")

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API1_BASE_URL = "https://unsalubriously-unfragrant-rosetta.ngrok-free.dev/api/vehicle-details-only"
API2_BASE_URL = "https://cjpen.vercel.app/vehicle"


def clean_val(*values: Any) -> str:
    """Returns the first non-null/non-empty string or 'NA'."""
    for v in values:
        if v is not None:
            val_str = str(v).strip()
            if val_str.upper() not in ["NONE", "NULL", "NA", "N/A", "", "FALSE"]:
                return val_str
    return "NA"


def clean_name_for_comparison(name: str) -> str:
    """Cleans owner name for accurate string comparison."""
    if not name or name == "NA":
        return ""
    # Remove titles, punctuation, and extra spaces
    cleaned = re.sub(r'\b(MR|MRS|MS|DR|M/S|SHRI|SMT)\b', '', name, flags=re.IGNORECASE)
    cleaned = re.sub(r'[^A-ZA-Z0-9\s]', '', cleaned)
    return ' '.join(cleaned.upper().split())


def calculate_similarity(name1: str, name2: str) -> float:
    """Calculates similarity percentage between two names."""
    c1 = clean_name_for_comparison(name1)
    c2 = clean_name_for_comparison(name2)
    if not c1 or not c2:
        return 0.0
    return SequenceMatcher(None, c1, c2).ratio()


def get_latest_owner_sr_no(sr1: Any, sr2: Any) -> str:
    """Picks the highest owner count number between both APIs."""
    nums = []
    for s in [sr1, sr2]:
        val = clean_val(s)
        if val != "NA":
            match = re.search(r'\d+', val)
            if match:
                nums.append(int(match.group()))
    if nums:
        return str(max(nums))
    return "1"


async def fetch_api_1(client: httpx.AsyncClient, vehicle_no: str) -> Dict[str, Any]:
    try:
        url = f"{API1_BASE_URL}?regn_no={vehicle_no}"
        headers = {"ngrok-skip-browser-warning": "true"}
        res = await client.get(url, headers=headers, timeout=12.0)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"API 1 Error: {e}")
    return {}


async def fetch_api_2(client: httpx.AsyncClient, vehicle_no: str) -> Dict[str, Any]:
    try:
        url = f"{API2_BASE_URL}/{vehicle_no}"
        res = await client.get(url, timeout=12.0)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"API 2 Error: {e}")
    return {}


def format_custom_json(api1_data: Dict[str, Any], api2_data: Dict[str, Any], vehicle_no: str) -> Dict[str, Any]:
    # Extract sub-dictionaries safely
    a1_res = api1_data.get("meta_data", {}).get("signzy_response", {}).get("result", {})
    a1_cust = api1_data.get("customer_details", {})
    a1_veh = api1_data.get("vehicle_details", {})
    a2_data = api2_data.get("data", {})

    # Extract Owners & Addresses
    owner_1 = clean_val(a1_cust.get("full_name"), a1_res.get("owner"))
    owner_2 = clean_val(a2_data.get("owner"))

    addr_1 = clean_val(a1_cust.get("communication_address", {}).get("address_line"), a1_res.get("permanentAddress"))
    addr_2 = clean_val(a2_data.get("presentAddress"), a2_data.get("permAddress"))

    # Compare Names
    similarity = calculate_similarity(owner_1, owner_2)
    is_same_owner = similarity >= 0.70  # 70% match threshold

    if owner_1 != "NA" and owner_2 != "NA" and not is_same_owner:
        # Transfer case / Different Owners
        final_owner = f"1st Owner: {owner_1} | 2nd Owner: {owner_2}"
        final_address = f"1st Owner Address: {addr_1} | 2nd Owner Address: {addr_2}"
        owner_transfer_detected = True
    else:
        # Same Owner or only one API provided the name
        final_owner = owner_1 if owner_1 != "NA" else owner_2
        # Pick the longer, more detailed address
        if addr_1 != "NA" and addr_2 != "NA":
            final_address = addr_1 if len(addr_1) >= len(addr_2) else addr_2
        else:
            final_address = addr_1 if addr_1 != "NA" else addr_2
        owner_transfer_detected = False

    # Owner Serial Count
    sr1 = a1_res.get("ownerCount")
    sr2 = a2_data.get("ownerCount")
    latest_sr_no = get_latest_owner_sr_no(sr1, sr2)

    # Models & Variants
    model = clean_val(a1_res.get("model"), a2_data.get("vehicle"))
    variant = clean_val(a2_data.get("variant"))
    maker = clean_val(a1_res.get("vehicleManufacturerName"), a2_data.get("manufacturer"))

    data_payload = {
        "id": 2141636,
        "status": "SUCCESS",
        "rto": clean_val(a1_res.get("regAuthority"), a2_data.get("regAuthority")),
        "reg_no": vehicle_no.upper(),
        "pb_vehicle_code": "0",
        "regn_dt": clean_val(a1_veh.get("registration_date"), a1_res.get("regDate"), a2_data.get("regDate")),
        "chasi_no": clean_val(api1_data.get("chassis_number"), a2_data.get("chassis")),
        "engine_no": clean_val(api1_data.get("engine_number"), a2_data.get("engine")),
        "owner_name": final_owner,
        "owner_1_name": owner_1,
        "owner_2_name": owner_2,
        "owner_transfer_detected": owner_transfer_detected,
        "vh_class": clean_val(a1_res.get("class"), a2_data.get("vehicleClass")),
        "vehicle_category": clean_val(a1_res.get("vehicleCategory"), "Two-Wheeler"),
        "vehicle_model": model,
        "variant": variant,
        "is_commercial": False if clean_val(api1_data.get("is_commercial")) in ["NA", "false", "False"] else True,
        "fuel_type": clean_val(a1_res.get("type"), a2_data.get("fuelType")),
        "maker": maker,
        "vehicle_age": clean_val(a1_res.get("vehicleAge")),
        "insUpto": clean_val(api1_data.get("previous_policy_exp_date"), a2_data.get("insuranceUpto")),
        "state": clean_val(a1_res.get("state")),
        "policy_no": clean_val(a1_res.get("vehicleInsurancePolicyNumber"), a2_data.get("insurancePolicyNumber")),
        "puc_no": clean_val(a1_res.get("puccNumber"), a2_data.get("puccNumber")),
        "puc_upto": clean_val(a1_res.get("puccUpto"), a2_data.get("puccValidUpto")),
        "insurance_comp": clean_val(a1_res.get("vehicleInsuranceCompanyName"), a2_data.get("insuranceCompanyName")),
        "financer_name": clean_val(a1_res.get("rcFinancer"), a2_data.get("financerName")),
        "is_financed": clean_val(a1_veh.get("is_vehicle_financed")),
        "source": "PARIVAHAN_SERVICE_GATEWAY",
        "maker_modal": f"{maker} {model}".strip(),
        "father_name": clean_val(a1_res.get("ownerFatherName"), a2_data.get("ownerFatherName")),
        "address": final_address,
        "address_1": addr_1,
        "address_2": addr_2,
        "owner_sr_no": latest_sr_no,
        "vehicle_color": clean_val(a1_res.get("vehicleColour"), a1_veh.get("vehicle_color")),
        "fitness_upto": clean_val(a1_res.get("rcExpiryDate")),
        "no_of_seats": clean_val(a1_res.get("vehicleSeatCapacity"), a2_data.get("seatCapacity"), "2"),
        "fuel_norms": clean_val(a1_res.get("normsType")),
        "mobile_no": "NA",
        "blacklist_status": clean_val(a1_res.get("blacklistStatus"), "Clean"),
        "blacklist_details": a1_res.get("blacklistDetails", []),
        "permit_details": {
            "permit_number": clean_val(a1_res.get("permitNumber")),
            "permit_type": clean_val(a1_res.get("permitType")),
            "permit_valid_upto": clean_val(a1_res.get("permitValidUpto"))
        }
    }

    return {
        "query": vehicle_no.upper(),
        "rc_details": {
            "status": True,
            "response_code": 200,
            "response_message": "Fetched [ PARIVAHAN SERVICE ]",
            "data": [data_payload]
        }
    }


@app.get("/")
def home():
    return {
        "status": "Online",
        "message": "Parivahan RC Master API Gateway is active."
    }


@app.get("/api/v1/vehicle/{vehicle_no}")
async def get_vehicle_json(vehicle_no: str):
    clean_vno = vehicle_no.replace(" ", "").replace("-", "").upper()
    async with httpx.AsyncClient() as client:
        api1_resp, api2_resp = await asyncio.gather(
            fetch_api_1(client, clean_vno),
            fetch_api_2(client, clean_vno)
        )
    return format_custom_json(api1_resp, api2_resp, clean_vno)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
