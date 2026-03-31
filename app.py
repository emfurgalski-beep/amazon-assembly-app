import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
import os
import json
import datetime
import altair as alt
from streamlit_gsheets import GSheetsConnection

# --- Page Configuration ---
st.set_page_config(page_title="NPSG Module Assembly Tool", layout="wide")

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
                    # Gracefully handle legacy data by injecting the new column if it's missing
                    if "Collected" not in bom_df.columns:
                        bom_df.insert(0, "Collected", False)
                    if "Prekited" not in bom_df.columns:
                        bom_df.insert(1, "Prekited", False)
                    if "Notes" not in bom_df.columns:
                        bom_df["Notes"] = ""
                    if "UIN" in bom_df.columns:
                        bom_df = bom_df.sort_values(by="UIN", ascending=True).reset_index(drop=True)
                    last_updated = row["Last_Updated"] if "Last_Updated" in df.columns else "Unknown"
                    is_archived = row["Archived"] if "Archived" in df.columns and pd.notna(row["Archived"]) else False
                    due_date = pd.to_datetime(row["DueDate"]).date() if "DueDate" in df.columns and pd.notna(row["DueDate"]) else None
                    is_priority = row["IsPriority"] if "IsPriority" in df.columns and pd.notna(row["IsPriority"]) else False
                    
                    loaded_modules[name] = {"bom": bom_df, "last_updated": last_updated, "archived": is_archived, 
                                            "due_date": due_date, "is_priority": is_priority}
        return loaded_modules
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets. Check your secrets! Error: {e}")
        return {}

def save_module_to_gsheets(module_name, bom_df):
    """Save or update a module's DataFrame in Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl=0).dropna(how="all")
        
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bom_json = bom_df.to_json(orient="records")

        # Preserve existing metadata when saving
        is_archived, due_date, is_priority = False, None, False
        if not df.empty and "Module_Name" in df.columns:
            old_row = df[df["Module_Name"] == module_name]
            if not old_row.empty:
                if "Archived" in old_row.columns:
                    is_archived = old_row["Archived"].iloc[0] if pd.notna(old_row["Archived"].iloc[0]) else False
                if "DueDate" in old_row.columns:
                    due_date = old_row["DueDate"].iloc[0] if pd.notna(old_row["DueDate"].iloc[0]) else None
                if "IsPriority" in old_row.columns:
                    is_priority = old_row["IsPriority"].iloc[0] if pd.notna(old_row["IsPriority"].iloc[0]) else False

        new_row_data = {"Module_Name": module_name, "BOM_JSON": bom_json, "Last_Updated": current_time, 
                        "Archived": is_archived, "DueDate": due_date, "IsPriority": is_priority}
        new_row = pd.DataFrame([new_row_data])

        if not df.empty and "Module_Name" in df.columns:
            # Remove the old row for this module, if it exists
            df = df[df["Module_Name"] != module_name]
            df = pd.concat([df, new_row], ignore_index=True)
        else:
            df = new_row
            
        # Push the entire updated dataframe back to the sheet
        conn.update(worksheet="Sheet1", data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed to save to Google Sheets. Error: {e}")

def set_archive_status_in_gsheets(module_name, is_archived):
    """Sets the archive status for a specific module in Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl=0).dropna(how="all")
        
        if not df.empty and "Module_Name" in df.columns:
            module_index = df.index[df["Module_Name"] == module_name].tolist()
            if module_index:
                if "Archived" not in df.columns:
                    df["Archived"] = False
                df.loc[module_index[0], "Archived"] = is_archived
                conn.update(worksheet="Sheet1", data=df)
                st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed to update archive status in Google Sheets. Error: {e}")

