import streamlit as st
import google.generativeai as genai
from streamlit_mic_recorder import mic_recorder
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import io
import datetime
import pandas as pd
import zipfile
from PIL import Image

# ==========================================
# 1. SETUP & STYLING
# ==========================================
st.set_page_config(page_title="ClaimScribe V3", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; font-family: 'Inter', sans-serif; }
    h1 { color: #1e3a8a; font-weight: 800; }
    .input-card { background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }
    div.stButton > button { background-color: #2563eb; color: white; border-radius: 8px; border: none; padding: 0.6rem 1.2rem; font-weight: 600; width: 100%; }
    div.stButton > button:hover { background-color: #1d4ed8; }
</style>
""", unsafe_allow_html=True)

# 🔑 HARDCODE API KEY HERE
api_key = "AIzaSyBkLvLcfwhCf0G7bWg_QJXZDI-cb12NG04"

# Load Truth Data (Price List)
@st.cache_data
def load_truth_data():
    try:
        df = pd.read_csv("codes.csv")
        return df.to_string(index=False), True
    except FileNotFoundError:
        return "", False

xactimate_database, database_loaded = load_truth_data()

# Session State
if "generated_report" not in st.session_state: st.session_state.generated_report = None
if "scope_items" not in st.session_state: st.session_state.scope_items = []
if "renamed_zip" not in st.session_state: st.session_state.renamed_zip = None

# ==========================================
# 2. SIDEBAR (The "Brain" Configuration)
# ==========================================
with st.sidebar:
    st.title("🛡️ ClaimScribe V3")
    
    # 1. Carrier Selection
    st.subheader("1. Client Profile")
    target_carrier = st.text_input("Carrier Name", value="State Farm", placeholder="e.g. State Farm, USAA...")
    
    # 2. THE NEW FEATURE: Dynamic Guideline Ingestion
    st.subheader("2. Deployment Guidelines")
    st.caption("Paste the actual 'Style Sheet' or email instructions here. The AI will strictly enforce these rules.")
    custom_guidelines = st.text_area("Paste Guidelines", height=150, placeholder="Example: 'Use strict passive voice. Never use the word 'rot'. Always mention the age of the roof in the first paragraph.'")
    
    st.divider()
    
    # 3. Loss Context
    loss_type = st.selectbox("Loss Type", ["Water (Pipe Burst)", "Water (Flood)", "Fire/Smoke", "Wind/Hail", "Theft/Vandalism"])
    
    if database_loaded:
        st.success("✅ Price List Database Loaded")
    else:
        st.warning("⚠️ No 'codes.csv' found. AI is guessing prices.")

# ==========================================
# 3. CORE AI FUNCTIONS
# ==========================================

def analyze_media(media_bytes, mime_type):
    if "PASTE_YOUR" in api_key:
        st.error("⚠️ API Key Missing! Update Line 30.")
        return None

    genai.configure(api_key=api_key)
    
    # DYNAMIC PROMPT LOGIC
    # If user pasted guidelines, use them. If not, ask AI to use its training data.
    if custom_guidelines:
        guideline_instruction = f"STRICTLY FOLLOW THESE USER PROVIDED GUIDELINES:\n{custom_guidelines}"
    else:
        guideline_instruction = f"NO GUIDELINES PROVIDED. Use your internal training data to adopt the standard persona and reporting style of {target_carrier}."

    sys_prompt = f"""
    You are a Senior Insurance Adjuster working for {target_carrier}.
    
    CONTEXT:
    - Loss Type: {loss_type}
    
    {guideline_instruction}
    
    TRUTH DATABASE (Xactimate Codes):
    {xactimate_database}
    
    YOUR MISSION:
    1. Listen to the field notes.
    2. Write a Risk Narrative.
       - If specific guidelines were provided above, you MUST follow them exactly.
       - If not, use the professional tone typical for {target_carrier}.
    3. Generate a Scope of Work.
       - Use ONLY codes from the Truth Database if available.
    
    OUTPUT FORMAT:
    ---NARRATIVE START---
    (The text)
    ---NARRATIVE END---
    ---SCOPE START---
    (Code) | (Desc) | (Qty)
    ---SCOPE END---
    """
    
    try:
        # Using 2.5-flash as requested
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content([sys_prompt, {"mime_type": mime_type, "data": media_bytes}])
        return response.text
    except Exception as e:
        st.error(f"Engine Error: {e}")
        return None

def process_photos(uploaded_files):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    renamed_images = []
    
    progress_bar = st.progress(0)
    
    for i, file in enumerate(uploaded_files):
        try:
            image_data = Image.open(file)
            # AI creates the name based on the Carrier Context
            prompt = f"Rename this photo for a {target_carrier} claim. Guideline: {custom_guidelines}. Format: Room_Detail_Condition.jpg. Return ONLY filename."
            response = model.generate_content([prompt, image_data])
            new_name = response.text.strip().replace(" ", "_").replace(".jpg", "") + ".jpg"
            renamed_images.append((new_name, file))
        except:
            renamed_images.append((f"Image_{i}.jpg", file))
        progress_bar.progress((i + 1) / len(uploaded_files))
            
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for name, original_file in renamed_images:
            original_file.seek(0)
            zip_file.writestr(name, original_file.read())
    return zip_buffer.getvalue()

def generate_pdf(narrative, scope_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    story.append(Paragraph(f"{target_carrier} Field Report", styles['Title']))
    story.append(Paragraph(f"Loss: {loss_type} | Date: {datetime.date.today()}", styles['Normal']))
    story.append(Spacer(1, 24))
    
    story.append(Paragraph("<b>Risk Narrative</b>", styles['Heading2']))
    story.append(Paragraph(narrative.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 24))
    
    if scope_data:
        story.append(Paragraph("<b>Preliminary Scope</b>", styles['Heading2']))
        table_data = [["Selector", "Description", "Qty"]] 
        for item in scope_data:
            table_data.append([item['code'], item['desc'], item['qty']])
        
        t = Table(table_data, colWidths=[80, 300, 50])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        story.append(t)
        
    doc.build(story)
    buffer.seek(0)
    return buffer

# ==========================================
# 4. MAIN DASHBOARD UI
# ==========================================

st.title("🛡️ ClaimScribe V3")
st.caption("AI-Powered Field Assistant")

tab_narrative, tab_photos = st.tabs(["🎙️ Narrative Engine", "📸 Photo Engine"])

# --- TAB 1 ---
with tab_narrative:
    col_input, col_output = st.columns([1, 1], gap="large")
    
    with col_input:
        st.markdown('<div class="input-card">', unsafe_allow_html=True)
        st.markdown("#### 1. Input Field Data")
        
        # Audio
        audio = mic_recorder(start_prompt="🔴 Record Voice Note", stop_prompt="⏹️ Stop", key="recorder", use_container_width=True)
        
        # Upload
        uploaded_file = st.file_uploader("Or Upload Media", type=["mp4", "mov", "wav", "mp3"])
        
        input_bytes = None
        input_mime = None
        
        if audio:
            input_bytes = audio['bytes']
            input_mime = "audio/wav"
        elif uploaded_file:
            input_bytes = uploaded_file.getvalue()
            input_mime = uploaded_file.type
            
        if input_bytes:
            st.divider()
            if st.button("🚀 Generate Report", type="primary"):
                with st.spinner("Analyzing against guidelines..."):
                    raw_text = analyze_media(input_bytes, input_mime)
                    if raw_text:
                        try:
                            narrative = raw_text.split("---NARRATIVE START---")[1].split("---NARRATIVE END---")[0].strip()
                            scope = raw_text.split("---SCOPE START---")[1].split("---SCOPE END---")[0].strip()
                            st.session_state.generated_report = narrative
                            scope_items = []
                            for line in scope.split('\n'):
                                if "|" in line:
                                    parts = [p.strip() for p in line.split('|')]
                                    if len(parts) >= 3:
                                        scope_items.append({"code": parts[0], "desc": parts[1], "qty": parts[2]})
                            st.session_state.scope_items = scope_items
                        except:
                            st.error("AI Response Error. Please try again.")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_output:
        if st.session_state.generated_report:
            st.markdown("#### 2. Review")
            st.text_area("Narrative", value=st.session_state.generated_report, height=250)
            
            if st.session_state.scope_items:
                st.dataframe(st.session_state.scope_items, use_container_width=True)
            
            pdf = generate_pdf(st.session_state.generated_report, st.session_state.scope_items)
            st.download_button("📄 Download PDF", data=pdf, file_name="Report.pdf", mime="application/pdf")
        else:
            st.info("👈 Record audio to generate report.")

# --- TAB 2 ---
with tab_photos:
    st.markdown('<div class="input-card">', unsafe_allow_html=True)
    st.markdown("#### Bulk Photo Renamer")
    st.write(f"Renaming photos for **{target_carrier}**.")
    if custom_guidelines:
        st.caption(f"Applying custom rules: {custom_guidelines[:50]}...")
    
    photos = st.file_uploader("Drop Photos Here", accept_multiple_files=True, type=['jpg', 'png'])
    
    if photos and st.button("⚡ Process Batch"):
        zip_data = process_photos(photos)
        st.session_state.renamed_zip = zip_data
        st.success("Done!")
            
    if st.session_state.renamed_zip:
        st.download_button("⬇️ Download ZIP", data=st.session_state.renamed_zip, file_name="Photos.zip", mime="application/zip", type="primary")
    st.markdown('</div>', unsafe_allow_html=True)