import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
import time

# --- INITIAL CONFIG ---
st.set_page_config(page_title="Kingshot Vikings Tool", page_icon="⚔️", layout="wide")

# --- GHOST MODE & MOBILE CSS ---
st.markdown("""
    <style>
    #MainMenu, footer, header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    .stAppViewFooter {display: none !important;}
    [data-baseweb="tab-list"] { gap: 8px; }
    [data-baseweb="tab"] {
        border: 1px solid #4B5563 !important;
        border-radius: 8px !important;
        padding: 10px 15px !important;
        background-color: #1F2937 !important;
        color: #F3F4F6 !important;
        font-weight: 600 !important;
        min-width: 100px;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        background-color: #3B82F6 !important;
        border-color: #60A5FA !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- AUTH & DATA ---
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
    return client.open("Kingshot_Data").worksheet(sheet_name).get_all_records()

if "password_correct" not in st.session_state:
    st.session_state["password_correct"] = False

if not st.session_state["password_correct"]:
    pw = st.text_input("Alliance Password", type="password")
    if st.button("Login"):
        if pw == GLOBAL_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Access Denied")
    st.stop()

st.title("⚔️ Vikings Swap Tool")

try:
    roster_data = fetch_data("Roster")
    orders_data = fetch_data("Orders")
except:
    st.error("Sheet Connection Busy...")
    st.stop()

# --- TABS ---
tab_reg, tab_roster, tab_orders = st.tabs(["📝 REGISTER", "👥 ROSTER", "📜 SWAP ORDERS"])

with tab_reg:
    st.subheader("Add / Update Entry")
    user = st.text_input("Username")
    status = st.radio("Status", ["Online", "Offline"], horizontal=True)
    marches = st.slider("Marches to send", 4, 6, 5)
    inf_cav = st.number_input("Infantry + Cavalry", min_value=0, value=0)
    
    if st.button("Submit My Entry", use_container_width=True):
        if user:
            with st.spinner("Writing..."):
                client = get_client()
                sheet = client.open("Kingshot_Data").worksheet("Roster")
                idx = next((i for i, item in enumerate(roster_data) if item["Username"] == user), None)
                if idx is not None: sheet.delete_rows(idx + 2)
                sheet.append_row([user, status, marches, inf_cav])
                st.cache_data.clear()
                st.success("Entry Saved!")
                time.sleep(1); st.rerun()

with tab_roster:
    c1, c2 = st.columns([3, 1])
    c1.subheader(f"Total: {len(roster_data)}")
    if c2.button("🔄 Refresh", key="ref_rost"):
        st.cache_data.clear(); st.rerun()
    st.dataframe(pd.DataFrame(roster_data), use_container_width=True)

with tab_orders:
    c3, c4 = st.columns([3, 1])
    c3.subheader("Alliance Swap Orders")
    if c4.button("🔄 Refresh", key="ref_ord"):
        st.cache_data.clear(); st.rerun()
    
    if orders_data:
        my_name = st.text_input("🔍 Search for your name")
        df_ord = pd.DataFrame(orders_data)
        if my_name: df_ord = df_ord[df_ord['From'].str.contains(my_name, case=False)]
        st.dataframe(df_ord, use_container_width=True)
    else: st.info("Orders pending Admin generation.")

# --- THE NEW LOGIC ENGINE ---
st.markdown("---")
with st.expander("🛡️ Admin Controls"):
    admin_pw = st.text_input("Admin Password", type="password")
    
    if st.button("Generate & Publish Orders"):
        if admin_pw == ADMIN_PASSWORD:
            with st.spinner("Processing Bubbles..."):
                players = []
                for p in roster_data:
                    players.append({
                        "Username": p["Username"], "Status": p["Status"],
                        "Sends": int(p["Marches_Available"]), "Inf_Cav": int(p.get("Inf_Cav", 0)),
                        "Rec_Count": 0, "History": []
                    })
                
                # Separate send queues
                online_senders = [p for p in players if p["Status"] == "Online"]
                offline_senders = [p for p in players if p["Status"] == "Offline"]
                
                # Build march-by-march queue
                all_marches = []
                for p in (online_senders + offline_senders):
                    for _ in range(p["Sends"]): all_marches.append(p)
                
                final_rows = []

                def get_target(sender, pool, cap, strength_priority=False):
                    eligible = [t for t in pool if t['Username'] != sender['Username'] 
                                and t['Rec_Count'] < cap and t['Username'] not in sender['History']]
                    if not eligible: return None
                    
                    if strength_priority:
                        # User wants HIGH strength to have LOWER priority for receiving more.
                        # So we sort by Inf_Cav ASCENDING (weakest first).
                        eligible.sort(key=lambda x: (x['Inf_Cav'], x['Rec_Count']))
                    else:
                        eligible.sort(key=lambda x: x['Rec_Count'])
                    return eligible[0]

                for s in all_marches:
                    target = None
                    # PASS 1: Same Status Bubble (Cap 4)
                    target = get_target(s, [p for p in players if p['Status'] == s['Status']], 4)
                    
                    # PASS 2: Online -> Offline Leak (Cap 4)
                    if not target and s['Status'] == "Online":
                        target = get_target(s, [p for p in players if p['Status'] == "Offline"], 4)
                    
                    # PASS 3: Necessary Step-Up (Cap 5) - LOW STRENGTH FIRST
                    if not target:
                        target = get_target(s, players, 5, strength_priority=True)

                    # PASS 4: Absolute Emergency (Cap 6)
                    if not target:
                        target = get_target(s, players, 6, strength_priority=True)

                    if target:
                        final_rows.append([s['Username'], s['Status'], target['Username'], target['Status']])
                        target['Rec_Count'] += 1
                        s['History'].append(target['Username'])
                    else:
                        final_rows.append([s['Username'], s['Status'], "NO TARGET", "N/A"])

                df_final = pd.DataFrame(final_rows, columns=["From", "Status", "Send To", "Target Status"]).sort_values(by="From")
                
                client = get_client()
                order_sheet = client.open("Kingshot_Data").worksheet("Orders")
                order_sheet.clear()
                order_sheet.append_row(["From", "Status", "Send To", "Target Status"])
                order_sheet.append_rows(df_final.values.tolist())
                st.cache_data.clear(); st.success("Orders Published!"); st.rerun()

    if st.button("Reset Data"):
        if admin_pw == ADMIN_PASSWORD:
            client = get_client()
            client.open("Kingshot_Data").worksheet("Roster").clear()
            client.open("Kingshot_Data").worksheet("Roster").append_row(["Username", "Status", "Marches_Available", "Inf_Cav"])
            client.open("Kingshot_Data").worksheet("Orders").clear()
            client.open("Kingshot_Data").worksheet("Orders").append_row(["From", "Status", "Send To", "Target Status"])
            st.cache_data.clear(); st.success("Wiped."); st.rerun()
