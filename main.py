from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine
from models import FeeDemand, Scholarship, Student, Transaction
from reports import router as reports_router
from transactions import (
    apply_fee_payment,
    migrate_accounting_schema,
    router as transactions_router,
)


class PaymentItem(BaseModel):
    fee_head: str = Field(min_length=1, max_length=50)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class PaymentRequest(BaseModel):
    d_no: str = Field(min_length=1, max_length=32)
    counter_id: Literal["1", "2", "Bank"]
    payments: list[PaymentItem] = Field(min_length=1)
    payment_mode: Literal["Cash", "UPI", "Bank"]


class ScholarshipReceiptRequest(BaseModel):
    d_no: str = Field(min_length=1, max_length=32)
    scholarship_id: int = Field(gt=0)
    fee_head: str = Field(min_length=1, max_length=50)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    d_no: str
    name: str
    department: str
    semester: int
    status: str


def _fee_balances(
    session: Session,
    d_no: str,
    semester: int | None = None,
) -> dict[str, dict[str, Decimal]]:
    statement = select(FeeDemand).where(FeeDemand.d_no == d_no)
    if semester is not None:
        statement = statement.where(FeeDemand.semester == semester)
    demands = session.scalars(statement).all()
    balances: dict[str, dict[str, Decimal]] = {}
    for demand in demands:
        balance = balances.setdefault(
            demand.fee_head,
            {
                "assessed_amount": Decimal("0.00"),
                "paid_amount": Decimal("0.00"),
                "outstanding_balance": Decimal("0.00"),
            },
        )
        balance["assessed_amount"] += demand.assessed_amount
        balance["paid_amount"] += demand.amount_paid
        balance["outstanding_balance"] += demand.outstanding_balance
    return balances


def _transaction_response(transaction: Transaction) -> dict[str, object]:
    return {
        "id": transaction.id,
        "receipt_no": transaction.receipt_no,
        "d_no": transaction.d_no,
        "counter_id": transaction.counter_id,
        "fee_head": transaction.fee_head,
        "amount_paid": transaction.amount_paid,
        "payment_mode": transaction.payment_mode,
        "date_time": transaction.date_time,
    }


