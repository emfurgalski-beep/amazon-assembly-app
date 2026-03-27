import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

# --- Page Configuration ---
st.set_page_config(page_title="Assembly Extractor", layout="wide")

# --- Authentication Logic ---
def check_password():
    """Returns `True` if the user entered the correct password."""
    def password_entered():
        if st.session_state.get("password") == st.secrets.get("app_password"):
            st.session_state["password_correct"] = True
            if "password" in st.session_state:
                del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input(
        "Please enter the password to access the dashboard",
        type="password",
        on_change=password_entered,
        key="password"
    )
    if "password_correct" in st.session_state and not st.session_state.password_correct:
        st.error("😕 Password incorrect")
    return False

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

# --- UI Rendering Functions ---

def render_master_view():
    """Renders the main dashboard grid with all module cards."""
    st.title("📊 Module Dashboard")
    if not st.session_state.modules_db:
        st.info("Your dashboard is empty. Please go to 'Upload New Module' to add some PDFs.")
        return

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
                        
                        # This button sets the state to switch to the detail view
                        if st.button("View Checklist", key=f"view_{module_name}", use_container_width=True):
                            st.session_state.selected_module = module_name
                            st.rerun()

def render_detail_view():
    """Renders the full-page checklist for the selected module."""
    module_name = st.session_state.selected_module
    module_data = st.session_state.modules_db[module_name]
    df = module_data["bom"]

    # Back button to reset the state and return to the master view
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
        if st.form_submit_button("💾 Save Progress"):
            st.session_state.modules_db[module_name]["bom"] = edited_df
            st.rerun()

# ==========================================
# MAIN APP LOGIC (Protected by Password)
# ==========================================
if check_password():
    # Initialize session state variables
    if 'modules_db' not in st.session_state:
        st.session_state.modules_db = {}
    if 'selected_module' not in st.session_state:
        st.session_state.selected_module = None

    # Sidebar Navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Upload New Module", "Dashboard"])
    if st.sidebar.button("Log Out"):
        st.session_state.password_correct = False
        st.session_state.selected_module = None
        st.rerun()

    # Page Routing
    if page == "Upload New Module":
        st.title("📤 Upload Amazon Assembly Module")
        uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
        if uploaded_file is not None:
            module_name = uploaded_file.name.replace('.pdf', '')
            if module_name in st.session_state.modules_db:
                st.warning(f"Module '{module_name}' is already in your Dashboard!")
            else:
                with st.spinner("Extracting BOM..."):
                    bom_df = process_pdf(uploaded_file.read())
                    if not bom_df.empty:
                        st.session_state.modules_db[module_name] = {"bom": bom_df}
                        st.success(f"Successfully processed and saved '{module_name}'!")
                        st.balloons()
                    else:
                        st.error("Could not find a valid BOM in this document.")

    elif page == "Dashboard":
        # This is the core navigation logic:
        # If a module is selected, render its detail page.
        # Otherwise, render the main grid.
        if st.session_state.selected_module:
            render_detail_view()
        else:
            render_master_view()
