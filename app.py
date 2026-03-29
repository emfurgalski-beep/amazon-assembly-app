import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
import os
import json
from streamlit_gsheets import GSheetsConnection

# --- Page Configuration ---
st.set_page_config(page_title="Assembly Extractor", layout="wide")

# ==========================================
# DATABASE LOGIC (Google Sheets)
# ==========================================
def load_all_modules_from_gsheets():
    """Load all modules from Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # ttl=0 ensures we always pull the freshest data
        df = conn.read(worksheet="Sheet1", ttl=0).dropna(how="all")
        
        loaded_modules = {}
        if not df.empty and "Module_Name" in df.columns and "BOM_JSON" in df.columns:
            for _, row in df.iterrows():
                name = row["Module_Name"]
                bom_json_str = row["BOM_JSON"]
                if pd.notna(bom_json_str):
                    bom_df = pd.read_json(io.StringIO(bom_json_str), orient="records")
                    loaded_modules[name] = {"bom": bom_df}
        return loaded_modules
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets. Check your secrets! Error: {e}")
        return {}

def save_module_to_gsheets(module_name, bom_df):
    """Save or update a module's DataFrame in Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl=0).dropna(how="all")
        
        bom_json = bom_df.to_json(orient="records")
        new_row = pd.DataFrame([{"Module_Name": module_name, "BOM_JSON": bom_json}])
        
        if not df.empty and "Module_Name" in df.columns:
            # Remove the old row for this module, if it exists
            df = df[df["Module_Name"] != module_name]
            # Append the updated row
            df = pd.concat([df, new_row], ignore_index=True)
        else:
            df = new_row
            
        # Push the entire updated dataframe back to the sheet
        conn.update(worksheet="Sheet1", data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed to save to Google Sheets. Error: {e}")

def delete_module_from_gsheets(module_name):
    """Delete a module from Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl=0).dropna(how="all")
        
        if not df.empty and "Module_Name" in df.columns:
            # Keep everything EXCEPT the module we want to delete
            df = df[df["Module_Name"] != module_name]
            conn.update(worksheet="Sheet1", data=df)
            st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed to delete from Google Sheets. Error: {e}")

# ==========================================
# AUTHENTICATION LOGIC
# ==========================================
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

# ==========================================
# PDF PARSING LOGIC
# ==========================================
def process_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    """Extracts BOM data from PDF bytes and returns it as a Pandas DataFrame."""
    all_bom_data = []
    row_pattern = re.compile(r'^(\d+)\s+([^\s]+)\s+([\d\.,]+)\s+(.+)$')
    in_bom_section = False

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
    
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
    
                    if "BOM_ID" in line.upper() and "UIN" in line.upper() and "QUANTITY" in line.upper():
                        in_bom_section = True
                        continue
    
                    if in_bom_section:
                        match = row_pattern.match(line)
                        if match:
                            all_bom_data.append({
                                "Completed": False, # Checkbox column defaults to False
                                "BOM_ID": match.group(1),
                                "UIN": match.group(2),
                                "Quantity": match.group(3),
                                "Description": match.group(4)
                            })
                        elif all_bom_data:
                            # Stop rules and text wrapping
                            if re.match(r'^Page\s+\d+', line, re.IGNORECASE) or (line.isdigit() and len(line) < 4):
                                continue
                            if re.match(r'^(Step\s+\d+|\d+\.\d+\s+[A-Z])', line, re.IGNORECASE):
                                in_bom_section = False
                                continue
                            if line.upper().startswith("NOTES:") or line.upper().startswith("TOTAL"):
                                in_bom_section = False
                                continue
                            if len(all_bom_data[-1]["Description"]) < 400:
                                all_bom_data[-1]["Description"] += " " + line
    except Exception as e:
        st.error(f"An error occurred while reading the PDF: {e}")
        return pd.DataFrame() # Return empty dataframe on failure
        
    return pd.DataFrame(all_bom_data)

# ==========================================
# MAIN APP LOGIC (Protected by Password)
# ==========================================
if check_password():
    # --- Initialize session state from Google Sheets ---
    if 'modules_db' not in st.session_state:
        st.session_state.modules_db = load_all_modules_from_gsheets()
    if 'selected_module' not in st.session_state:
        st.session_state.selected_module = None

    # --- Sidebar Navigation ---
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Upload New Module", "Dashboard"])
    
    st.sidebar.divider()
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
                module_name = os.path.splitext(uploaded_file.name)[0]
                
                if module_name in st.session_state.modules_db:
                    st.warning(f"Module '{module_name}' is already in your Dashboard!")
                else:
                    with st.spinner(f"Extracting BOM from {module_name}..."):
                        pdf_bytes = uploaded_file.read()
                        bom_df = process_pdf(pdf_bytes)
                        
                        if not bom_df.empty:
                            # Update local memory
                            st.session_state.modules_db[module_name] = {"bom": bom_df}
                            # Push to Google Sheets
                            save_module_to_gsheets(module_name, bom_df)
                            
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
            module_data = st.session_state.modules_db.get(module_name)
            
            # Failsafe in case module was deleted but state wasn't cleared
            if not module_data:
                st.session_state.selected_module = None
                st.rerun()
                
            df = module_data["bom"]

            # --- Top Navigation & Actions ---
            nav_col1, nav_col2, nav_col3 = st.columns([6, 2, 2])
            with nav_col1:
                if st.button("← Back to Dashboard"):
                    st.session_state.selected_module = None
                    st.rerun()
            with nav_col2:
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Export CSV", data=csv, file_name=f"{module_name}_bom.csv", mime="text/csv", use_container_width=True)
            with nav_col3:
                if st.button("🗑️ Delete", type="primary", use_container_width=True):
                    with st.spinner("Deleting module..."):
                        delete_module_from_gsheets(module_name)
                        if module_name in st.session_state.modules_db:
                            del st.session_state.modules_db[module_name]
                        st.session_state.selected_module = None
                        st.rerun()

            st.title(f"📦 Module: {module_name}")
            st.divider()

            # --- Progress Calculation & Display ---
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
            
            # --- Interactive Form ---
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
                with st.spinner("Saving to Google Sheets..."):
                    # Update local memory
                    st.session_state.modules_db[module_name]["bom"] = edited_df
                    # Update Google Sheets
                    save_module_to_gsheets(module_name, edited_df)
                st.rerun()

        # --- MASTER VIEW (GRID) ---
        else:
            st.title("📊 Module Dashboard")
            if not st.session_state.modules_db:
                st.info("Your dashboard is empty. Please go to 'Upload New Module' to add some PDFs.")
            else:
                st.write("Select a module to view its checklist.")
                
                # --- Overall Progress Chart ---
                with st.expander("📈 View Overall Progress", expanded=True):
                    chart_data = []
                    total_global_items = 0
                    total_global_completed = 0
                    
                    for name, data in st.session_state.modules_db.items():
                        df_mod = data["bom"]
                        tot = len(df_mod)
                        comp = df_mod["Completed"].sum()
                        pct = int((comp / tot) * 100) if tot > 0 else 0
                        chart_data.append({"Module": name, "Completion %": pct})
                        total_global_items += tot
                        total_global_completed += comp
                        
                    global_pct = int((total_global_completed / total_global_items) * 100) if total_global_items > 0 else 0
                    
                    prog_col1, prog_col2 = st.columns([1, 3])
                    with prog_col1:
                        st.metric("Overall Completion", f"{global_pct}%", f"{total_global_completed} / {total_global_items} Total Items")
                    with prog_col2:
                        chart_df = pd.DataFrame(chart_data).set_index("Module")
                        st.bar_chart(chart_df, y="Completion %")

                st.divider()
                
                # --- Search and Sort Controls ---
                ctrl_col1, ctrl_col2 = st.columns([3, 1])
                with ctrl_col1:
                    search_term = st.text_input("🔍 Search Modules", placeholder="Type to filter by module name...")
                with ctrl_col2:
                    sort_order = st.selectbox("↕️ Sort By", ["Name (A-Z)", "Name (Z-A)", "Completion (High - Low)", "Completion (Low - High)"])
                
                # Prepare filtered and calculated list
                module_items = []
                for name, data in st.session_state.modules_db.items():
                    if search_term.lower() in name.lower():
                        df_mod = data["bom"]
                        tot = len(df_mod)
                        comp = df_mod["Completed"].sum()
                        pct = int((comp / tot) * 100) if tot > 0 else 0
                        module_items.append({"name": name, "data": data, "pct": pct, "tot": tot, "comp": comp})
                
                # Apply Sorting
                if sort_order == "Name (A-Z)":
                    module_items = sorted(module_items, key=lambda x: x["name"].lower())
                elif sort_order == "Name (Z-A)":
                    module_items = sorted(module_items, key=lambda x: x["name"].lower(), reverse=True)
                elif sort_order == "Completion (High - Low)":
                    module_items = sorted(module_items, key=lambda x: x["pct"], reverse=True)
                elif sort_order == "Completion (Low - High)":
                    module_items = sorted(module_items, key=lambda x: x["pct"])
                
                if not module_items:
                    st.warning("No modules found matching your search.")
                else:
                    # Chunk the items into rows of 3 columns
                    for i in range(0, len(module_items), 3):
                        cols = st.columns(3)
                        for j in range(3):
                            if i + j < len(module_items):
                                mod_dict = module_items[i + j]
                                module_name = mod_dict["name"]
                                
                                with cols[j]:
                                    with st.container(border=True):
                                        st.subheader(f"📦 {module_name}")
                                        st.progress(mod_dict["pct"] / 100.0)
                                        st.metric("Completion Status", f"{mod_dict['pct']}%", f"{mod_dict['comp']} / {mod_dict['tot']} Items")
                                        
                                        if st.button("View Checklist", key=f"view_{module_name}", use_container_width=True):
                                            st.session_state.selected_module = module_name
                                            st.rerun()
