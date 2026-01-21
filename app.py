import streamlit as st
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
from src.document_parser import DocumentParser
from src.analyzer import PitchDeckAnalyzer
from src.memo_generator import MemoGenerator
from src.exporter import Exporter
from src.models import PitchDeckData, InvestmentMemo, ExecutiveSummary


# --- Page Config ---
st.set_page_config(
    page_title="Pitch Deck Analyzer - HatchUp",
    page_icon="🥚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for "Premium" Feel ---


# --- Custom CSS for "Premium" Feel ---
# Removed to prevent conflicts with user theme settings (Dark/Light mode)


# --- Sidebar & Setup ---
with st.sidebar:
    st.title("🥚 HatchUp for VCs")
    st.markdown("---")
    

    st.info("Upload a Pitch Deck (PDF, PPTX, or Image) to begin analysis.")
    st.caption("Powered by HatchUp.ai")

# --- Main App Logic ---

st.title("Pitch Deck Analyzer")
st.markdown("Generated structured insights, investment memos, and executive summaries in seconds.")

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

# File Uploader
uploaded_file = st.file_uploader("Upload Pitch Deck", type=["pdf", "pptx", "ppt", "png", "jpg", "jpeg"])

if uploaded_file and not os.environ.get("GROQ_API_KEY"):
    st.error("GROQ_API_KEY not found. Please check your .env file.")

if uploaded_file and st.button("Analyze Deck") and os.environ.get("GROQ_API_KEY"):
    # Hardcoded model
    model_choice = "openai/gpt-oss-20b"
    
    with st.spinner("Reading Document..."):
        try:
            # 1. Parse Document
            raw_text = DocumentParser.parse_file(uploaded_file)
            description_preview = raw_text[:500] + "..." if len(raw_text) > 500 else raw_text
            # st.expander("Show extracted text").text(description_preview) # Debug

            
            # 2. Extract Data
            with st.spinner("Extracting Insights (Analyst Agent)..."):
                analyzer = PitchDeckAnalyzer(api_key=os.environ["GROQ_API_KEY"], model_name=model_choice)
                deck_data: PitchDeckData = analyzer.analyze_pitch_deck(raw_text)
            
            # 3. Generate Memo & Summary
            with st.spinner("Drafting Memo (Partner Agent)..."):
                generator = MemoGenerator(api_key=os.environ["GROQ_API_KEY"], model_name=model_choice)
                memo: InvestmentMemo = generator.generate_memo(deck_data)
                
            with st.spinner("Finalizing Executive Summary..."):
                summary: ExecutiveSummary = generator.generate_executive_summary(deck_data, memo)
                
            # Store in session state
            st.session_state.analysis_result = {
                "data": deck_data,
                "memo": memo,
                "summary": summary
            }
            st.success("Analysis Complete!")
            
        except Exception as e:
            st.error(f"An error occurred during analysis: {str(e)}")

# --- Display Results ---
if st.session_state.analysis_result:
    res = st.session_state.analysis_result
    data = res["data"]
    memo = res["memo"]
    summary = res["summary"]
    
    # Layout Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["⚡ Executive Summary", "📊 Extracted Data", "🚩 Red Flags", "📝 Investment Memo"])
    
    with tab1:
        st.header("Executive Summary")
        
        # Determine color for outlook
        outlook = summary.decision_outlook.lower()
        color = "gray"
        if "positive" in outlook: color = "green"
        elif "negative" in outlook: color = "red"
        
        st.markdown(f"**Outlook**: :{color}[{summary.decision_outlook}]")
        
        st.subheader("Key Highlights")
        for point in summary.summary_bullet_points:
            st.markdown(f"- {point}")
            
        st.divider()
        st.subheader("Company Identity")
        c1, c2 = st.columns(2)
        c1.metric("Startup", data.startup_name)
        c2.metric("Stage / Ask", data.funding_ask_stage)
        
    with tab2:
        st.header("Structured Data Extraction")
        st.markdown("From Pitch Deck")
        
        # Display as a clean table-like format using JSON or dataframe
        # We can make specific cards
        
        with st.expander("Problem & Solution", expanded=True):
            st.markdown(f"**Problem**\n\n{data.problem}")
            st.markdown(f"**Solution**\n\n{data.solution}")
            
        with st.expander("Product, Market & Business Model", expanded=True):
            st.markdown(f"**Product**\n\n{data.product}")
            st.markdown(f"**Market / TAM**\n\n{data.market_tam}")
            st.markdown(f"**Business Model**\n\n{data.business_model}")

        with st.expander("Traction & Competition", expanded=False):
            st.markdown(f"**Traction**\n\n{data.traction_metrics}")
            st.markdown(f"**Competition**\n\n{data.competitive_landscape}")
            
        with st.expander("Team", expanded=False):
            st.markdown(f"{data.team}")
            
        # Excel Download
        excel_data = Exporter.to_excel(data)
        st.download_button(
            label="Download Data (.xlsx)",
            data=excel_data,
            file_name=f"{data.startup_name}_hatchup_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with tab3:
        st.header("Risk Analysis")
        
        c1, c2, c3 = st.columns(3)
        
        with c1:
            st.error(f"Red Flags ({len(data.red_flags)})")
            for flag in data.red_flags:
                st.markdown(f"- {flag}")
                
        with c2:
            st.warning(f"Weak Signals ({len(data.weak_signals)})")
            for signal in data.weak_signals:
                st.markdown(f"- {signal}")
                
        with c3:
            st.info(f"Missing Sections ({len(data.missing_sections)})")
            for gap in data.missing_sections:
                st.markdown(f"- {gap}")

    with tab4:
        st.header("Investment Memo")
        st.caption("Generated Draft - Review before sharing.")
        
        st.markdown(f"## {data.startup_name} - Investment Memo")
        st.markdown(f"**Overview:** {memo.company_overview}")
        st.markdown("---")
        st.markdown(f"### Problem & Solution\n{memo.problem_solution_clarity}")
        st.markdown(f"### Market Opportunity\n{memo.market_opportunity}")
        st.markdown(f"### Product & Diffferentiation\n{memo.product_differentiation}")
        st.markdown(f"### Traction\n{memo.traction_metrics_analysis}")
        st.markdown(f"### Team\n{memo.team_assessment}")
        st.markdown(f"### Risks\n{memo.risks_concerns}")
        st.markdown(f"### Open Questions\n{memo.open_questions}")
        st.markdown(f"### Assessment\n{memo.neutral_assessment}")
        
        st.divider()
        
        # Exports
        col1, col2 = st.columns(2)
        
        text_memo = Exporter.to_text_memo(memo, data.startup_name)
        col1.download_button(
            label="Download Memo (TXT)",
            data=text_memo,
            file_name=f"{data.startup_name}_memo.txt",
            mime="text/plain"
        )
        
        pdf_memo = Exporter.to_pdf_memo(memo, data.startup_name)
        col2.download_button(
            label="Download Memo (PDF)",
            data=pdf_memo,
            file_name=f"{data.startup_name}_memo.pdf",
            mime="application/pdf"
        )
