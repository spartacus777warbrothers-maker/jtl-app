import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
import time

# 1. INITIAL CONFIG (Must be first)
st.set_page_config(
    page_title="Kingshot Vikings Tool",
    page_icon="⚔️",
    layout="wide"
)

# 2. GHOST MODE & MOBILE TAB CSS
# This hides GitHub links and makes tabs look like high-contrast buttons
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {display: none;}
    .stAppViewFooter {display: none !important;}

    /* Mobile Tab Styling */
    [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent !important;
    }
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
        color: white !important;
    }
    [data-baseweb="tab-highlight"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

# 3. GOOGLE API HELPERS
def get_client():
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=15)
def fetch_all_data():
    """Fetches both tabs in one single handshake to prevent 429 errors."""
    client = get_client()
    sh = client.open("Kingshot_Data")
    roster = sh.worksheet("Roster").get_all_records()
    orders = sh.worksheet("Orders").get_all_records()
    return roster, orders

# 4. AUTHENTICATION
GLOBAL_PASSWORD = st.secrets["general"]["password"]
ADMIN_PASSWORD = st.secrets["general"]["admin_password"]

if "password_correct" not in st.session_state:
    st.session_state["password_correct"] = False

if not st.session_state["password_correct"]:
    st.title("⚔️ Alliance Login")
    pw = st.text_input("Enter Password", type="password")
    if st.button("Login"):
        if pw == GLOBAL_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Invalid Password")
    st.stop()

# 5. DATA LOADING
try:
    roster_data, orders_data = fetch_all_data()
except Exception:
    st.error("🛡️ Sheet Connection Busy. Please wait 30 seconds and refresh.")
    st.stop()

# 6. UI TABS
st.title("⚔️ Vikings Troop Swap")
tab_reg, tab_roster, tab_orders = st.tabs(["📝 REGISTER", "👥 ROSTER", "📜 SWAP ORDERS"])

with tab_reg:
    st.subheader("Register Your Troops")
    user = st.text_input("In-Game Username")
    status = st.radio("Current Status", ["Online", "Offline"], horizontal=True)
    marches = st.slider("Marches you are sending", 4, 6, 5)
    inf_cav = st.number_input("Infantry + Cavalry Count", min_value=0, value=0)
    
    if st.button("Submit My Entry", use_container_width=True):
        if user:
            with st.spinner("Talking to Google..."):
                client = get_client()
                sheet = client.open("Kingshot_Data").worksheet("Roster")
                idx = next((i for i, item in enumerate(roster_data) if item["Username"] == user), None)
                if idx is not None:
                    sheet.delete_rows(idx + 2)
                sheet.append_row([user, status, marches, inf_cav])
                st.cache_data.clear()
                st.success(f"Successfully saved {user}!")
                time.sleep(1)
                st.rerun()
    
    st.markdown("---")
    with st.expander("❌ Delete My Entry"):
        del_user = st.text_input("Type username exactly to remove")
        if st.button("Delete Info", use_container_width=True):
            client = get_client()
            sheet = client.open("Kingshot_Data").worksheet("Roster")
            idx = next((i for i, item in enumerate(roster_data) if item["Username"] == del_user), None)
            if idx is not None:
                sheet.delete_rows(idx + 2)
                st.cache_data.clear()
                st.success("Entry removed.")
                time.sleep(1)
                st.rerun()

with tab_roster:
    c1, c2 = st.columns([3, 1])
    c1.subheader(f"Total Registered: {len(roster_data)}")
    if c2.button("🔄 Refresh", key="ref_rost"):
        st.cache_data.clear()
        st.rerun()
    if roster_data:
        st.dataframe(pd.DataFrame(roster_data), use_container_width=True)
    else:
        st.info("No entries yet.")

with tab_orders:
    c3, c4 = st.columns([3, 1])
    c3.subheader("Live Swap Orders")
    if c4.button("🔄 Refresh", key="ref_ord"):
        st.cache_data.clear()
        st.rerun()
    
    if orders_data:
        search = st.text_input("🔍 Filter by your name")
        df_ord = pd.DataFrame(orders_data)
        if search:
            df_ord = df_ord[df_ord['From'].str.contains(search, case=False)]
        st.dataframe(df_ord, use_container_width=True)
    else:
        st.warning("Orders haven't been generated yet.")

