# Rishi Jobs – Contract Generator

Fills the Rishi Jobs *Placement Services Agreement* template with client details and
produces a ready-to-sign PDF. The template's design (logo, header, borders, fonts,
table and wording) is kept exactly as is; only the placeholders are replaced.

## Structure
| File | Purpose |
|---|---|
| `app.py` | Streamlit form (front end) |
| `api.py` | Flask API that returns the filled PDF |
| `contract_generator.py` | PDF engine (PyMuPDF) |
| `templates/contract_template.pdf` | Original contract template |

## Run
```
pip install -r requirements.txt
run.bat
```
or manually, in two terminals:
```
python api.py                 # http://127.0.0.1:5000
python -m streamlit run app.py   # http://localhost:8501
```
Set `CONTRACT_API_URL` if the API runs somewhere else.

## API
`POST /api/contracts/generate` with JSON:
```json
{
  "contract_date": "2026-09-19",
  "city": "Surat",
  "company_name": "ABC Technologies Private Limited",
  "gst_number": "24ABCDE1234F1Z5",
  "registered_address": "…",
  "signatory_name": "Mr. Amit Patel",
  "signatory_designation": "Director",
  "payment_days": 15,
  "replacement_days": 90,
  "fee_type": "tiered_10"
}
```
`fee_type`: `tiered_10`, `tiered_11`, `tiered_12`, `flat`. Returns the PDF, or `422` with a list of validation errors.

## What gets filled
- **[CITY] / [DATE]**: place and date of agreement (the date also goes in both signature blocks)
- **Client name, GSTIN, registered address**: opening clause, signature block and the Client's Information Sheet
- **[PAYMENT DAYS]**: clause 3, e.g. "Fifteen (15) days"
- **Replacement days**: clause 4, "Ninety (90) Days" becomes "Sixty (60) Days" when 60 is chosen
- **Fee table**: service description and the chosen fee structure
- **Signatory name and designation**: client signature block
