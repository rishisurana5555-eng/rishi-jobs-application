"""
Rishi Jobs - Contract API (Flask)

Endpoints
    GET  /api/health              -> service status
    GET  /api/options             -> dropdown options for the contract form
    POST /api/contracts/generate  -> JSON contract details in, filled PDF out

Run:  python api.py   (serves on http://127.0.0.1:5000)
"""

import io
import os

from flask import Flask, jsonify, request, send_file

from contract_generator import (
    DEFAULT_SERVICE_DESCRIPTION,
    FEE_TYPES,
    PAYMENT_DAYS,
    REPLACEMENT_DAYS,
    TEMPLATE_PATH,
    ContractDetails,
    contract_filename,
    generate_contract,
)

app = Flask(__name__)


@app.get("/api/health")
def health():
    return jsonify(status="ok", template_found=os.path.exists(TEMPLATE_PATH))


@app.get("/api/options")
def options():
    return jsonify(
        payment_days=[{"value": d, "label": f"{d} days"} for d in PAYMENT_DAYS],
        replacement_days=[{"value": d, "label": f"{d} days"} for d in REPLACEMENT_DAYS],
        fee_types=[{"value": k, "label": v} for k, v in FEE_TYPES.items()],
        default_service_description=DEFAULT_SERVICE_DESCRIPTION,
    )


@app.post("/api/contracts/generate")
def generate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(errors=["Request body must be a JSON object."]), 400
    try:
        details = ContractDetails.from_dict(payload)
    except ValueError as exc:
        return jsonify(errors=exc.args[0]), 422

    try:
        pdf_bytes = generate_contract(details)
    except Exception as exc:  # surface template/rendering problems to the client
        app.logger.exception("Contract generation failed")
        return jsonify(errors=[f"Could not generate the contract: {exc}"]), 500

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=contract_filename(details),
    )


if __name__ == "__main__":
    app.run(
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "5000")),
        debug=False,
    )
