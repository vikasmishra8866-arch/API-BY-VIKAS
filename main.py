import asyncio
from typing import Any, Dict
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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


def calculate_vehicle_age(reg_date_str: str) -> str:
    """Calculates vehicle age automatically from registration date string."""
    if not reg_date_str or reg_date_str == "NA":
        return "NA"
    
    date_formats = ["%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"]
    reg_date = None
    
    for fmt in date_formats:
        try:
            reg_date = datetime.strptime(reg_date_str.strip(), fmt)
            break
        except ValueError:
            continue

    if not reg_date:
        return "NA"

    today = datetime.now()
    years = today.year - reg_date.year
    months = today.month - reg_date.month

    if months < 0:
        years -= 1
        months += 12

    parts = []
    if years > 0:
        parts.append(f"{years} year{'s' if years > 1 else ''}")
    if months > 0:
        parts.append(f"{months} month{'s' if months > 1 else ''}")

    return ", ".join(parts) if parts else "Less than a month"


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


def normalize_maker(maker_str: str, vh_class: str) -> str:
    """Corrects known maker name mismatches based on vehicle class."""
    maker = maker_str.upper()
    vh = vh_class.upper()
    if "HONDA CARS" in maker and ("SCOOTER" in vh or "M-CYCLE" in vh or "2WN" in vh):
        return "HONDA MOTORCYCLE & SCOOTER INDIA"
    return maker_str


async def fetch_api_1(client: httpx.AsyncClient, vehicle_no: str) -> Dict[str, Any]:
    try:
        url = f"{API1_BASE_URL}?regn_no={vehicle_no}"
        headers = {"ngrok-skip-browser-warning": "true"}
        res = await client.get(url, headers=headers, timeout=12.0)
        print(f"[API 1 Status]: {res.status_code}")
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"API 1 Error: {e}")
    return {}


async def fetch_api_2(client: httpx.AsyncClient, vehicle_no: str) -> Dict[str, Any]:
    try:
        url = f"{API2_BASE_URL}/{vehicle_no}"
        res = await client.get(url, timeout=12.0)
        print(f"[API 2 Status]: {res.status_code}")
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"API 2 Error: {e}")
    return {}