# 7. ADMIN LOGIC ENGINE
st.markdown("---")
with st.expander("🛡️ Admin Controls"):
    admin_pw = st.text_input("Admin Key", type="password")
    
    if st.button("Generate & Publish Orders", use_container_width=True):
        if admin_pw == ADMIN_PASSWORD:
            with st.spinner("Calculating Bubbles & Strength..."):
                if len(roster_data) < 2:
                    st.error("Not enough players.")
                else:
                    # Prep Player Data
                    players = []
                    for p in roster_data:
                        players.append({
                            "Username": p["Username"], "Status": p["Status"],
                            "Sends": int(p["Marches_Available"]), "Inf_Cav": int(p.get("Inf_Cav", 0)),
                            "Rec_Count": 0, "History": []
                        })
                    
                    # Create Queue
                    all_marches = []
                    for p in players:
                        for _ in range(p["Sends"]): all_marches.append(p)
                    random.shuffle(all_marches)

                    final_rows = []

                    def find_target(sender, pool, cap, use_strength_priority=False):
                        eligible = [t for t in pool if t['Username'] != sender['Username'] 
                                    and t['Rec_Count'] < cap and t['Username'] not in sender['History']]
                        if not eligible: return None
                        
                        if use_strength_priority:
                            # WEAKEST players (Lowest Inf_Cav) get priority to receive extra
                            eligible.sort(key=lambda x: (x['Inf_Cav'], x['Rec_Count']))
                        else:
                            eligible.sort(key=lambda x: x['Rec_Count'])
                        return eligible[0]

                    # WATERFALL LOGIC
                    for s in all_marches:
                        target = None
                        # Pass 1: Same Bubble (Cap 4)
                        target = find_target(s, [p for p in players if p['Status'] == s['Status']], 4)
                        # Pass 2: Online -> Offline Leak (Cap 4)
                        if not target and s['Status'] == "Online":
                            target = find_target(s, [p for p in players if p['Status'] == "Offline"], 4)
                        # Pass 3: Step Up to 5 (Weakest Players First)
                        if not target:
                            target = find_target(s, players, 5, use_strength_priority=True)
                        # Pass 4: Step Up to 6 (Emergency)
                        if not target:
                            target = find_target(s, players, 6, use_strength_priority=True)

                        if target:
                            final_rows.append([s['Username'], s['Status'], target['Username'], target['Status']])
                            target['Rec_Count'] += 1
                            s['History'].append(target['Username'])
                        else:
                            final_rows.append([s['Username'], s['Status'], "NO UNIQUE TARGET", "N/A"])

                    # Save to Google Sheets
                    df_final = pd.DataFrame(final_rows, columns=["From", "Status", "Send To", "Target Status"]).sort_values(by="From")
                    client = get_client()
                    sh = client.open("Kingshot_Data")
                    order_sheet = sh.worksheet("Orders")
                    order_sheet.clear()
                    order_sheet.append_row(["From", "Status", "Send To", "Target Status"])
                    order_sheet.append_rows(df_final.values.tolist())
                    
                    st.cache_data.clear()
                    st.success("Swaps Published Successfully!")
                    time.sleep(1)
                    st.rerun()
        else:
            st.error("Admin Password Incorrect")

    if st.button("Reset Entire Website"):
        if admin_pw == ADMIN_PASSWORD:
            client = get_client()
            sh = client.open("Kingshot_Data")
            sh.worksheet("Roster").clear()
            sh.worksheet("Roster").append_row(["Username", "Status", "Marches_Available", "Inf_Cav"])
            sh.worksheet("Orders").clear()
            sh.worksheet("Orders").append_row(["From", "Status", "Send To", "Target Status"])
            st.cache_data.clear()
            st.success("All data wiped.")
            st.rerun()
