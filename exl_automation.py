import json
import os
import re
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# --- CONFIGURATION ---
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
EXL_LINK = "https://exlphilippines.talkpush.com/careers/4-customer-service/apply?source=Edward+Mapa+Belacse+%28Olympuz%29&redirect_url=https%3A%2F%2Ftalkpu.sh%2Ft%2F5HDwH000n&refresh_rate=1"

def setup_gspread():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    # Cursor secrets inject JSON into GOOGLE_APPLICATION_CREDENTIALS;
    # local runs may still use a path to a service-account file.
    if SERVICE_ACCOUNT_FILE.strip().startswith("{"):
        info = json.loads(SERVICE_ACCOUNT_FILE)
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds)

def format_exl_phone(phone_str):
    digits = re.sub(r'\D', '', str(phone_str))
    if not digits:
        return "9171111111"
    if digits.startswith("903"):
        return "917" + digits[3:]
    if len(digits) >= 10:
        return "09" + digits[-9:]
    return "09" + digits.zfill(9)

def get_exl_site(location):
    loc = str(location).lower().strip()
    if loc in ["philippines", "ph", "phils", "parañaque"]: return "Pasay"
    if any(x in loc for x in ["panay", "negros occidental", "zamboanga", "palawan", "iloilo"]): return "Iloilo"
    if any(x in loc for x in ["laguna", "batangas", "quezon", "bicol", "cavite", "alabang", "muntinlupa"]): return "Alabang"
    if any(x in loc for x in ["cebu", "visayas", "mindanao", "cagayan de oro"]): return "Cebu"
    return "QC" # Default for Metro Manila north / Central Luzon

def run_exl_pipeline():
    gc = setup_gspread()
    doc = gc.open_by_url("https://docs.google.com/spreadsheets/d/1NoRX955F0dpxMReiC-6lcd3hgxFDccS3H9hzabTQghE/edit")
    
    # Target Tabs, target column index (1-based), and starting row
    tabs = [
        {"name": "MODERN TRACTION", "col": 22, "start": 879}, # Column V
        {"name": "VALID CONSENT - TP, FVR & EXL", "col": 16, "start": 405}, # Column P
        {"name": "JOBSTREET", "col": 20, "start": 181} # Column T
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        for tab_info in tabs:
            ws = doc.worksheet(tab_info["name"])
            data = ws.get_all_values()
            
            # Verify header exactly matches EXL in the target column before writing
            if len(data) > 0 and "EXL" not in str(data[0][tab_info["col"]-1]).upper():
                continue

            for row_idx in range(tab_info["start"] - 1, len(data)):
                row = data[row_idx]
                if len(row) < tab_info["col"]: 
                    row.extend([""] * (tab_info["col"] - len(row)))
                
                # Re-read specific cell right before processing to ensure it hasn't changed
                current_remark = ws.cell(row_idx + 1, tab_info["col"]).value or ""
                if current_remark.strip():
                    continue

                # Map columns based on tab layout
                is_valid_consent_tab = (tab_info["name"] == "VALID CONSENT - TP, FVR & EXL")
                
                if is_valid_consent_tab:
                    pref = row[9].strip() # Column J
                    loc = row[3].strip()  # Column D
                    email = row[4].strip() # Column E
                    first_name = row[1].strip() # Column B
                else:
                    pref = row[11].strip() # Column L
                    loc = row[6].strip()  # Column G
                    email = row[5].strip() # Column F
                    first_name = row[2].strip() # Column C

                # 1. Check preference
                if "EXL" not in pref and "All of the above" not in pref:
                    ws.update_cell(row_idx + 1, tab_info["col"], "Executive Team / N")
                    continue

                # 2. Check incomplete information
                email_lower = email.lower()
                if not email or "@" not in email or email_lower.endswith("g,ail.com") or email_lower.endswith(".con") or loc in ["N/A", ""] or not first_name:
                    ws.update_cell(row_idx + 1, tab_info["col"], "Incomplete Information")
                    continue
                
                # 3. Check for shared towns/unclear provinces (Exceptions included)
                loc_lower = loc.lower()
                unclear_towns = ["san jose", "san luis", "concepcion", "rosario", "santa maria", "naga"]
                if loc_lower in unclear_towns and loc_lower not in ["san francisco", "naga city", "city of naga"]:
                    continue # Leave blank and hold for manual review

                # 4. Check for locations abroad
                if "abroad" in loc_lower or loc_lower in ["chennai", "india", "waterbury", "us"]:
                    ws.update_cell(row_idx + 1, tab_info["col"], "INVALID")
                    continue

                # Upload via Playwright
                # (You must add the exact Talkpush chatbot selectors here to match the form answers)
                page = context.new_page()
                try:
                    page.goto(EXL_LINK, timeout=60000)
                    page.wait_for_load_state("networkidle")
                    
                    # NOTE: Stop automation when the chatbot asks for a video or audio recording.
                    
                    ws.update_cell(row_idx + 1, tab_info["col"], "Executive Team / Y")
                except Exception as e:
                    print(f"Failed EXL submission for Row {row_idx + 1} ({tab_info['name']}): {e}")
                finally:
                    page.close()

        browser.close()

if __name__ == "__main__":
    run_exl_pipeline()