def format_custom_json(api1_data: Dict[str, Any], api2_data: Dict[str, Any], vehicle_no: str) -> Dict[str, Any]:
    a1_res = api1_data.get("meta_data", {}).get("signzy_response", {}).get("result", {})
    a1_cust = api1_data.get("customer_details", {})
    a1_veh = api1_data.get("vehicle_details", {})
    a2_data = api2_data.get("data", {})

    # Priority preference set to active live gateway owner first
    owner_1 = clean_val(a1_res.get("owner"), a1_cust.get("full_name"))
    owner_2 = clean_val(a2_data.get("owner"))

    addr_1 = clean_val(a1_res.get("permanentAddress"), a1_cust.get("communication_address", {}).get("address_line"))
    addr_2 = clean_val(a2_data.get("presentAddress"), a2_data.get("permAddress"))

    similarity = calculate_similarity(owner_1, owner_2)
    is_same_owner = similarity >= 0.70

    if owner_1 != "NA" and owner_2 != "NA" and not is_same_owner:
        final_owner = f"1st Owner: {owner_1} | 2nd Owner: {owner_2}"
        out_owner_1 = owner_1
        out_owner_2 = owner_2
        final_address = f"1st Owner Address: {addr_1} | 2nd Owner Address: {addr_2}"
        out_addr_1 = addr_1
        out_addr_2 = addr_2
        owner_transfer_detected = True
    else:
        final_owner = owner_1 if owner_1 != "NA" else owner_2
        out_owner_1 = final_owner
        out_owner_2 = "NA"
        
        if addr_1 != "NA" and addr_2 != "NA":
            final_address = addr_1 if len(addr_1) >= len(addr_2) else addr_2
        else:
            final_address = addr_1 if addr_1 != "NA" else addr_2
            
        out_addr_1 = final_address
        out_addr_2 = "NA"
        owner_transfer_detected = False

    reg_date = clean_val(a1_veh.get("registration_date"), a1_res.get("regDate"), a2_data.get("regDate"))
    vehicle_age = clean_val(a1_res.get("vehicleAge"))
    if vehicle_age == "NA":
        vehicle_age = calculate_vehicle_age(reg_date)

    latest_sr_no = get_latest_owner_sr_no(a1_res.get("ownerCount"), a2_data.get("ownerCount"))

    vh_class = clean_val(a1_res.get("class"), a2_data.get("vehicleClass"))
    raw_maker = clean_val(a1_res.get("vehicleManufacturerName"), a2_data.get("manufacturer"))
    maker = normalize_maker(raw_maker, vh_class)

    model = clean_val(a1_res.get("model"), a2_data.get("vehicle"))
    variant = clean_val(a2_data.get("variant"))

    raw_comm = str(clean_val(api1_data.get("is_commercial"), a1_res.get("isCommercial"))).upper()
    is_commercial = True if raw_comm in ["TRUE", "1", "YES", "COMMERCIAL"] else False

    # Financer & Hypothecation Check
    financer = clean_val(a1_res.get("rcFinancer"), a2_data.get("financerName"), a1_veh.get("financer_name"))
    raw_financed = clean_val(a1_veh.get("is_vehicle_financed"), a1_res.get("isFinanced"))
    if raw_financed != "NA":
        is_financed_status = raw_financed
    else:
        is_financed_status = "False" if financer.upper() in ["ON CASH", "CASH", "NA"] else "True"

    # PUC Details Fallback
    puc_no = clean_val(a1_res.get("puccNumber"), a1_veh.get("puc_number"), a2_data.get("puccNumber"), a2_data.get("pucNumber"))
    puc_upto = clean_val(a1_res.get("puccUpto"), a1_veh.get("puc_expiry"), a2_data.get("puccValidUpto"))

    # Clean Maker-Model combination
    if maker == "NA" and model == "NA":
        maker_modal = "NA"
    elif maker != "NA" and model != "NA":
        maker_modal = f"{maker} {model}".strip()
    else:
        maker_modal = maker if maker != "NA" else model

    # Smart Vehicle Category Detection (Fixes 2WN/4WN issue)
    raw_cat = clean_val(a1_res.get("vehicleCategory"), a2_data.get("vehicleCategory"))
    if raw_cat == "NA":
        vh_upper = vh_class.upper()
        if any(k in vh_upper for k in ["CAR", "LMV", "SUV", "MOTOR CAR", "QUADRICYCLE", "GOODS"]):
            raw_cat = "4WN"
        elif any(k in vh_upper for k in ["SCOOTER", "M-CYCLE", "MOTORCYCLE", "TWO WHEELER", "2WN"]):
            raw_cat = "2WN"
        else:
            raw_cat = "4WN" if "CAR" in vh_upper or "LMV" in vh_upper else "2WN"

    # RTO & State Fallback Logic (Fixes missing state when RTO has 'Surat, Gujarat')
    rto_val = clean_val(a1_res.get("regAuthority"), a2_data.get("regAuthority"))
    state_val = clean_val(a1_res.get("state"), a2_data.get("state"))
    if state_val == "NA" and rto_val != "NA" and "," in rto_val:
        state_val = rto_val.split(",")[-1].strip()

    data_payload = {
        "id": 2141636,
        "status": "SUCCESS",
        "rto": rto_val,
        "reg_no": vehicle_no.upper(),
        "pb_vehicle_code": "0",
        "regn_dt": reg_date,
        "chasi_no": clean_val(api1_data.get("chassis_number"), a2_data.get("chassis")),
        "engine_no": clean_val(api1_data.get("engine_number"), a2_data.get("engine")),
        "owner_name": final_owner,
        "owner_1_name": out_owner_1,
        "owner_2_name": out_owner_2,
        "owner_transfer_detected": owner_transfer_detected,
        "vh_class": vh_class,
        "vehicle_category": raw_cat,
        "vehicle_model": model,
        "variant": variant,
        "is_commercial": is_commercial,
        "fuel_type": clean_val(a1_res.get("type"), a2_data.get("fuelType")),
        "maker": maker,
        "vehicle_age": vehicle_age,
        "insUpto": clean_val(api1_data.get("previous_policy_exp_date"), a2_data.get("insuranceUpto")),
        "state": state_val,
        "policy_no": clean_val(a1_res.get("vehicleInsurancePolicyNumber"), a2_data.get("insurancePolicyNumber")),
        "puc_no": puc_no,
        "puc_upto": puc_upto,
        "insurance_comp": clean_val(a1_res.get("vehicleInsuranceCompanyName"), a2_data.get("insuranceCompanyName")),
        "financer_name": financer,
        "is_financed": is_financed_status,
        "source": "PARIVAHAN_SERVICE_GATEWAY",
        "maker_modal": maker_modal,
        "father_name": clean_val(a1_res.get("ownerFatherName"), a2_data.get("ownerFatherName")),
        "address": final_address,
        "address_1": out_addr_1,
        "address_2": out_addr_2,
        "owner_sr_no": latest_sr_no,
        "vehicle_color": clean_val(a1_res.get("vehicleColour"), a1_veh.get("vehicle_color")),
        "fitness_upto": clean_val(a1_res.get("rcExpiryDate")),
        "no_of_seats": clean_val(a1_res.get("vehicleSeatCapacity"), a2_data.get("seatCapacity"), "2"),
        "fuel_norms": clean_val(a1_res.get("normsType")),
        "mobile_no": "NA",
        "noc_details": clean_val(a1_res.get("nocDetails"), a2_data.get("nocDetails")),
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
    formatted_data = format_custom_json(api1_resp, api2_resp, clean_vno)
    return JSONResponse(content=formatted_data, headers={"Content-Type": "application/json; charset=utf-8"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
