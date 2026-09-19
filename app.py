"""
Rishi Jobs - Placement Services Agreement generator (Streamlit front end)

Collects the contract details, sends them to the Flask API and offers the
filled PDF for download.

Run:  streamlit run app.py      (the Flask API must be running: python api.py)
"""

import os
from datetime import date

import pymupdf as fitz
import requests
import streamlit as st

API_URL = os.environ.get("CONTRACT_API_URL", "http://127.0.0.1:5000")
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "logo.png")

PAYMENT_DAYS = [7, 10, 15, 30]
REPLACEMENT_DAYS = [60, 90]
FEE_TYPES = {
    "tiered_10": "Tiered:  8.33% up to ₹ 12,00,000 CTC   |10% above ₹ 12,00,000 CTC",
    "tiered_11": "Tiered:  8.33% up to ₹ 12,00,000 CTC   |11% above ₹ 12,00,000 CTC",
    "tiered_12": "Tiered:  8.33% up to ₹ 12,00,000 CTC   |12% above ₹ 12,00,000 CTC",
    "flat": "Flat:  8.33% of Annual CTC",
}

st.set_page_config(page_title="Rishi Jobs | Contract Generator", page_icon="📄", layout="centered")

st.markdown(
    """
    <style>
      .rj-header {background:#16213E;color:#fff;padding:18px 22px;border-radius:12px;
                  border-left:8px solid #DDA878;margin-bottom:18px}
      .rj-header h1 {font-size:1.55rem;margin:0;color:#fff}
      .rj-header p {margin:4px 0 0;color:#e6d3bf;font-size:.95rem}
      div.stButton > button, div.stDownloadButton > button, div.stFormSubmitButton > button
        {background:#16213E;color:#fff;border:0}
      div.stButton > button:hover, div.stDownloadButton > button:hover,
      div.stFormSubmitButton > button:hover {background:#DDA878;color:#16213E}
    </style>
    """,
    unsafe_allow_html=True,
)

header_cols = st.columns([1, 5]) if os.path.exists(LOGO_PATH) else None
if header_cols:
    header_cols[0].image(LOGO_PATH, width=80)
    target = header_cols[1]
else:
    target = st
target.markdown(
    '<div class="rj-header"><h1>Placement Services Agreement</h1>'
    "<p>Fill in the client details to generate a ready-to-sign contract PDF.</p></div>",
    unsafe_allow_html=True,
)


def api_available() -> bool:
    try:
        return requests.get(f"{API_URL}/api/health", timeout=3).ok
    except requests.RequestException:
        return False


@st.cache_resource
def start_embedded_api():
    """Run the Flask API inside this process (single-process hosts like Streamlit Cloud)."""
    import threading

    from werkzeug.serving import make_server

    from api import app as flask_app

    server = make_server("127.0.0.1", 5000, flask_app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if "CONTRACT_API_URL" not in os.environ and not api_available():
    try:
        start_embedded_api()
    except OSError:
        pass

if not api_available():
    st.error(
        f"The contract API is not reachable at **{API_URL}**. "
        "Start it with `python api.py` (or use `run.bat`) and reload this page."
    )

with st.form("contract_form"):
    st.subheader("Agreement")
    c1, c2 = st.columns(2)
    contract_date = c1.date_input("Contract date *", value=date.today(), format="DD/MM/YYYY")
    city = c2.text_input("Place of agreement (city) *", value="Surat", max_chars=40)

    st.subheader("Client company")
    company_name = st.text_input("Company name *", max_chars=120,
                                 placeholder="e.g. ABC Technologies Private Limited")
    gst_number = st.text_input("GST number *", max_chars=15, placeholder="e.g. 24ABCDE1234F1Z5")
    registered_address = st.text_area("Registered address *", max_chars=300, height=90)

    st.subheader("Authorised signatory")
    s1, s2 = st.columns(2)
    signatory_name = s1.text_input("Signatory name *", max_chars=60, placeholder="e.g. Mr. Amit Patel")
    signatory_designation = s2.text_input("Designation *", max_chars=60, placeholder="e.g. Director")

    st.subheader("Commercial terms")
    t1, t2 = st.columns(2)
    payment_days = t1.selectbox("Payment days *", PAYMENT_DAYS, index=2,
                                format_func=lambda d: f"{d} days")
    replacement_days = t2.selectbox("Replacement days *", REPLACEMENT_DAYS, index=1,
                                    format_func=lambda d: f"{d} days")
    fee_type = st.radio("Fee type *", list(FEE_TYPES), format_func=FEE_TYPES.get)

    with st.expander("More options"):
        service_description = st.text_input("Service description (fee table)",
                                            value="Permanent Recruitment Services", max_chars=60)
        fill_information_sheet = st.checkbox(
            "Pre-fill company name, address and GST number in the Client's Information Sheet",
            value=True,
        )

    submitted = st.form_submit_button("Generate contract", type="primary", width="stretch")

if submitted:
    payload = {
        "contract_date": contract_date.isoformat(),
        "city": city,
        "company_name": company_name,
        "gst_number": gst_number,
        "registered_address": registered_address,
        "signatory_name": signatory_name,
        "signatory_designation": signatory_designation,
        "payment_days": payment_days,
        "replacement_days": replacement_days,
        "fee_type": fee_type,
        "service_description": service_description,
        "fill_information_sheet": fill_information_sheet,
    }
    try:
        with st.spinner("Generating contract..."):
            resp = requests.post(f"{API_URL}/api/contracts/generate", json=payload, timeout=60)
    except requests.RequestException as exc:
        st.error(f"Could not reach the contract API: {exc}")
    else:
        if resp.ok:
            disposition = resp.headers.get("Content-Disposition", "")
            filename = disposition.split("filename=")[-1].strip('"') if "filename=" in disposition \
                else "Placement_Services_Agreement.pdf"
            st.session_state["contract_pdf"] = resp.content
            st.session_state["contract_name"] = filename
        else:
            st.session_state.pop("contract_pdf", None)
            try:
                errors = resp.json().get("errors", [resp.text])
            except ValueError:
                errors = [resp.text]
            st.error("Please fix the following:\n\n" + "\n".join(f"- {e}" for e in errors))

if "contract_pdf" in st.session_state:
    pdf_bytes = st.session_state["contract_pdf"]
    st.success("Contract generated successfully.")
    st.download_button(
        "⬇️ Download contract PDF",
        data=pdf_bytes,
        file_name=st.session_state["contract_name"],
        mime="application/pdf",
        width="stretch",
    )
    with st.expander("Preview", expanded=True):
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        tabs = st.tabs([f"Page {i + 1}" for i in range(doc.page_count)])
        for tab, page in zip(tabs, doc):
            tab.image(page.get_pixmap(dpi=110).tobytes("png"), width="stretch")
        doc.close()
