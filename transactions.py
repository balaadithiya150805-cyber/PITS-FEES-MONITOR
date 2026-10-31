from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from database import SessionLocal
from models import FeeDemand, PaymentTransaction, ScholarshipClaim, Student


router = APIRouter()

PaymentMode = Literal["Cash", "UPI", "Bank", "Bank Transfer"]
CounterNumber = Literal["1", "2", "Bank"]


class CollectionPaymentRequest(BaseModel):
    d_no: str = Field(min_length=1, max_length=32)
    fee_head: str = Field(min_length=1, max_length=50)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_mode: PaymentMode
    counter_number: CounterNumber | None = None


class ScholarshipDisbursementRequest(BaseModel):
    claim_id: int = Field(gt=0)
    fee_head: str = Field(min_length=1, max_length=50)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


def migrate_accounting_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    demand_columns = {column["name"] for column in inspector.get_columns("fee_demands")}
    transaction_column_info = {
        column["name"]: column for column in inspector.get_columns("transactions")
    }
    transaction_constraints = {
        constraint["name"]: constraint.get("sqltext", "")
        for constraint in inspector.get_check_constraints("transactions")
    }

    with engine.begin() as connection:
        if "amount_paid" not in demand_columns:
            connection.execute(
                text(
                    "ALTER TABLE fee_demands ADD COLUMN amount_paid "
                    "NUMERIC(12, 2) NOT NULL DEFAULT 0"
                )
            )
            connection.execute(
                text(
                    """
                    WITH historical_payments AS (
                        SELECT d_no, fee_head, SUM(amount_paid) AS total_paid
                        FROM transactions
                        GROUP BY d_no, fee_head
                    ),
                    ordered_demands AS (
                        SELECT
                            demand.id,
                            demand.assessed_amount,
                            COALESCE(payment.total_paid, 0) AS total_paid,
                            COALESCE(
                                SUM(demand.assessed_amount) OVER (
                                    PARTITION BY demand.d_no, demand.fee_head
                                    ORDER BY demand.semester, demand.id
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                ),
                                0
                            ) AS assessed_before
                        FROM fee_demands AS demand
                        LEFT JOIN historical_payments AS payment
                            ON payment.d_no = demand.d_no
                            AND payment.fee_head = demand.fee_head
                    )
                    UPDATE fee_demands AS demand
                    SET amount_paid = LEAST(
                        ordered.assessed_amount,
                        GREATEST(ordered.total_paid - ordered.assessed_before, 0)
                    )
                    FROM ordered_demands AS ordered
                    WHERE demand.id = ordered.id
                    """
                )
            )

        if "outstanding_balance" not in demand_columns:
            connection.execute(
                text(
                    "ALTER TABLE fee_demands ADD COLUMN outstanding_balance "
                    "NUMERIC(12, 2) GENERATED ALWAYS AS "
                    "(assessed_amount - amount_paid) STORED"
                )
            )

        payment_mode_column = transaction_column_info.get("payment_mode")
        if payment_mode_column is not None and (
            (payment_mode_column["type"].length or 0) < 20
            or "Govt Transfer" not in transaction_constraints.get(
                "ck_transactions_payment_mode", ""
            )
        ):
            connection.execute(
                text("ALTER TABLE transactions ALTER COLUMN payment_mode TYPE VARCHAR(20)")
            )
            connection.execute(
                text(
                    "ALTER TABLE transactions DROP CONSTRAINT IF EXISTS "
                    "ck_transactions_payment_mode"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE transactions ADD CONSTRAINT "
                    "ck_transactions_payment_mode CHECK "
                    "(payment_mode IN ('Cash', 'UPI', 'Bank', 'Bank Transfer', "
                    "'Govt Transfer'))"
                )
            )

    constraint_names = {
        constraint["name"]
        for constraint in inspect(engine).get_check_constraints("fee_demands")
    }
    with engine.begin() as connection:
        if "ck_fee_demands_amount_paid_nonnegative" not in constraint_names:
            connection.execute(
                text(
                    "ALTER TABLE fee_demands ADD CONSTRAINT "
                    "ck_fee_demands_amount_paid_nonnegative CHECK (amount_paid >= 0)"
                )
            )
        if "ck_fee_demands_amount_paid_not_over_assessed" not in constraint_names:
            connection.execute(
                text(
                    "ALTER TABLE fee_demands ADD CONSTRAINT "
                    "ck_fee_demands_amount_paid_not_over_assessed "
                    "CHECK (amount_paid <= assessed_amount)"
                )
            )