def update_module_metadata_in_gsheets(module_name, due_date=None, is_priority=None):
    """Updates metadata for a specific module in Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Sheet1", ttl=0).dropna(how="all")
        
        if not df.empty and "Module_Name" in df.columns:
            module_index = df.index[df["Module_Name"] == module_name].tolist()
            if module_index:
                idx = module_index[0]
                if due_date is not None:
                    if "DueDate" not in df.columns: df["DueDate"] = None
                    df.loc[idx, "DueDate"] = due_date.strftime('%Y-%m-%d') if due_date else None
                if is_priority is not None:
                    if "IsPriority" not in df.columns: df["IsPriority"] = False
                    df.loc[idx, "IsPriority"] = is_priority
                conn.update(worksheet="Sheet1", data=df)
                st.cache_data.clear()
    except Exception as e:
        st.error(f"Failed to update metadata in Google Sheets. Error: {e}")

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
        pwd = st.session_state["password"]
        # Admin Login
        if "admin_password" in st.secrets and pwd == st.secrets["admin_password"]:
            st.session_state["password_correct"] = True
            st.session_state["user_role"] = "Admin"
            del st.session_state["password"]
        # Worker Login
        elif "worker_password" in st.secrets and pwd == st.secrets["worker_password"]:
            st.session_state["password_correct"] = True
            st.session_state["user_role"] = "Worker"
            del st.session_state["password"]
        # Inventory Login
        elif "inventory_password" in st.secrets and pwd == st.secrets["inventory_password"]:
            st.session_state["password_correct"] = True
            st.session_state["user_role"] = "Inventory"
            del st.session_state["password"]
        # Fallback to legacy password (Grants Admin)
        elif "app_password" in st.secrets and pwd == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.session_state["user_role"] = "Admin"
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
                                "Collected": False, # New column for Inventory
                                "Prekited": False, # New column for Prekit
                                "Completed": False, # Checkbox column defaults to False
                                "BOM_ID": match.group(1),
                                "UIN": match.group(2),
                                "Quantity": match.group(3),
                                "Description": match.group(4),
                                "Notes": "" # New column for Issues/Notes
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
        
    df = pd.DataFrame(all_bom_data)
    if not df.empty and "UIN" in df.columns:
        df = df.sort_values(by="UIN", ascending=True).reset_index(drop=True)
    return df

# ==========================================
# MAIN APP LOGIC (Protected by Password)
# ==========================================
if check_password():
    # --- Custom CSS for a more professional layout ---
    st.markdown("""
        <style>
            /* Target bordered containers (Module Cards) regardless of Light/Dark theme */
            div[data-testid="stVerticalBlockBorderWrapper"] {
                border-radius: 10px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2), 0 2px 4px -1px rgba(0, 0, 0, 0.1);
                transition: all 0.3s ease-in-out;
            }
            /* Add hover "pop" effect */
            div[data-testid="stVerticalBlockBorderWrapper"]:hover {
                transform: translateY(-5px);
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -2px rgba(0, 0, 0, 0.1);
                border-color: #FF4B4B;
            }
            /* Style metrics to look like mini KPI badges */
            div[data-testid="stMetric"] {
                background-color: rgba(150, 150, 150, 0.1);
                padding: 10px;
                border-radius: 8px;
                display: flex;
                flex-direction: column;
                align-items: center;
            }
        </style>
        """, unsafe_allow_html=True)

    # --- Initialize session state from Google Sheets ---
    if 'modules_db' not in st.session_state:
        st.session_state.modules_db = load_all_modules_from_gsheets()
    if 'selected_module' not in st.session_state:
        st.session_state.selected_module = None
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 0
        
    # --- Hot-Reload Patch for Legacy Sessions ---
    for name, data in st.session_state.modules_db.items():
        data.setdefault("last_updated", "Unknown")
        data.setdefault("archived", False)
        data.setdefault("due_date", None)
        data.setdefault("is_priority", False)

        if "bom" in data:
            if "Collected" not in data["bom"].columns:
                data["bom"].insert(0, "Collected", False)
            if "Prekited" not in data["bom"].columns:
                data["bom"].insert(1, "Prekited", False)
            if "Notes" not in data["bom"].columns:
                data["bom"]["Notes"] = ""
            if "UIN" in data["bom"].columns:
                data["bom"] = data["bom"].sort_values(by="UIN", ascending=True).reset_index(drop=True)

    # --- App Header ---
    st.title("🏗️ NPSG Module Assembly Tool")
    st.write("") # Slight spacing

    # --- Top Navigation ---
    top_col1, top_col2, top_col3 = st.columns([2, 6, 2])
    with top_col1:
        st.write(f"**👤 Role:** {st.session_state.get('user_role', 'Admin')}")
    with top_col2:
        pages = ["Dashboard"]
        if st.session_state.get("user_role", "Admin") == "Admin":
            pages.insert(0, "Upload New Module")
        page = st.radio("Navigation", pages, horizontal=True, label_visibility="collapsed")
    with top_col3:
        if st.button("Log Out", use_container_width=True):
            st.session_state["password_correct"] = False
            st.session_state.selected_module = None
            st.rerun()
            
    st.divider()

    # ==========================================
    # PAGE 1: UPLOAD NEW MODULE
    # ==========================================
    if page == "Upload New Module":
        st.header("📤 Upload New Module")
        st.write("Upload one or more PDFs to extract their Bill of Materials and save them to your dashboard.")
        
        uploaded_files = st.file_uploader("Choose PDF files", type="pdf", accept_multiple_files=True)
        
        # --- Admin controls for new modules ---
        due_date, is_priority = None, False
        if st.session_state.get("user_role") == "Admin":
            st.write("---")
            st.write("**Project Management (Admin Only)**")
            due_date = st.date_input("Set Due Date (Optional)")
            is_priority = st.toggle("Mark as High Priority", value=False)

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
                            st.session_state.modules_db[module_name] = {
                                "bom": bom_df, "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                                "archived": False, "due_date": due_date, "is_priority": is_priority
                            }
                            # Push to Google Sheets
                            save_module_to_gsheets(module_name, bom_df)
                            if due_date or is_priority: # Update metadata if set
                                update_module_metadata_in_gsheets(module_name, due_date, is_priority)
                            
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
                if st.session_state.get("user_role", "Admin") == "Admin":
                    if st.button("🗑️ Delete", type="primary", use_container_width=True):
                        with st.spinner("Deleting module..."):
                            delete_module_from_gsheets(module_name)
                            if module_name in st.session_state.modules_db:
                                del st.session_state.modules_db[module_name]
                            st.session_state.selected_module = None
                            st.rerun()

            # --- Module Header with Priority & Due Date ---
            header_text = "📦 Module: "
            if module_data.get("is_priority"):
                header_text += "🚨 "
            header_text += module_name
            st.header(header_text)
            st.caption(f"Due Date: {module_data.get('due_date', 'Not set')}")
            st.divider()

            # --- Progress Calculation & Display ---
            total_items = len(df)
            collected_items = df["Collected"].sum()
            prekited_items = df["Prekited"].sum()
            completed_items = df["Completed"].sum()
            
            collected_pct = int((collected_items / total_items) * 100) if total_items > 0 else 0
            prekited_pct = int((prekited_items / total_items) * 100) if total_items > 0 else 0
            progress_percentage = int((completed_items / total_items) * 100) if total_items > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📦 Collected", f"{collected_pct}%", f"{collected_items} / {total_items}")
                st.progress(collected_pct / 100.0)
            with col2:
                st.metric("🔄 Prekited", f"{prekited_pct}%", f"{prekited_items} / {total_items}")
                st.progress(prekited_pct / 100.0)
            with col3:
                st.metric("🛠️ Assembled", f"{progress_percentage}%", f"{completed_items} / {total_items}")
                st.progress(progress_percentage / 100.0)
            
            if progress_percentage == 100:
                st.success("Module Complete! 🎉")
                # --- Archive Controls for Admins ---
                if st.session_state.get("user_role") == "Admin":
                    is_archived = module_data.get("archived", False)
                    if not is_archived:
                        if st.button("🗄️ Archive Module", use_container_width=True):
                            set_archive_status_in_gsheets(module_name, True)
                            st.session_state.modules_db[module_name]["archived"] = True
                            st.rerun()
                    else: # Module is archived
                        if st.button("⤴️ Unarchive Module", use_container_width=True):
                            set_archive_status_in_gsheets(module_name, False)
                            st.session_state.modules_db[module_name]["archived"] = False
                            st.rerun()

            # --- Admin Metadata Editor ---
            if st.session_state.get("user_role") == "Admin":
                with st.expander("⚙️ Edit Project Details (Admin)"):
                    new_due_date = st.date_input("Due Date", value=module_data.get("due_date"), key=f"due_{module_name}")
                    new_is_priority = st.toggle("High Priority", value=module_data.get("is_priority", False), key=f"pri_{module_name}")
                    
                    if st.button("Save Project Details", key=f"save_meta_{module_name}"):
                        # Check if values have changed before saving
                        if new_due_date != module_data.get("due_date") or new_is_priority != module_data.get("is_priority"):
                            with st.spinner("Updating metadata..."):
                                update_module_metadata_in_gsheets(module_name, new_due_date, new_is_priority)
                                st.session_state.modules_db[module_name]['due_date'] = new_due_date
                                st.session_state.modules_db[module_name]['is_priority'] = new_is_priority
                            st.success("Project details updated!")
                            st.rerun()

            st.subheader("📝 Bill of Materials Checklist")
            
            user_role = st.session_state.get("user_role", "Admin")
            can_edit_collected = user_role in ["Admin", "Worker"]
            can_edit_prekited = user_role in ["Admin", "Inventory"]
            can_edit_assembled = user_role in ["Admin", "Worker"]

            # --- Bulk Actions ---
            b_col1, b_col2, b_col3, b_col4, b_col5, b_col6 = st.columns(6)
            with b_col1:
                if st.button("📦 Collect All", use_container_width=True, disabled=not can_edit_collected):
                    st.session_state.modules_db[module_name]["bom"]["Collected"] = True
                    st.session_state.modules_db[module_name]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_module_to_gsheets(module_name, st.session_state.modules_db[module_name]["bom"])
                    st.rerun()
            with b_col2:
                if st.button("🔄 Prekit All", use_container_width=True, disabled=not can_edit_prekited):
                    st.session_state.modules_db[module_name]["bom"]["Prekited"] = True
                    st.session_state.modules_db[module_name]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_module_to_gsheets(module_name, st.session_state.modules_db[module_name]["bom"])
                    st.rerun()
            with b_col3:
                if st.button("✅ Assemble All", use_container_width=True, disabled=not can_edit_assembled):
                    st.session_state.modules_db[module_name]["bom"]["Completed"] = True
                    st.session_state.modules_db[module_name]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_module_to_gsheets(module_name, st.session_state.modules_db[module_name]["bom"])
                    st.rerun()
            with b_col4:
                if st.button("📦 Uncollect All", use_container_width=True, disabled=not can_edit_collected):
                    st.session_state.modules_db[module_name]["bom"]["Collected"] = False
                    st.session_state.modules_db[module_name]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_module_to_gsheets(module_name, st.session_state.modules_db[module_name]["bom"])
                    st.rerun()
            with b_col5:
                if st.button("🔄 Unprekit All", use_container_width=True, disabled=not can_edit_prekited):
                    st.session_state.modules_db[module_name]["bom"]["Prekited"] = False
                    st.session_state.modules_db[module_name]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_module_to_gsheets(module_name, st.session_state.modules_db[module_name]["bom"])
                    st.rerun()
            with b_col6:
                if st.button("❌ Unassemble All", use_container_width=True, disabled=not can_edit_assembled):
                    st.session_state.modules_db[module_name]["bom"]["Completed"] = False
                    st.session_state.modules_db[module_name]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_module_to_gsheets(module_name, st.session_state.modules_db[module_name]["bom"])
                    st.rerun()

            # --- Interactive Form ---
            def highlight_rows(row):
                # 1. Highlight rows with issues/notes in bold red
                if pd.notna(row.get('Notes')) and str(row.get('Notes')).strip() != "":
                    return ['background-color: #FF4B4B; color: white; font-weight: bold;'] * len(row)
                # 2. Highlight fully assembled rows in light green
                elif row.get('Completed'):
                    return ['background-color: rgba(46, 204, 113, 0.3)'] * len(row)
                # 3. Highlight prekited rows in light blue
                elif row.get('Prekited'):
                    return ['background-color: rgba(52, 152, 219, 0.3)'] * len(row)
                # 4. Highlight collected rows in light orange
                elif row.get('Collected'):
                    return ['background-color: rgba(243, 156, 18, 0.3)'] * len(row)
                # 5. Default color for everything else
                return [''] * len(row)
                
            styled_df = df.style.apply(highlight_rows, axis=1)

            with st.form(key=f"form_{module_name}"):
                edited_df = st.data_editor(
                    styled_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Collected": st.column_config.CheckboxColumn("Collected?", default=False, disabled=not can_edit_collected),
                        "Prekited": st.column_config.CheckboxColumn("Prekited?", default=False, disabled=not can_edit_prekited),
                        "Completed": st.column_config.CheckboxColumn("Assembled?", default=False, disabled=not can_edit_assembled),
                        "BOM_ID": st.column_config.TextColumn("BOM ID", disabled=True),
                        "UIN": st.column_config.TextColumn("UIN", disabled=True),
                        "Quantity": st.column_config.TextColumn("Qty", disabled=True),
                        "Description": st.column_config.TextColumn("Description", disabled=True),
                        "Notes": st.column_config.TextColumn("Issue / Notes", default="")
                    }
                )
                submit_progress = st.form_submit_button("💾 Save Progress")
                
            if submit_progress:
                with st.spinner("Saving to Google Sheets..."):
                    # Update local memory
                    st.session_state.modules_db[module_name]["bom"] = edited_df
                    st.session_state.modules_db[module_name]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # Update Google Sheets
                    save_module_to_gsheets(module_name, edited_df)
                st.rerun()

        # --- MASTER VIEW (GRID) ---
        else:
            st.header("📊 Module Dashboard")
            if not st.session_state.modules_db:
                st.info("Your dashboard is empty. Please go to 'Upload New Module' to add some PDFs.")
            else:
                active_modules = {k: v for k, v in st.session_state.modules_db.items() if not v.get("archived", False)}
                archived_modules = {k: v for k, v in st.session_state.modules_db.items() if v.get("archived", False)}

                active_tab, archived_tab = st.tabs([f"🚀 Active Modules ({len(active_modules)})", f"🗄️ Archived Modules ({len(archived_modules)})"])

                with active_tab:
                    if not active_modules:
                        st.info("All modules are archived or the dashboard is empty. Check the 'Archived Modules' tab or upload a new module.")
                    else:
                        st.write("Select a module to view its checklist.")
                        # --- Overall Progress Chart ---
                        with st.expander("📈 View Overall Progress", expanded=True):
                            chart_data = []
                            total_global_items, total_global_collected, total_global_prekited, total_global_completed = 0, 0, 0, 0
                            
                            for name, data in active_modules.items():
                                df_mod, tot = data["bom"], len(data["bom"])
                                col, pre, comp = df_mod["Collected"].sum(), df_mod["Prekited"].sum(), df_mod["Completed"].sum()
                                chart_data.append({"Module": name, "Collected %": int((col/tot)*100 if tot>0 else 0), "Prekited %": int((pre/tot)*100 if tot>0 else 0), "Completed %": int((comp/tot)*100 if tot>0 else 0)})
                                total_global_items += tot
                                total_global_collected += col
                                total_global_prekited += pre
                                total_global_completed += comp
                                
                            global_col_pct = int((total_global_collected / total_global_items) * 100) if total_global_items > 0 else 0
                            global_pre_pct = int((total_global_prekited / total_global_items) * 100) if total_global_items > 0 else 0
                            global_pct = int((total_global_completed / total_global_items) * 100) if total_global_items > 0 else 0
                            
                            prog_col1, prog_col2, prog_col3 = st.columns(3)
                            prog_col1.metric("Overall Collected", f"{global_col_pct}%", f"{total_global_collected} / {total_global_items} Items")
                            prog_col2.metric("Overall Prekited", f"{global_pre_pct}%", f"{total_global_prekited} / {total_global_items} Items")
                            prog_col3.metric("Overall Assembled", f"{global_pct}%", f"{total_global_completed} / {total_global_items} Items")
                            
                            # Use Altair to force Y-axis from 0 to 100 with 5% steps
                            if chart_data:
                                chart_df = pd.DataFrame(chart_data)
                                melted_df = chart_df.melt(id_vars=["Module"], value_vars=["Collected %", "Prekited %", "Completed %"], var_name="Stage", value_name="Percentage")
                                bar_chart = alt.Chart(melted_df).mark_bar().encode(
                                    x=alt.X('Module:N', title='Module', axis=alt.Axis(labelAngle=-45)),
                                    y=alt.Y('Percentage:Q', scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(values=list(range(0, 101, 5)), title='Percentage (%)')),
                                    color=alt.Color('Stage:N', legend=alt.Legend(title="Progress", orient="top")),
                                    xOffset='Stage:N'
                                ).properties(height=400)
                                st.altair_chart(bar_chart, use_container_width=True)

                        # --- Global Issues Tracker ---
                        with st.expander("🚨 Global Issues & Bottlenecks", expanded=False):
                            all_issues = [issues_df.assign(Module=name) for name, data in active_modules.items() if not (issues_df := data["bom"][data["bom"]["Notes"].fillna("").astype(str).str.strip() != ""]).empty]
                            if all_issues:
                                st.dataframe(pd.concat(all_issues, ignore_index=True), hide_index=True, use_container_width=True)
                            else:
                                st.success("No issues or notes logged across any active modules! 🎉")

                        st.divider()

                        # --- Master Report Export ---
                        with st.expander("📊 Download Master Report"):
                            st.write("Generate a CSV report of the current status of all active modules.")
                            report_data = []
                            for name, data in active_modules.items():
                                df_mod, tot = data["bom"], len(data["bom"])
                                col, pre, comp = df_mod["Collected"].sum(), df_mod["Prekited"].sum(), df_mod["Completed"].sum()
                                num_issues = len(df_mod[df_mod["Notes"].fillna("").astype(str).str.strip() != ""])
                                report_data.append({
                                    "Module Name": name, "Collected %": int((col/tot)*100 if tot>0 else 0),
                                    "Prekited %": int((pre/tot)*100 if tot>0 else 0), "Assembled %": int((comp/tot)*100 if tot>0 else 0),
                                    "Open Issues": num_issues, "Last Updated": data.get("last_updated", "Unknown"),
                                    "Due Date": data.get("due_date"), "High Priority": data.get("is_priority", False)
                                })
                            if report_data:
                                report_df = pd.DataFrame(report_data)
                                report_csv = report_df.to_csv(index=False).encode('utf-8')
                                st.download_button("📥 Download Report", data=report_csv, file_name="NPSG_Master_Report.csv", mime="text/csv")
                        
                        # --- Smart Quick Filters ---
                        quick_filter = st.radio("🎯 Smart Quick-Filters", ["All Modules", "📦 Needs Collecting", "🔄 Ready for Prekit", "🛠️ Ready for Assembly"], horizontal=True, key="active_quick_filter")

                        # --- Search and Sort Controls ---
                        ctrl_col1, ctrl_col2 = st.columns([3, 1])
                        search_term = ctrl_col1.text_input("🔍 Search Modules", placeholder="Type to filter by module name...")
                        sort_order = ctrl_col2.selectbox("↕️ Sort By", ["Priority", "Due Date (Soonest First)", "Name (A-Z)", "Name (Z-A)", 
                                                                      "Completion (High - Low)", "Completion (Low - High)"])
                        
                        # Prepare filtered and calculated list
                        module_items = []
                        for name, data in active_modules.items():
                            if search_term.lower() in name.lower():
                                df_mod, tot = data["bom"], len(data["bom"])
                                col_pct, pre_pct, pct = (int((s/tot)*100) if tot>0 else 0 for s in (df_mod["Collected"].sum(), df_mod["Prekited"].sum(), df_mod["Completed"].sum()))
                                
                                if (quick_filter == "📦 Needs Collecting" and col_pct >= 100) or \
                                   (quick_filter == "🔄 Ready for Prekit" and (col_pct < 100 or pre_pct >= 100)) or \
                                   (quick_filter == "🛠️ Ready for Assembly" and (pre_pct < 100 or pct >= 100)):
                                    continue
                                module_items.append({
                                    "name": name, "col_pct": col_pct, "pre_pct": pre_pct, "pct": pct, 
                                    "last_updated": data.get("last_updated", "Unknown"),
                                    "due_date": data.get("due_date"), "is_priority": data.get("is_priority", False)
                                })
                        
                        # Apply Sorting
                        if sort_order == "Priority":
                            module_items.sort(key=lambda x: (x['is_priority'], x.get('due_date') is None, x.get('due_date')), reverse=True)
                        elif sort_order == "Due Date (Soonest First)":
                            module_items.sort(key=lambda x: (x.get('due_date') is None, x.get('due_date')))
                        elif "Name" in sort_order:
                            module_items.sort(key=lambda x: x['name'], reverse=("Z-A" in sort_order))
                        elif "Completion" in sort_order:
                            module_items.sort(key=lambda x: x['pct'], reverse=("High - Low" in sort_order))
                        
                        if not module_items:
                            st.warning("No modules found matching your search or filter.")
                        else:
                            # --- Pagination Logic ---
                            ITEMS_PER_PAGE = 12
                            total_pages = (len(module_items) - 1) // ITEMS_PER_PAGE + 1
                            st.session_state.current_page = min(st.session_state.current_page, total_pages - 1)

                            start_idx = st.session_state.current_page * ITEMS_PER_PAGE
                            end_idx = start_idx + ITEMS_PER_PAGE
                            paginated_items = module_items[start_idx:end_idx]

                            # --- Display Paginated Items ---
                            for i in range(0, len(paginated_items), 3):
                                cols = st.columns(3)
                                for j, mod_dict in enumerate(paginated_items[i:i+3]):
                                    with cols[j]:
                                        with st.container(border=True):
                                            card_header = "📦 "
                                            if mod_dict.get("is_priority"):
                                                card_header += "🚨 "
                                            card_header += mod_dict['name']
                                            st.subheader(card_header)

                                            due_date_str = f"Due: {mod_dict['due_date']}" if mod_dict.get('due_date') else "No due date"
                                            st.caption(f"{due_date_str} | ⏳ Last updated: {mod_dict['last_updated']}")
                                            
                                            # Use HTML flexbox to force columns and prevent Streamlit from collapsing them into rows
                                            metrics_html = f"""
                                            <div style="display: flex; gap: 10px; margin-bottom: 15px;">
                                                <div style="flex: 1; background-color: rgba(150, 150, 150, 0.1); padding: 8px; border-radius: 8px; text-align: center;">
                                                    <div style="font-size: 0.8rem; margin-bottom: 4px; opacity: 0.8;">Collected</div>
                                                    <div style="font-size: 1.2rem; font-weight: bold;">{mod_dict['col_pct']}%</div>
                                                </div>
                                                <div style="flex: 1; background-color: rgba(150, 150, 150, 0.1); padding: 8px; border-radius: 8px; text-align: center;">
                                                    <div style="font-size: 0.8rem; margin-bottom: 4px; opacity: 0.8;">Prekited</div>
                                                    <div style="font-size: 1.2rem; font-weight: bold;">{mod_dict['pre_pct']}%</div>
                                                </div>
                                                <div style="flex: 1; background-color: rgba(150, 150, 150, 0.1); padding: 8px; border-radius: 8px; text-align: center;">
                                                    <div style="font-size: 0.8rem; margin-bottom: 4px; opacity: 0.8;">Assembled</div>
                                                    <div style="font-size: 1.2rem; font-weight: bold;">{mod_dict['pct']}%</div>
                                                </div>
                                            </div>
                                            """
                                            st.markdown(metrics_html, unsafe_allow_html=True)
                                            
                                            if st.button("View Checklist", key=f"view_{mod_dict['name']}", use_container_width=True):
                                                st.session_state.selected_module = mod_dict['name']
                                                st.rerun()
                            
                            st.divider()

                            # --- Pagination Controls ---
                            if total_pages > 1:
                                p_col1, p_col2, p_col3 = st.columns([3, 4, 3])
                                with p_col1:
                                    if st.button("← Previous", use_container_width=True, disabled=(st.session_state.current_page == 0)):
                                        st.session_state.current_page -= 1
                                        st.rerun()
                                with p_col2:
                                    st.write(f"Page **{st.session_state.current_page + 1}** of **{total_pages}**")
                                with p_col3:
                                    if st.button("Next →", use_container_width=True, disabled=(st.session_state.current_page >= total_pages - 1)):
                                        st.session_state.current_page += 1
                                        st.rerun()
                with archived_tab:
                    st.write("These modules are 100% complete and have been archived to keep the active dashboard clean.")
                    if not archived_modules:
                        st.info("No modules have been archived yet.")
                    else:
                        for name, data in sorted(archived_modules.items()):
                            with st.container(border=True):
                                a_col1, a_col2 = st.columns([4,1])
                                with a_col1:
                                    st.subheader(name)
                                    st.caption(f"Archived on or after: {data.get('last_updated', 'N/A')}")
                                with a_col2:
                                    if st.button("View Details", key=f"view_archived_{name}", use_container_width=True):
                                        st.session_state.selected_module = name
                                        st.rerun()
