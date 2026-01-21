import pandas as pd
from fpdf import FPDF
from src.models import PitchDeckData, InvestmentMemo
import io

class Exporter:
    @staticmethod
    def to_excel(data: PitchDeckData) -> bytes:
        """
        Converts extracted PitchDeckData to an Excel file bytes object.
        """
        # Create a dictionary for the dataframe
        # We flatten lists (missing_sections, etc) to strings for CSV/Excel cells
        flat_data = {
            "Field": [],
            "Value": []
        }
        
        # Core Fields
        core_fields = [
            ("Startup Name", data.startup_name),
            ("Problem", data.problem),
            ("Solution", data.solution),
            ("Product", data.product),
            ("Market / TAM", data.market_tam),
            ("Business Model", data.business_model),
            ("Traction", data.traction_metrics),
            ("Team", data.team),
            ("Competition", data.competitive_landscape),
            ("Funding Ask/Stage", data.funding_ask_stage)
        ]
        
        for k, v in core_fields:
            flat_data["Field"].append(k)
            flat_data["Value"].append(v)
            
        # Analysis Lists
        lists = [
            ("Missing Sections", data.missing_sections),
            ("Weak Signals", data.weak_signals),
            ("Red Flags", data.red_flags)
        ]
        
        for k, v in lists:
            flat_data["Field"].append(k)
            flat_data["Value"].append(", ".join(v) if v else "None")

        df = pd.DataFrame(flat_data)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Pitch Deck Analysis')
        return output.getvalue()

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """
        Replaces incompatible characters with ASCII equivalents/replacements
        for FPDF's latin-1 limitation.
        """
        replacements = {
            '\u2018': "'", '\u2019': "'",  # Smart quotes
            '\u201c': '"', '\u201d': '"',  # Smart double quotes
            '\u2013': '-', '\u2014': '-',  # Dashes
            '\u2026': '...',               # Ellipsis
            '\u2022': '*',                 # Bullet point
            '\u2011': '-',                 # Non-breaking hyphen
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
            
        # Fallback: normalize unicode characters to closest ASCII or remove
        return text.encode('latin-1', 'replace').decode('latin-1')

    @staticmethod
    def to_pdf_memo(memo: InvestmentMemo, startup_name: str) -> bytes:
        """
        Creates a PDF Investment Memo.
        """
        pdf = FPDF()
        pdf.add_page()
        
        # Title
        # Sanitize name
        safe_name = Exporter._sanitize_text(startup_name)
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, f"Investment Memo: {safe_name}", ln=True, align='C')
        pdf.ln(10)
        
        # Sections
        sections = [
            ("Company Overview", memo.company_overview),
            ("Problem & Solution Clarity", memo.problem_solution_clarity),
            ("Market Opportunity", memo.market_opportunity),
            ("Product Differentiation", memo.product_differentiation),
            ("Traction & Metrics", memo.traction_metrics_analysis),
            ("Team Assessment", memo.team_assessment),
            ("Risks & Concerns", memo.risks_concerns),
            ("Open Questions", memo.open_questions),
            ("Neutral Assessment", memo.neutral_assessment)
        ]
        
        for title, content in sections:
            pdf.set_font("Arial", 'B', 12)
            safe_title = Exporter._sanitize_text(title)
            pdf.cell(0, 10, safe_title, ln=True)
            
            pdf.set_font("Arial", '', 11)
            # Handle List vs String
            if isinstance(content, list):
                # Convert list to bullet points
                formatted_content = "\n".join([f"- {item}" for item in content])
            else:
                formatted_content = content
                
            # Sanitize content
            safe_content = Exporter._sanitize_text(formatted_content)
            pdf.multi_cell(0, 6, safe_content)
            pdf.ln(5)
            
        return pdf.output(dest='S').encode('latin-1')

    @staticmethod
    def to_text_memo(memo: InvestmentMemo, startup_name: str) -> str:
        """
        Creates a plain text Investment Memo.
        """
        lines = [f"Investment Memo: {startup_name}", "="*40, ""]
        
        sections = [
            ("Company Overview", memo.company_overview),
            ("Problem & Solution Clarity", memo.problem_solution_clarity),
            ("Market Opportunity", memo.market_opportunity),
            ("Product Differentiation", memo.product_differentiation),
            ("Traction & Metrics", memo.traction_metrics_analysis),
            ("Team Assessment", memo.team_assessment),
            ("Risks & Concerns", memo.risks_concerns),
            ("Open Questions", memo.open_questions),
            ("Neutral Assessment", memo.neutral_assessment)
        ]
        
        for title, content in sections:
            lines.append(f"## {title}")
            
            if isinstance(content, list):
                for item in content:
                    lines.append(f"- {item}")
            else:
                lines.append(content)
                
            lines.append("")
            
        return "\n".join(lines)
