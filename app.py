import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
import sqlite3
import json

# --- Page Configuration ---
st.set_page_config(page_title="Assembly Extractor", layout="wide")

# --- Database Setup & Helper Functions ---
DB_FILE = "amazon_modules.db"

def init_db():
    """Create the database and tables if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS modules (
            module_name TEXT PRIMARY KEY,
            bom_json TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_module_to_db(module_name, df):
    """Save or update a module's DataFrame in the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Convert DataFrame to JSON string so it easily fits in a text column
    bom_json = df.to_json(orient="records")
    # REPLACE INTO acts as both an INSERT (if new) and an UPDATE (if exists)
    cursor.execute('''
        REPLACE INTO modules (module_name, bom_json)
        VALUES (?, ?)
    ''', (module_name, bom_json))
    conn.commit()
    conn.close()

def load_all_modules_from_db():
    """Load all modules from the database into a dictionary."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT module_name, bom_json FROM modules')
    rows = cursor.fetchall()
    conn.close()
    
    loaded_modules = {}
    for row in rows:
        name = row[0]
        # Convert JSON string back to DataFrame
        df = pd.read_json(io.StringIO(row[1]), orient="records")
        loaded_modules[name] = {"bom": df}
    return loaded_modules

# Initialize the database file when the app starts
init_db()

# --- Authentication Logic ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Please enter the password to access the dashboard", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Please enter the password to access the dashboard", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

# --- Helper Function: Extract Data from PDF ---
def process_pdf(pdf_bytes):
    all_bom_data = []
    row_pattern = re.compile(r'^(\d+)\s+([^\s]+)\s+([\d\.,]+)\s+(.+)$')
    in_bom_section = False

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if not line: continue
                if "BOM_ID" in line.upper() and "UIN" in line.upper() and "QUANTITY" in line.upper():
                    in_bom_section = True
                    continue
                if in_bom_section:
                    match = row_pattern.match(line)
                    if match:
                        all_bom_data.append({
                            "Completed": False, "BOM_ID": match.group(1), "UIN": match.group(2),
                            "Quantity": match.group(3), "Description": match.group(4)
                        })
                    elif all_bom_data:
                        if re.match(r'^Page\s+\d+', line, re.IGNORECASE) or (line.isdigit() and len(line) < 4): continue
                        if re.match(r'^(Step\s+\d+|\d+\.\d+\s+[A-Z])', line, re.IGNORECASE):
                            in_bom_section = False
                            continue
                        if line.upper().startswith("NOTES:") or line.upper().startswith("TOTAL"):
                            in_bom_section = False
                            continue
                        if len(all_bom_data[-1]["Description"]) < 400:
                            all_bom_data[-1]["Description"] += " " + line
    return pd.DataFrame(all_bom_data)

# ==========================================
# MAIN APP LOGIC (Protected by Password)
# ==========================================
if check_password():
    # --- Initialize ALL session state variables here ---
    if 'modules_db' not in st.session_state:
        # Instead of an empty dict, load from our SQLite database!
        st.session_state.modules_db = load_all_modules_from_db()
    if 'selected_module' not in st.session_state:
        st.session_state.selected_module = None

    # --- Sidebar Navigation ---
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Upload New Module", "Dashboard"])
    if st.sidebar.button("Log Out"):
        st.session_state["password_correct"] = False
        st.session_state.selected_module = None
        st.rerun()

    # ==========================================
    # PAGE 1: UPLOAD NEW MODULE
    # ==========================================
    if page == "Upload New Module":
        st.title("📤 Upload Amazon Assembly Module")
        st.write("Upload one or more PDFs to extract their Bill of Materials and save them to your dashboard.")
        
        uploaded_files = st.file_uploader("Choose PDF files", type="pdf", accept_multiple_files=True)
        
        if uploaded_files:
            success_count = 0
            for uploaded_file in uploaded_files:
                module_name = uploaded_file.name.replace('.pdf', '')
                
                if module_name in st.session_state.modules_db:
                    st.warning(f"Module '{module_name}' is already in your Dashboard!")
                else:
                    with st.spinner(f"Extracting BOM from {module_name}..."):
                        pdf_bytes = uploaded_file.read()
                        bom_df = process_pdf(pdf_bytes)
                        
                        if not bom_df.empty:
                            # Update memory
                            st.session_state.modules_db[module_name] = {"bom": bom_df}
                            # NEW: Also save to physical database
                            save_module_to_db(module_name, bom_df)
                            
                            st.success(f"Successfully processed and saved '{module_name}'!")
                            success_count += 1
                        else:
                            st.error(f"Could not find a valid BOM in '{module_name}'.")
            
            if success_count > 0:
                st.balloons()

    # ==========================================
    # PAGE 2: DASHBOARD (with Master-Detail View)
    # ==========================================
    elif page == "Dashboard":
        # --- DETAIL VIEW (FULL WINDOW) ---
        if st.session_state.selected_module:
            module_name = st.session_state.selected_module
            module_data = st.session_state.modules_db[module_name]
            df = module_data["bom"]

            if st.button("← Back to Dashboard"):
                st.session_state.selected_module = None
                st.rerun()

            st.title(f"📦 Module: {module_name}")
            st.divider()

            total_items = len(df)
            completed_items = df["Completed"].sum()
            progress_percentage = int((completed_items / total_items) * 100) if total_items > 0 else 0
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(progress_percentage / 100.0)
            with col2:
                st.metric("Completion Status", f"{progress_percentage}%", f"{completed_items} / {total_items} Items")
            
            if progress_percentage == 100:
                st.success("Module Complete! 🎉")
                if st.button("Celebrate!", key=f"celebrate_{module_name}"):
                    st.balloons()
            
            st.subheader("📝 Bill of Materials Checklist")
            
            with st.form(key=f"form_{module_name}"):
                edited_df = st.data_editor(
                    df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Completed": st.column_config.CheckboxColumn("Done?", default=False),
                        "BOM_ID": st.column_config.TextColumn("BOM ID", disabled=True),
                        "UIN": st.column_config.TextColumn("UIN", disabled=True),
                        "Quantity": st.column_config.TextColumn("Qty", disabled=True),
                        "Description": st.column_config.TextColumn("Description", disabled=True)
                    }
                )
                submit_progress = st.form_submit_button("💾 Save Progress")
                
            if submit_progress:
                # Update memory
                st.session_state.modules_db[module_name]["bom"] = edited_df
                # NEW: Save changes to the physical database file
                save_module_to_db(module_name, edited_df)
                st.rerun()

        # --- MASTER VIEW (GRID) ---
        else:
            st.title("📊 Module Dashboard")
            if not st.session_state.modules_db:
                st.info("Your dashboard is empty. Please go to 'Upload New Module' to add some PDFs.")
            else:
                st.write("Select a module to view its checklist.")
                st.divider()
                module_items = list(st.session_state.modules_db.items())
                for i in range(0, len(module_items), 3):
                    cols = st.columns(3)
                    for j in range(3):
                        if i + j < len(module_items):
                            module_name, module_data = module_items[i + j]
                            df = module_data["bom"]
                            total_items = len(df)
                            completed_items = df["Completed"].sum()
                            progress_percentage = int((completed_items / total_items) * 100) if total_items > 0 else 0

                            with cols[j]:
                                with st.container(border=True):
                                    st.subheader(f"📦 {module_name}")
                                    st.progress(progress_percentage / 100.0)
                                    st.metric("Completion Status", f"{progress_percentage}%", f"{completed_items} / {total_items} Items")
                                    
                                    if st.button("View Checklist", key=f"view_{module_name}", use_container_width=True):
                                        st.session_state.selected_module = module_name
                                        st.rerun()
