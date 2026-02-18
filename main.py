import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
import time

# --- CONFIGURATION ---
GLOBAL_PASSWORD = st.secrets["general"]["password"]
ADMIN_PASSWORD = st.secrets["general"]["admin_password"]

def get_client():
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=5)
def fetch_data(sheet_name):
    client = get_client()
    sheet = client.open("Kingshot_Data").worksheet(sheet_name)
    return sheet.get_all_records()

# --- AUTHENTICATION ---
if "password_correct" not in st.session_state:
    st.session_state["password_correct"] = False

if not st.session_state["password_correct"]:
    pw = st.text_input("Enter Alliance Password", type="password")
    if st.button("Login"):
        if pw == GLOBAL_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

st.title("⚔️ Kingshot Vikings: Troop Swap")

try:
    roster_data = fetch_data("Roster")
    orders_data = fetch_data("Orders")
except Exception as e:
    st.error("Connection busy. Please refresh in 10 seconds.")
    st.stop()

# --- SIDEBAR: PLAYER ACTIONS ---
st.sidebar.header("Member Actions")
with st.sidebar.expander("Add/Update My Entry"):
    user = st.text_input("In-Game Username")
    status = st.radio("Status", ["Online", "Offline"])
    marches = st.slider("Marches you are sending", 4, 6, 5)
    inf_cav = st.number_input("Infantry + Cavalry Count", min_value=0, value=0, help="Higher numbers will be prioritized to receive 5+ marches.")
    
    if st.button("Submit Entry"):
        if user:
            with st.spinner("Saving..."):
                client = get_client()
                sheet = client.open("Kingshot_Data").worksheet("Roster")
                existing_idx = next((i for i, item in enumerate(roster_data) if item["Username"] == user), None)
                if existing_idx is not None:
                    sheet.delete_rows(existing_idx + 2)
                
                # Column order: Username, Status, Marches_Available, Inf_Cav
                sheet.append_row([user, status, marches, inf_cav])
                st.cache_data.clear()
                st.success(f"Saved {user}!")
                time.sleep(1)
                st.rerun()

with st.sidebar.expander("❌ Remove My Entry"):
    del_user = st.text_input("Confirm Username to Remove")
    if st.button("Delete My Info"):
        with st.spinner("Removing..."):
            client = get_client()
            sheet = client.open("Kingshot_Data").worksheet("Roster")
            existing_idx = next((i for i, item in enumerate(roster_data) if item["Username"] == del_user), None)
            if existing_idx is not None:
                sheet.delete_rows(existing_idx + 2)
                st.cache_data.clear()
                st.success("Removed.")
                time.sleep(1)
                st.rerun()

# --- MAIN AREA ---
tab1, tab2 = st.tabs(["Current Roster", "📜 SWAP ORDERS"])

with tab1:
    st.subheader(f"Registered Players: {len(roster_data)}")
    if roster_data:
        # Displaying with Strength column
        df_roster = pd.DataFrame(roster_data).sort_values(by="Inf_Cav", ascending=False)
        st.table(df_roster)
    else:
        st.info("Waiting for players...")

with tab2:
    if orders_data:
        st.header("📋 Alliance Swap Orders")
        df_disp = pd.DataFrame(orders_data).sort_values(by="From")
        st.table(df_disp)
    else:
        st.warning("Orders not yet generated.")

# --- ADMIN SECTION ---
st.markdown("---")
with st.expander("🛡️ Admin Controls"):
    admin_pw = st.text_input("Admin Password", type="password")
    
    if st.button("Generate & Publish Orders"):
        if admin_pw == ADMIN_PASSWORD:
            with st.spinner("Calculating Optimized Swaps..."):
                if len(roster_data) < 2:
                    st.error("Need more players!")
                else:
                    players = []
                    for p in roster_data:
                        players.append({
                            "Username": p["Username"],
                            "Status": p["Status"],
                            "Sends": int(p["Marches_Available"]),
                            "Inf_Cav": int(p.get("Inf_Cav", 0)),
                            "Receiving_Count": 0,
                            "History": []
                        })
                    
                    marches_to_assign = []
                    for p in players:
                        for _ in range(p["Sends"]):
                            marches_to_assign.append(p)
                    
                    random.shuffle(marches_to_assign)
                    marches_to_assign.sort(key=lambda x: x['Status'] == 'Online', reverse=True)

                    final_orders = []

                    def find_best_target(sender, target_pool, max_cap, prioritize_strength=False):
                        eligible = [
                            t for t in target_pool 
                            if t['Username'] != sender['Username'] 
                            and t['Receiving_Count'] < max_cap 
                            and t['Username'] not in sender['History']
                        ]
                        if not eligible: return None
                        
                        if prioritize_strength:
                            # Sort by Infantry+Cavalry (High to Low) then by current count (Low to High)
                            eligible.sort(key=lambda x: (-x['Inf_Cav'], x['Receiving_Count']))
                        else:
                            # Standard sort: just balance the load evenly
                            eligible.sort(key=lambda x: x['Receiving_Count'])
                        
                        return eligible[0]

                    # DISTRIBUTION WATERFALL
                    for sender in marches_to_assign:
                        target = None
                        
                        # STEP 1: Same Status (Cap 4) - Standard Load Balancing
                        target = find_best_target(sender, [p for p in players if p['Status'] == sender['Status']], 4)
                        
                        # STEP 2: Cross Status (Cap 4) - Standard Load Balancing
                        if not target:
                            target = find_best_target(sender, players, 4)
                        
                        # STEP 3: The "Step Up" (Cap 5+) - PRIORITIZE HIGH INF_CAV
                        if not target:
                            target = find_best_target(sender, players, 10, prioritize_strength=True)

                        if target:
                            final_orders.append([sender['Username'], sender['Status'], target['Username'], target['Status']])
                            target['Receiving_Count'] += 1
                            sender['History'].append(target['Username'])
                        else:
                            final_orders.append([sender['Username'], sender['Status'], "LIMIT REACHED", "N/A"])

                    df_final = pd.DataFrame(final_orders, columns=["From", "Status", "Send To", "Target Status"])
                    df_final = df_final.sort_values(by="From")

                    client = get_client()
                    order_sheet = client.open("Kingshot_Data").worksheet("Orders")
                    order_sheet.clear()
                    order_sheet.append_row(["From", "Status", "Send To", "Target Status"])
                    order_sheet.append_rows(df_final.values.tolist())
                    
                    st.cache_data.clear()
                    st.success("Orders published! High Inf+Cav players prioritized for extra marches.")
                    st.rerun()
        else:
            st.error("Wrong Admin Password")

    if st.button("Reset All Data"):
        if admin_pw == ADMIN_PASSWORD:
            client = get_client()
            client.open("Kingshot_Data").worksheet("Roster").clear()
            client.open("Kingshot_Data").worksheet("Roster").append_row(["Username", "Status", "Marches_Available", "Inf_Cav"])
            client.open("Kingshot_Data").worksheet("Orders").clear()
            client.open("Kingshot_Data").worksheet("Orders").append_row(["From", "Status", "Send To", "Target Status"])
            st.cache_data.clear()
            st.success("Wiped everything.")
            st.rerun()
