import argparse
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import Date, cast, select

from database import SessionLocal
from models import PaymentTransaction


LOGGER = logging.getLogger("tally_export")

# Replace values here if the ledger names differ in the target Tally company.
FEE_HEAD_LEDGER_NAMES = {
    "Tuition": "Tuition Fees Account",
    "Accessories": "Accessories Fees Account",
    "Examination": "Exam Fees Account",
    "Exam": "Exam Fees Account",
    "Hostel": "Hostel Fees Account",
    "Mess": "Mess Fees Account",
    "Bus": "Bus Fees Account",
    "Other fees": "Other Fees Account",
    "Other Fees": "Other Fees Account",
    "Other": "Other Fees Account",
}

# Keep these aligned with the corresponding bank/cash ledgers in Tally.
PAYMENT_MODE_LEDGER_NAMES = {
    "Cash": "Cash",
    "UPI": "Bank",
    "Bank": "Bank",
    "Bank Transfer": "Bank",
    "Govt Transfer": "Bank",
}


def get_daily_transactions(transaction_date: date) -> list[PaymentTransaction]:
    """Return recorded (committed) transactions whose local SQL date matches."""
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(PaymentTransaction)
                .where(cast(PaymentTransaction.date_time, Date) == transaction_date)
                .order_by(PaymentTransaction.date_time, PaymentTransaction.id)
            ).all()
        )


def _receipt_voucher(transaction: PaymentTransaction) -> ET.Element:
    amount = Decimal(transaction.amount_paid)
    if amount <= 0:
        raise ValueError(
            f"Transaction {transaction.id} has a non-positive amount: {amount}"
        )

    try:
        receipt_ledger = PAYMENT_MODE_LEDGER_NAMES[transaction.payment_mode]
    except KeyError as error:
        raise ValueError(
            f"Transaction {transaction.id} has an unsupported payment mode: "
            f"{transaction.payment_mode!r}"
        ) from error

    try:
        fee_ledger = FEE_HEAD_LEDGER_NAMES[transaction.fee_head]
    except KeyError as error:
        raise ValueError(
            f"Transaction {transaction.id} has an unmapped fee head: "
            f"{transaction.fee_head!r}"
        ) from error

    voucher = ET.Element(
        "VOUCHER",
        {
            "VCHTYPE": "Receipt",
            "ACTION": "Create",
            "OBJVIEW": "Accounting Voucher View",
        },
    )
    ET.SubElement(voucher, "DATE").text = transaction.date_time.strftime("%Y%m%d")
    ET.SubElement(voucher, "VOUCHERTYPENAME").text = "Receipt"
    ET.SubElement(voucher, "VOUCHERNUMBER").text = str(transaction.id)
    ET.SubElement(voucher, "NARRATION").text = (
        f"Receipt No: {transaction.id}, D.No: {transaction.d_no}"
    )

    ledger_entries = (
        (receipt_ledger, "Yes", amount),
        (fee_ledger, "No", -amount),
    )
    for ledger_name, is_deemed_positive, ledger_amount in ledger_entries:
        entry = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(entry, "LEDGERNAME").text = ledger_name
        ET.SubElement(entry, "ISDEEMEDPOSITIVE").text = is_deemed_positive
        ET.SubElement(entry, "AMOUNT").text = f"{ledger_amount:.2f}"

    return voucher


def build_tally_xml(
    transactions: list[PaymentTransaction],
    company_name: str | None = None,
) -> str:
    envelope = ET.Element("ENVELOPE")
    header = ET.SubElement(envelope, "HEADER")
    ET.SubElement(header, "TALLYREQUEST").text = "Import Data"

    body = ET.SubElement(envelope, "BODY")
    import_data = ET.SubElement(body, "IMPORTDATA")
    request_description = ET.SubElement(import_data, "REQUESTDESC")
    ET.SubElement(request_description, "REPORTNAME").text = "Vouchers"
    if company_name:
        static_variables = ET.SubElement(request_description, "STATICVARIABLES")
        ET.SubElement(static_variables, "SVCURRENTCOMPANY").text = company_name

    request_data = ET.SubElement(import_data, "REQUESTDATA")
    for transaction in transactions:
        tally_message = ET.SubElement(
            request_data,
            "TALLYMESSAGE",
            {"xmlns:UDF": "TallyUDF"},
        )
        tally_message.append(_receipt_voucher(transaction))

    ET.indent(envelope, space="  ")
    return ET.tostring(envelope, encoding="unicode", xml_declaration=True)


def export_daily_transactions(
    transaction_date: date,
    output_path: Path | None = None,
    company_name: str | None = None,
) -> Path:
    transactions = get_daily_transactions(transaction_date)
    xml_content = build_tally_xml(transactions, company_name)
    destination = output_path or Path(
        f"tally_receipts_{transaction_date:%Y%m%d}.xml"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(xml_content, encoding="utf-8")
    LOGGER.info(
        "Exported %s transactions for %s to %s.",
        len(transactions),
        transaction_date,
        destination,
    )
    return destination


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Export daily fee transactions to a Tally-compatible XML file."
    )
    parser.add_argument(
        "--date",
        required=True,
        type=date.fromisoformat,
        help="Transaction date to export (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output XML path (default: tally_receipts_YYYYMMDD.xml).",
    )
    parser.add_argument(
        "--company",
        help="Optional exact company name as configured in Tally.",
    )
    args = parser.parse_args()

    try:
        export_daily_transactions(args.date, args.output, args.company)
    except Exception:
        LOGGER.exception("Tally export failed.")
        raise


if __name__ == "__main__":
    main()