def _student_for_update(session: Session, d_no: str) -> Student:
    student = session.scalar(
        select(Student).where(Student.d_no == d_no).with_for_update()
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def _record_transaction(
    session: Session,
    *,
    d_no: str,
    counter_id: str,
    fee_head: str,
    amount: Decimal,
    payment_mode: str,
) -> Transaction:
    transaction = Transaction(
        d_no=d_no,
        counter_id=counter_id,
        fee_head=fee_head,
        amount_paid=amount,
        payment_mode=payment_mode,
    )
    session.add(transaction)
    session.flush()
    session.refresh(transaction)
    return transaction


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_accounting_schema(engine)
    yield


app = FastAPI(title="PITS Fees Monitor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(transactions_router)
app.include_router(reports_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/reports/daily")
def get_daily_report() -> dict[str, object]:
    today = func.current_date()
    with SessionLocal() as session:
        report_date = session.scalar(select(today))
        payment_mode_rows = session.execute(
            select(Transaction.payment_mode, func.sum(Transaction.amount_paid))
            .where(cast(Transaction.date_time, Date) == today)
            .group_by(Transaction.payment_mode)
            .order_by(Transaction.payment_mode)
        ).all()
        fee_head_rows = session.execute(
            select(Transaction.fee_head, func.sum(Transaction.amount_paid))
            .where(cast(Transaction.date_time, Date) == today)
            .group_by(Transaction.fee_head)
            .order_by(Transaction.fee_head)
        ).all()
        counter_rows = session.execute(
            select(Transaction.counter_id, func.sum(Transaction.amount_paid))
            .where(cast(Transaction.date_time, Date) == today)
            .group_by(Transaction.counter_id)
            .order_by(Transaction.counter_id)
        ).all()

    return {
        "report_date": report_date,
        "by_payment_mode": [
            {"payment_mode": payment_mode, "total": total}
            for payment_mode, total in payment_mode_rows
        ],
        "by_fee_head": [
            {"fee_head": fee_head, "total": total}
            for fee_head, total in fee_head_rows
        ],
        "by_counter": [
            {"counter_id": counter_id, "total": total}
            for counter_id, total in counter_rows
        ],
    }


@app.get("/api/student/{d_no}")
def get_student(d_no: str) -> dict[str, object]:
    with SessionLocal() as session:
        student = session.get(Student, d_no)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")

        payment_history = session.scalars(
            select(Transaction)
            .where(Transaction.d_no == d_no)
            .order_by(Transaction.date_time.desc(), Transaction.id.desc())
        ).all()
        return {
            "student": StudentResponse.model_validate(student),
            "assessed_fees": [
                {"fee_head": fee_head, **amounts}
                for fee_head, amounts in sorted(
                    _fee_balances(session, d_no, semester=student.semester).items()
                )
            ],
            "payment_history": [
                _transaction_response(transaction) for transaction in payment_history
            ],
        }


@app.post("/api/pay")
def pay_fees(payload: PaymentRequest) -> dict[str, object]:
    with SessionLocal.begin() as session:
        _student_for_update(session, payload.d_no)
        balances = _fee_balances(session, payload.d_no)
        requested_by_head: dict[str, Decimal] = {}
        for payment in payload.payments:
            fee_head = payment.fee_head.strip()
            if not fee_head:
                raise HTTPException(status_code=422, detail="fee_head cannot be blank")
            requested_by_head[fee_head] = (
                requested_by_head.get(fee_head, Decimal("0.00")) + payment.amount
            )

        for fee_head, amount in requested_by_head.items():
            balance = balances.get(fee_head)
            if balance is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"No assessed fee found for fee head '{fee_head}'",
                )
            if amount > balance["outstanding_balance"]:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Payment for '{fee_head}' exceeds outstanding balance "
                        f"({balance['outstanding_balance']})"
                    ),
                )

        for fee_head, amount in requested_by_head.items():
            apply_fee_payment(
                session,
                d_no=payload.d_no,
                fee_head=fee_head,
                amount=amount,
            )

        transactions = [
            _record_transaction(
                session,
                d_no=payload.d_no,
                counter_id=payload.counter_id,
                fee_head=payment.fee_head.strip(),
                amount=payment.amount,
                payment_mode=payload.payment_mode,
            )
            for payment in payload.payments
        ]

    return {
        "message": "Payment recorded",
        "transactions": [_transaction_response(transaction) for transaction in transactions],
    }


@app.post("/api/scholarship/receive")
def receive_scholarship(payload: ScholarshipReceiptRequest) -> dict[str, object]:
    with SessionLocal.begin() as session:
        _student_for_update(session, payload.d_no)
        scholarship = session.scalar(
            select(Scholarship)
            .where(
                Scholarship.id == payload.scholarship_id,
                Scholarship.d_no == payload.d_no,
            )
            .with_for_update()
        )
        if scholarship is None:
            raise HTTPException(status_code=404, detail="Scholarship not found for student")
        if payload.amount > scholarship.pending_amount:
            raise HTTPException(
                status_code=400,
                detail="Received amount cannot exceed the scholarship pending amount",
            )

        fee_head = payload.fee_head.strip()
        if not fee_head:
            raise HTTPException(status_code=422, detail="fee_head cannot be blank")
        balances = _fee_balances(session, payload.d_no)
        balance = balances.get(fee_head)
        if balance is None:
            raise HTTPException(
                status_code=400,
                detail=f"No assessed fee found for fee head '{fee_head}'",
            )
        if payload.amount > balance["outstanding_balance"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Scholarship payment for '{fee_head}' exceeds outstanding balance "
                    f"({balance['outstanding_balance']})"
                ),
            )

        apply_fee_payment(
            session,
            d_no=payload.d_no,
            fee_head=fee_head,
            amount=payload.amount,
        )
        scholarship.received_amount += payload.amount
        scholarship.pending_amount -= payload.amount
        transaction = _record_transaction(
            session,
            d_no=payload.d_no,
            counter_id="Bank",
            fee_head=fee_head,
            amount=payload.amount,
            payment_mode="Govt Transfer",
        )
        session.flush()
        scholarship_result = {
            "id": scholarship.id,
            "received_amount": scholarship.received_amount,
            "pending_amount": scholarship.pending_amount,
        }

    return {
        "message": "Scholarship receipt recorded and applied to fees",
        "scholarship": scholarship_result,
        "transaction": _transaction_response(transaction),
    }
