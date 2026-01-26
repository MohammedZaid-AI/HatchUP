import streamlit as st
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.models import PitchDeckData, InvestmentMemo
from src.memo_generator import MemoGenerator
from src.exporter import Exporter

st.set_page_config(
    page_title="Create Memo - HatchUp",
    page_icon="📝",
    layout="wide"
)

st.title("📝 Create Investment Memo")
st.markdown("Manually draft or regenerate an investment memo from existing data.")

# Check for data in session state from the Analyzer page
if "analysis_result" in st.session_state and st.session_state.analysis_result:
    data = st.session_state.analysis_result["data"]
    st.success(f"Loaded data for **{data.startup_name}** from Analyzer.")
else:
    st.info("No analysis data found. You can start fresh or go back to 'Analyze Deck' to extract data first.")
    data = None

# --- Form for Manual Entry / Editing ---
with st.form("memo_form"):
    startup_name = st.text_input("Startup Name", value=data.startup_name if data else "")
    
    c1, c2 = st.columns(2)
    with c1:
        problem = st.text_area("Problem", value=data.problem if data else "", height=150)
        solution = st.text_area("Solution", value=data.solution if data else "", height=150)
        market = st.text_area("Market / TAM", value=data.market_tam if data else "", height=150)
        
    with c2:
        product = st.text_area("Product", value=data.product if data else "", height=150)
        traction = st.text_area("Traction", value=data.traction_metrics if data else "", height=150)
        team = st.text_area("Team", value=data.team if data else "", height=150)

    # Hidden fields context for the generator
    # We reconstruct a PitchDeckData-like dict/object to pass to the generator if needed
    
    generate_btn = st.form_submit_button("Generate Memo")

if generate_btn and os.environ.get("GROQ_API_KEY"):
    # Construct a temporary data object
    # We use the PitchDeckData model, filling missing fields with "N/A" for manual entry
    try:
        current_data = PitchDeckData(
            startup_name=startup_name,
            problem=problem,
            solution=solution,
            product=product,
            market_tam=market,
            business_model="N/A", # Simplified for this form
            traction_metrics=traction,
            team=team,
            competitive_landscape="N/A",
            funding_ask_stage="N/A",
            missing_sections=[],
            weak_signals=[],
            red_flags=[]
        )
        
        with st.spinner("Drafting Memo..."):
            model_choice = "openai/gpt-oss-20b"
            generator = MemoGenerator(api_key=os.environ["GROQ_API_KEY"], model_name=model_choice)
            memo = generator.generate_memo(current_data)
            
            # Update session state so the Research Engine can use this latest data
            if "analysis_result" not in st.session_state or st.session_state.analysis_result is None:
                st.session_state.analysis_result = {}
            
            st.session_state.analysis_result["data"] = current_data
            st.session_state.analysis_result["memo"] = memo
            
            st.subheader("Generated Memo")
            st.markdown(f"**Overview:** {memo.company_overview}")
            st.markdown(f"### Problem & Solution\n{memo.problem_solution_clarity}")
            st.markdown(f"### Market Opportunity\n{memo.market_opportunity}")
            st.markdown(f"### Product\n{memo.product_differentiation}")
            st.markdown(f"### Traction\n{memo.traction_metrics_analysis}")
            st.markdown(f"### Team\n{memo.team_assessment}")
            st.markdown(f"### Risks\n{memo.risks_concerns}")
            st.markdown(f"### Assessment\n{memo.neutral_assessment}")
            
            # Downloads
            col1, col2 = st.columns(2)
            text_memo = Exporter.to_text_memo(memo, startup_name)
            col1.download_button("Download TXT", text_memo, file_name=f"{startup_name}_memo.txt")
            
            pdf_memo = Exporter.to_pdf_memo(memo, startup_name)
            col2.download_button("Download PDF", pdf_memo, file_name=f"{startup_name}_memo.pdf", mime="application/pdf")
            
    except Exception as e:
        st.error(f"Error generating memo: {e}")
elif generate_btn and not os.environ.get("GROQ_API_KEY"):
    st.error("GROQ_API_KEY not found in .env")