def _lock_student(session: Session, d_no: str) -> Student:
    student = session.scalar(
        select(Student).where(Student.d_no == d_no).with_for_update()
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def apply_fee_payment(
    session: Session,
    *,
    d_no: str,
    fee_head: str,
    amount: Decimal,
    semester: int | None = None,
) -> Decimal:
    statement = select(FeeDemand).where(
        FeeDemand.d_no == d_no,
        FeeDemand.fee_head == fee_head,
    )
    if semester is not None:
        statement = statement.where(FeeDemand.semester == semester)

    demands = session.scalars(
        statement.order_by(FeeDemand.semester, FeeDemand.id).with_for_update()
    ).all()
    if not demands:
        raise HTTPException(
            status_code=400,
            detail=f"No assessed fee found for fee head '{fee_head}'",
        )

    outstanding = sum(
        (demand.outstanding_balance for demand in demands), Decimal("0.00")
    )
    if amount > outstanding:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Payment for '{fee_head}' exceeds outstanding balance "
                f"({outstanding})"
            ),
        )

    remaining = amount
    for demand in demands:
        applied = min(remaining, demand.outstanding_balance)
        demand.amount_paid += applied
        remaining -= applied
        if remaining == 0:
            break
    return outstanding - amount


def _record_transaction(
    session: Session,
    *,
    d_no: str,
    fee_head: str,
    amount: Decimal,
    payment_mode: str,
    counter_number: str,
) -> PaymentTransaction:
    transaction = PaymentTransaction(
        d_no=d_no,
        fee_head=fee_head,
        amount_paid=amount,
        payment_mode=payment_mode,
        counter_id=counter_number,
    )
    session.add(transaction)
    session.flush()
    session.refresh(transaction)
    return transaction


def _transaction_response(transaction: PaymentTransaction) -> dict[str, object]:
    return {
        "transaction_id": transaction.id,
        "receipt_no": transaction.receipt_no,
        "d_no": transaction.d_no,
        "counter_number": transaction.counter_id,
        "fee_head": transaction.fee_head,
        "amount": transaction.amount_paid,
        "payment_mode": transaction.payment_mode,
        "date_time": transaction.date_time,
    }


@router.post("/api/collections/pay")
def pay_collection(payload: CollectionPaymentRequest) -> dict[str, object]:
    d_no = payload.d_no.strip()
    fee_head = payload.fee_head.strip()
    if not d_no or not fee_head:
        raise HTTPException(status_code=422, detail="d_no and fee_head cannot be blank")

    with SessionLocal.begin() as session:
        student = _lock_student(session, d_no)
        outstanding_balance = apply_fee_payment(
            session,
            d_no=d_no,
            fee_head=fee_head,
            amount=payload.amount,
            semester=student.semester,
        )
        counter_number = payload.counter_number or (
            "Bank" if payload.payment_mode in ("Bank", "Bank Transfer") else "1"
        )
        transaction = _record_transaction(
            session,
            d_no=d_no,
            fee_head=fee_head,
            amount=payload.amount,
            payment_mode=payload.payment_mode,
            counter_number=counter_number,
        )

    return {
        "message": "Payment recorded",
        "transaction": _transaction_response(transaction),
        "outstanding_balance": outstanding_balance,
    }


@router.post("/api/scholarships/disburse")
def disburse_scholarship(
    payload: ScholarshipDisbursementRequest,
) -> dict[str, object]:
    fee_head = payload.fee_head.strip()
    if not fee_head:
        raise HTTPException(status_code=422, detail="fee_head cannot be blank")

    with SessionLocal.begin() as session:
        claim = session.scalar(
            select(ScholarshipClaim)
            .where(ScholarshipClaim.id == payload.claim_id)
            .with_for_update()
        )
        if claim is None:
            raise HTTPException(status_code=404, detail="Scholarship claim not found")
        if claim.status != "Pending":
            raise HTTPException(
                status_code=409, detail="Scholarship claim has already been received"
            )
        if payload.amount != claim.expected_amount:
            raise HTTPException(
                status_code=400,
                detail="Disbursed amount must equal the claim's expected amount",
            )

        student = _lock_student(session, claim.d_no)
        outstanding_balance = apply_fee_payment(
            session,
            d_no=claim.d_no,
            fee_head=fee_head,
            amount=payload.amount,
            semester=student.semester,
        )
        transaction = _record_transaction(
            session,
            d_no=claim.d_no,
            fee_head=fee_head,
            amount=payload.amount,
            payment_mode="Govt Transfer",
            counter_number="Bank",
        )
        claim.status = "Received"

    return {
        "message": "Scholarship disbursement recorded and applied to fees",
        "claim_id": claim.id,
        "status": claim.status,
        "transaction": _transaction_response(transaction),
        "outstanding_balance": outstanding_balance,
    }
