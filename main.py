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
    """Calculates vehicle age automatically and precisely from registration date string."""
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

    if today.day < reg_date.day:
        months -= 1

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

    latest_sr_no = get_latest_owner_sr_no(a1_res.get("ownerCount"), a2_data.get("ownerCount"))
    sr_num = int(latest_sr_no) if latest_sr_no.isdigit() else 1

    # Extract all possible owner names across fields
    cust_name = clean_val(a1_cust.get("full_name"))
    signzy_name = clean_val(a1_res.get("owner"))
    api2_name = clean_val(a2_data.get("owner"))

    # Collect unique names in order of arrival
    names_list = []
    for nm in [cust_name, signzy_name, api2_name]:
        if nm != "NA":
            is_dup = False
            for existing in names_list:
                if calculate_similarity(nm, existing) >= 0.70:
                    is_dup = True
                    break
            if not is_dup:
                names_list.append(nm)

    # Address extraction
    addr_1 = clean_val(a1_cust.get("communication_address", {}).get("address_line"), a1_res.get("permanentAddress"))
    addr_2 = clean_val(a2_data.get("presentAddress"), a2_data.get("permAddress"))

    # Financer details extraction across APIs
    financer_api1 = clean_val(a1_res.get("rcFinancer"), a1_veh.get("financer_name"))
    financer_api2 = clean_val(a2_data.get("financerName"))

    # If 2 or more distinct names are detected OR owner count is explicitly 2+, mark transfer
    if len(names_list) >= 2 or sr_num >= 2:
        owner_transfer_detected = True
        
        if len(names_list) >= 2:
            out_owner_1 = names_list[0]
            out_owner_2 = names_list[1]
        elif len(names_list) == 1:
            out_owner_1 = "NA"
            out_owner_2 = names_list[0]
        else:
            out_owner_1 = "NA"
            out_owner_2 = "NA"

        final_owner = f"1st Owner: {out_owner_1} | 2nd Owner: {out_owner_2}"
        
        # Format addresses based on 1st and 2nd owner
        out_addr_1 = addr_1 if addr_1 != "NA" else "NA"
        out_addr_2 = addr_2 if addr_2 != "NA" else (addr_1 if addr_1 != "NA" else "NA")

        if out_addr_1 != "NA" and out_addr_2 != "NA" and out_addr_1 != out_addr_2:
            final_address = f"1st Owner Address: {out_addr_1} | 2nd Owner Address: {out_addr_2}"
        elif out_addr_1 != "NA":
            final_address = f"1st Owner Address: {out_addr_1} | 2nd Owner Address: {out_addr_2}"
        else:
            final_address = out_addr_1 if out_addr_1 != "NA" else out_addr_2

        # Financer Mapping according to Owner Count / Transfer
        fin1 = financer_api1 if financer_api1 != "NA" else "NA"
        fin2 = financer_api2 if (financer_api2 != "NA" and financer_api2 != financer_api1) else "NA"

        if fin1 != "NA" or fin2 != "NA":
            financer = f"1st Owner Financer: {fin1} | 2nd Owner Financer: {fin2}"
            is_financed_status = "True"
        else:
            financer = "NA"
            is_financed_status = "False"

    else:
        owner_transfer_detected = False
        out_owner_1 = names_list[0] if names_list else "NA"
        out_owner_2 = "NA"
        final_owner = out_owner_1

        if addr_1 != "NA" and addr_2 != "NA":
            final_address = addr_1 if len(addr_1) >= len(addr_2) else addr_2
        else:
            final_address = addr_1 if addr_1 != "NA" else addr_2

        out_addr_1 = final_address
        out_addr_2 = "NA"

        # Single Owner Financer Logic
        financer = clean_val(a1_res.get("rcFinancer"), a2_data.get("financerName"), a1_veh.get("financer_name"))
        raw_financed = clean_val(a1_veh.get("is_vehicle_financed"), a1_res.get("isFinanced"))
        if raw_financed != "NA":
            is_financed_status = raw_financed
        else:
            is_financed_status = "False" if financer.upper() in ["ON CASH", "CASH", "NA"] else "True"

    reg_date = clean_val(a1_veh.get("registration_date"), a1_res.get("regDate"), a2_data.get("regDate"))
    vehicle_age = calculate_vehicle_age(reg_date)
    if vehicle_age == "NA":
        vehicle_age = clean_val(a1_res.get("vehicleAge"))

    vh_class = clean_val(a1_res.get("class"), a2_data.get("vehicleClass"))
    raw_maker = clean_val(a1_res.get("vehicleManufacturerName"), a2_data.get("manufacturer"))
    maker = normalize_maker(raw_maker, vh_class)

    model = clean_val(a1_res.get("model"), a2_data.get("vehicle"))
    variant = clean_val(a2_data.get("variant"))

    raw_comm = str(clean_val(api1_data.get("is_commercial"), a1_res.get("isCommercial"))).upper()
    vh_class_upper = vh_class.upper()
    if raw_comm in ["TRUE", "1", "YES", "COMMERCIAL"]:
        is_commercial = True
    elif any(k in vh_class_upper for k in ["GOODS", "COMMERCIAL", "TAXI", "PERMIT", "3WT", "PASSENGER"]):
        is_commercial = True
    else:
        is_commercial = False

    # PUC Details Fallback
    puc_no = clean_val(a1_res.get("puccNumber"), a1_veh.get("puc_number"), a2_data.get("puccNumber"), a2_data.get("pucNumber"))
    puc_upto = clean_val(a1_res.get("puccUpto"), a1_veh.get("puc_expiry"), a2_data.get("puccValidUpto"))

    # Technical & Specs Extraction across APIs
    mfg_month_year = clean_val(a1_res.get("vehicleManufacturingMonthYear"), a2_data.get("manufacturingDate"), a2_data.get("manufacturedMonthYear"))
    unladen_wt = clean_val(a1_res.get("unladenWeight"), a2_data.get("unladenWeight"))
    gross_wt = clean_val(a1_res.get("grossVehicleWeight"), a2_data.get("grossVehicleWeight"))
    w_base = clean_val(a1_res.get("wheelbase"), a2_data.get("wheelbase"))
    cyl_count = clean_val(a1_res.get("vehicleCylindersNo"), a2_data.get("cylindersNo"), a2_data.get("cylinderCount"))
    cubic_cap = clean_val(a1_res.get("vehicleCubicCapacity"), a2_data.get("cubicCapacity"), a1_veh.get("cubic_capacity"))
    rto_cd = clean_val(api1_data.get("rb_rto_code"), a1_res.get("rtoCode"), a2_data.get("rtoCode"))
    tax_upto = clean_val(a1_res.get("vehicleTaxUpto"), a2_data.get("taxValidUpto"), a2_data.get("taxUpto"))

    # Clean Maker-Model combination
    if maker == "NA" and model == "NA":
        maker_modal = "NA"
    elif maker != "NA" and model != "NA":
        maker_modal = f"{maker} {model}".strip()
    else:
        maker_modal = maker if maker != "NA" else model

    # Smart Vehicle Category Detection
    raw_cat = clean_val(a1_res.get("vehicleCategory"), a2_data.get("vehicleCategory"))
    if raw_cat == "NA":
        vh_upper = vh_class.upper()
        if any(k in vh_upper for k in ["THREE WHEELER", "3WT", "3WN", "3 WHEELER", "AUTO", "TRICYCLE"]):
            raw_cat = "3WN"
        elif any(k in vh_upper for k in ["CAR", "LMV", "SUV", "MOTOR CAR", "QUADRICYCLE", "GOODS"]):
            raw_cat = "4WN"
        elif any(k in vh_upper for k in ["SCOOTER", "M-CYCLE", "MOTORCYCLE", "TWO WHEELER", "2WN"]):
            raw_cat = "2WN"
        else:
            raw_cat = "4WN" if "CAR" in vh_upper or "LMV" in vh_upper else "2WN"

    # RTO & State Fallback Logic
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
        "manufactured_month_year": mfg_month_year,
        "unladen_weight": unladen_wt,
        "gross_vehicle_weight": gross_wt,
        "wheelbase": w_base,
        "cylinder_count": cyl_count,
        "cubic_capacity": cubic_cap,
        "rto_code": rto_cd,
        "tax_valid_upto": tax_upto,
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
