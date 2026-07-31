import asyncio
from typing import Any, Dict
import os
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Vehicle Details Master Aggregator API")

# Allow CORS for front-end access
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
    """Helper to pick first valid string or return N/A."""
    for v in values:
        if v is not None and str(v).strip().upper() not in ["NONE", "NULL", "NA", "N/A", "", "FALSE"]:
            return str(v).strip()
    return "N/A"


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


def merge_and_compare_data(api1_data: Dict[str, Any], api2_data: Dict[str, Any], vehicle_no: str) -> Dict[str, Any]:
    # Raw Sub-Dictionaries
    a1_res = api1_data.get("meta_data", {}).get("signzy_response", {}).get("result", {})
    a1_cust = api1_data.get("customer_details", {})
    a1_veh = api1_data.get("vehicle_details", {})
    a2_data = api2_data.get("data", {})

    # Owner Name Comparison Logic
    owner_api1 = clean_val(a1_cust.get("full_name"), a1_res.get("owner"))
    owner_api2 = clean_val(a2_data.get("owner"))

    owner_mismatch = False
    if owner_api1 != "N/A" and owner_api2 != "N/A":
        if owner_api1.upper() != owner_api2.upper():
            owner_mismatch = True

    final_owner_name = owner_api1 if owner_api1 != "N/A" else owner_api2

    # Address Comparison Logic
    addr_api1 = clean_val(a1_cust.get("communication_address", {}).get("address_line"))
    addr_api2 = clean_val(a2_data.get("presentAddress"))

    address_mismatch = False
    if addr_api1 != "N/A" and addr_api2 != "N/A":
        if addr_api1.upper() != addr_api2.upper():
            address_mismatch = True

    final_address = addr_api1 if len(str(addr_api1)) >= len(str(addr_api2)) else addr_api2

    # Model & Variant
    model = clean_val(a1_res.get("model"), a2_data.get("vehicle"))
    variant = clean_val(a2_data.get("variant"))
    full_model = f"{model} ({variant})" if variant != "N/A" and variant not in model else model

    return {
        "success": True,
        "searched_vehicle_number": vehicle_no.upper(),
        "mismatch_alerts": {
            "is_owner_mismatch": owner_mismatch,
            "is_address_mismatch": address_mismatch,
        },
        "data": {
            "registration_details": {
                "registration_number": clean_val(a1_res.get("regNo"), a2_data.get("regNo"), vehicle_no.upper()),
                "registration_date": clean_val(a1_veh.get("registration_date"), a1_res.get("regDate"), a2_data.get("regDate")),
                "rc_status": clean_val(a1_res.get("status"), "ACTIVE" if a2_data.get("dataStatus") == 1 else "N/A"),
                "status_as_on": clean_val(a1_res.get("statusAsOn")),
                "rto_code": clean_val(a1_res.get("rtoCode"), a2_data.get("rtoCode")),
                "rto_authority": clean_val(a1_res.get("regAuthority"), a2_data.get("regAuthority")),
                "rc_expiry_date": clean_val(a1_res.get("rcExpiryDate")),
                "tax_upto": clean_val(a1_res.get("vehicleTaxUpto"))
            },
            "owner_details": {
                "owner_name": final_owner_name,
                "owner_name_api1": owner_api1,
                "owner_name_api2": owner_api2,
                "father_name": clean_val(a1_res.get("ownerFatherName"), a2_data.get("ownerFatherName")),
                "ownership_count": clean_val(a1_res.get("ownerCount")),
                "customer_type": clean_val(api1_data.get("customer_type")),
                "present_address": final_address,
                "present_address_api1": addr_api1,
                "present_address_api2": addr_api2,
                "permanent_address": clean_val(a1_res.get("permanentAddress"), a2_data.get("permAddress")),
                "pincode": clean_val(a2_data.get("pincode"))
            },
            "specifications": {
                "manufacturer": clean_val(a1_res.get("vehicleManufacturerName"), a2_data.get("manufacturer")),
                "vehicle_model": full_model,
                "variant": variant,
                "vehicle_class": clean_val(a1_res.get("class"), a2_data.get("vehicleClass")),
                "vehicle_category": clean_val(a1_res.get("vehicleCategory")),
                "body_type": clean_val(a1_res.get("bodyType")),
                "fuel_type": clean_val(a1_res.get("type"), a2_data.get("fuelType")),
                "norms_type": clean_val(a1_res.get("normsType")),
                "chassis_number": clean_val(api1_data.get("chassis_number"), a2_data.get("chassis")),
                "engine_number": clean_val(api1_data.get("engine_number"), a2_data.get("engine")),
                "cubic_capacity": clean_val(a1_res.get("vehicleCubicCapacity"), a2_data.get("cubicCapacity")),
                "cylinders_no": clean_val(a1_res.get("vehicleCylindersNo")),
                "vehicle_color": clean_val(a1_res.get("vehicleColour"), a1_veh.get("vehicle_color")),
                "manufactured_month_year": clean_val(a1_res.get("vehicleManufacturingMonthYear"), a2_data.get("manufacturerMonthYear")),
                "unladen_weight": clean_val(a1_res.get("unladenWeight")),
                "gross_vehicle_weight": clean_val(a1_res.get("grossVehicleWeight")),
                "wheelbase": clean_val(a1_res.get("wheelbase")),
                "seating_capacity": clean_val(a1_res.get("vehicleSeatCapacity"), a2_data.get("seatCapacity"))
            },
            "compliance_and_insurance": {
                "insurance_company": clean_val(a1_res.get("vehicleInsuranceCompanyName"), a2_data.get("insuranceCompanyName")),
                "insurance_policy_number": clean_val(a1_res.get("vehicleInsurancePolicyNumber"), a2_data.get("insurancePolicyNumber")),
                "insurance_expiry": clean_val(api1_data.get("previous_policy_exp_date"), a2_data.get("insuranceUpto")),
                "puc_number": clean_val(a1_res.get("puccNumber"), a2_data.get("puccNumber")),
                "puc_expiry": clean_val(a1_res.get("puccUpto"), a2_data.get("puccValidUpto")),
                "financer_name": clean_val(a1_res.get("rcFinancer"), a2_data.get("financerName")),
                "is_financed": clean_val(a1_veh.get("is_vehicle_financed"))
            },
            "permits_and_status": {
                "is_commercial": clean_val(api1_data.get("is_commercial"), a2_data.get("isCommercial")),
                "blacklist_status": clean_val(a1_res.get("blacklistStatus")),
                "blacklist_details": a1_res.get("blacklistDetails", []),
                "challan_details": a1_res.get("challanDetails", []),
                "permit_number": clean_val(a1_res.get("permitNumber")),
                "permit_type": clean_val(a1_res.get("permitType")),
                "permit_valid_upto": clean_val(a1_res.get("permitValidUpto")),
                "national_permit_number": clean_val(a1_res.get("nationalPermitNumber")),
                "noc_details": clean_val(a1_res.get("nocDetails"))
            }
        }
    }


@app.get("/")
def home():
    return {
        "status": "Online",
        "message": "Vehicle Details Master API is running successfully.",
        "usage": "GET /api/v1/vehicle/{vehicle_number}"
    }


@app.get("/api/v1/vehicle/{vehicle_no}")
async def get_master_vehicle_data(vehicle_no: str):
    clean_vno = vehicle_no.replace(" ", "").replace("-", "").upper()
    async with httpx.AsyncClient() as client:
        api1_resp, api2_resp = await asyncio.gather(
            fetch_api_1(client, clean_vno),
            fetch_api_2(client, clean_vno)
        )
    return merge_and_compare_data(api1_resp, api2_resp, clean_vno)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
