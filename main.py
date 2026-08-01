from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, Any, Optional

app = FastAPI(
    title="RC Data Normalizer API",
    description="API to parse and normalize RC details from API 1 and API 2 formats",
    version="1.0.0"
)

# ------------------------------------------------------------------
# Normalization Logic
# ------------------------------------------------------------------

def get_val(data: Any, *keys, default="NA") -> str:
    """Helper function to safely extract deep nested dictionary values."""
    curr = data
    for k in keys:
        if isinstance(curr, dict) and k in curr and curr[k] is not None:
            curr = curr[k]
        else:
            return default
    return str(curr) if curr != "" else default


def normalize_rc_data(raw_data: Dict[str, Any], input_reg_no: str = "NA") -> Dict[str, Any]:
    """
    Parses and normalizes raw JSON response from API 1 or API 2 
    into a standardized RC output dictionary.
    """
    # Standardized Output Blueprint
    result = {
        "id": 2141636,
        "status": "SUCCESS",
        "rto": "NA",
        "reg_no": input_reg_no,
        "pb_vehicle_code": "0",
        "regn_dt": "NA",
        "chasi_no": "NA",
        "engine_no": "NA",
        "owner_name": "NA",
        "owner_1_name": "NA",
        "owner_2_name": "NA",
        "owner_transfer_detected": False,
        "vh_class": "NA",
        "vehicle_category": "NA",
        "vehicle_model": "NA",
        "variant": "NA",
        "is_commercial": False,
        "fuel_type": "NA",
        "maker": "NA",
        "vehicle_age": "NA",
        "insUpto": "NA",
        "state": "NA",
        "policy_no": "NA",
        "puc_no": "NA",
        "puc_upto": "NA",
        "insurance_comp": "NA",
        "financer_name": "NA",
        "is_financed": "False",
        "source": "PARIVAHAN_SERVICE_GATEWAY",
        "maker_modal": "NA",
        "father_name": "NA",
        "address": "NA",
        "address_1": "NA",
        "address_2": "NA",
        "owner_sr_no": "1",
        "vehicle_color": "NA",
        "fitness_upto": "NA",
        "no_of_seats": "NA",
        "fuel_norms": "NA",
        "mobile_no": "NA",
        "noc_details": "NA",
        "blacklist_status": "Clean",
        "blacklist_details": [],
        "manufactured_month_year": "NA",
        "unladen_weight": "NA",
        "gross_vehicle_weight": "NA",
        "wheelbase": "NA",
        "cylinder_count": "NA",
        "cubic_capacity": "NA",
        "rto_code": "NA",
        "tax_valid_upto": "NA",
        "permit_details": {
            "permit_number": "NA",
            "permit_type": "NA",
            "permit_valid_upto": "NA"
        }
    }

    # ==========================================
    # PARSING LOGIC FOR API 1 FORMAT
    # ==========================================
    if "data" in raw_data and isinstance(raw_data["data"], dict) and "chassis" in raw_data["data"]:
        d = raw_data["data"]
        result["reg_no"] = d.get("regNo", input_reg_no)
        result["chasi_no"] = d.get("chassis", "NA")
        result["engine_no"] = d.get("engine", "NA")
        result["owner_name"] = d.get("owner", "NA")
        result["father_name"] = d.get("ownerFatherName", "NA")
        result["regn_dt"] = d.get("regDate", "NA")
        result["maker"] = d.get("manufacturer", "NA")
        result["vehicle_model"] = d.get("vehicle", "NA")
        result["variant"] = d.get("variant", "NA")
        result["maker_modal"] = f"{result['maker']} {result['vehicle_model']}".strip()
        result["vh_class"] = d.get("vehicleClass", "NA")
        result["vehicle_category"] = d.get("vehicleType", "NA")
        result["fuel_type"] = d.get("fuelType", "NA")
        result["is_commercial"] = d.get("isCommercial", False)
        
        # Insurance & PUC
        result["insurance_comp"] = d.get("insuranceCompanyName", "NA")
        result["policy_no"] = d.get("insurancePolicyNumber", "NA")
        result["insUpto"] = d.get("insuranceUpto", "NA")
        result["puc_no"] = d.get("puccNumber", "NA")
        result["puc_upto"] = d.get("puccValidUpto", "NA")
        
        # Financer & Address
        result["financer_name"] = d.get("financerName", "NA")
        result["is_financed"] = "True" if result["financer_name"] != "NA" else "False"
        result["address"] = d.get("presentAddress") or d.get("permAddress") or "NA"
        result["address_1"] = d.get("presentAddress", "NA")
        result["address_2"] = d.get("permAddress", "NA")
        
        # Technical Specs & RTO
        result["no_of_seats"] = str(d.get("seatCapacity", "NA"))
        result["cubic_capacity"] = str(d.get("cubicCapacity", "NA"))
        result["rto_code"] = d.get("rtoCode", "NA")
        result["rto"] = get_val(d, "rtoData", "rtoName")
        result["state"] = get_val(d, "rtoData", "statename")
        
        # Manufacturing Date
        mfg = d.get("manufacturerMonthYear", "NA")
        if mfg == "NA" and "manufacturerYear" in d:
            mfg = str(d["manufacturerYear"])
        result["manufactured_month_year"] = mfg

    # ==========================================
    # PARSING LOGIC FOR API 2 FORMAT
    # ==========================================
    elif "meta_data" in raw_data or "chassis_number" in raw_data:
        res = raw_data.get("meta_data", {}).get("signzy_response", {}).get("result", {})
        cust = raw_data.get("customer_details", {})
        v_det = raw_data.get("vehicle_details", {})

        # Primary Identifiers
        result["reg_no"] = raw_data.get("registration_number", get_val(res, "regNo", default=input_reg_no)).replace("-", "")
        result["chasi_no"] = raw_data.get("chassis_number", get_val(res, "chassis"))
        result["engine_no"] = raw_data.get("engine_number", get_val(res, "engine"))
        
        # Owner & Father
        result["owner_name"] = cust.get("full_name") or get_val(res, "owner")
        result["father_name"] = get_val(res, "ownerFatherName", default=get_val(raw_data, "nominee_details", "name"))
        result["owner_sr_no"] = get_val(res, "ownerCount", default="1")
        
        # Registration & Age
        result["regn_dt"] = v_det.get("registration_date") or get_val(res, "regDate")
        
        # Manufacturing Month/Year
        mfg_my = get_val(res, "vehicleManufacturingMonthYear")
        if mfg_my == "NA":
            m_m = raw_data.get("manufactured_month")
            m_y = raw_data.get("manufactured_year")
            if m_m and m_y:
                mfg_my = f"{m_m:02d}/{m_y}"
        result["manufactured_month_year"] = mfg_my

        # Vehicle Info & Class
        result["maker"] = get_val(res, "vehicleManufacturerName")
        result["vehicle_model"] = get_val(res, "model")
        result["maker_modal"] = f"{result['maker']} {result['vehicle_model']}".strip()
        result["vh_class"] = get_val(res, "class")
        result["vehicle_category"] = get_val(res, "vehicleCategory")
        result["fuel_type"] = get_val(res, "type")
        result["vehicle_color"] = v_det.get("vehicle_color") or get_val(res, "vehicleColour")
        result["is_commercial"] = raw_data.get("is_commercial", False)
        
        # Variant Handling (Extract first variant if score exists)
        variants = get_val(res, "mappings", "variantIds", default=[])
        if isinstance(variants, list) and len(variants) > 0:
            result["variant"] = str(variants[0].get("variantId", "NA"))

        # Insurance & PUC
        result["insurance_comp"] = get_val(res, "vehicleInsuranceCompanyName")
        result["policy_no"] = raw_data.get("previous_policy_number") or get_val(res, "vehicleInsurancePolicyNumber")
        result["insUpto"] = raw_data.get("previous_policy_exp_date") or get_val(res, "vehicleInsuranceUpto")
        result["puc_no"] = get_val(res, "puccNumber")
        result["puc_upto"] = get_val(res, "puccUpto")
        
        # Financer & Address
        result["financer_name"] = get_val(res, "rcFinancer")
        result["is_financed"] = "True" if v_det.get("is_vehicle_financed") or result["financer_name"] != "NA" else "False"
        result["address"] = get_val(cust, "communication_address", "address_line", default=get_val(res, "presentAddress"))
        result["address_1"] = get_val(cust, "communication_address", "address_line")
        result["address_2"] = get_val(res, "permanentAddress")

        # Technical Specs & RTO
        result["no_of_seats"] = get_val(res, "vehicleSeatCapacity")
        result["cubic_capacity"] = get_val(res, "vehicleCubicCapacity")
        result["gross_vehicle_weight"] = get_val(res, "grossVehicleWeight")
        result["unladen_weight"] = get_val(res, "unladenWeight")
        result["wheelbase"] = get_val(res, "wheelbase")
        result["cylinder_count"] = get_val(res, "vehicleCylindersNo")
        result["fuel_norms"] = get_val(res, "normsType")
        result["tax_valid_upto"] = get_val(res, "vehicleTaxUpto")
        result["rto_code"] = raw_data.get("rb_rto_code") or get_val(res, "rtoCode")
        result["rto"] = get_val(res, "regAuthority")

        # Permit details
        result["permit_details"] = {
            "permit_number": get_val(res, "permitNumber"),
            "permit_type": get_val(res, "permitType"),
            "permit_valid_upto": get_val(res, "permitValidUpto")
        }

    # Final Sanitization: Replace empty strings with "NA"
    for k, v in result.items():
        if v == "" or v is None:
            result[k] = "NA"

    return result

# ------------------------------------------------------------------
# FastAPI Routes
# ------------------------------------------------------------------

@app.get("/")
def home():
    return {"status": "Active", "message": "RC Normalizer API is running smoothly!"}


@app.post("/normalize-rc")
def process_rc_json(payload: Dict[str, Any] = Body(...)):
    """
    Accepts raw JSON from API 1 or API 2 and returns normalized RC details.
    """
    try:
        normalized_output = normalize_rc_data(payload)
        return {
            "status": True,
            "message": "Data normalized successfully",
            "rc_details": normalized_output
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse JSON data: {str(e)}")

# ------------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
