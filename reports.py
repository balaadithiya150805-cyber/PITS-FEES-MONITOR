from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from database import SessionLocal
from models import FeeDemand, PaymentTransaction, Scholarship, ScholarshipClaim, Student


router = APIRouter(prefix="/api/reports", tags=["reports"])

DAILY_FEE_HEADS = (
    "Tuition",
    "Examination",
    "Accessories",
    "Hostel",
    "Mess",
    "Bus",
    "Other fees",
)


def _decimal(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0.00")


def _transaction_date_filter(report_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(report_date, time.min)
    return start, start + timedelta(days=1)


@router.get("/daily-collections")
def get_daily_collections(report_date: date) -> dict[str, Any]:
    start, end = _transaction_date_filter(report_date)
    date_filter = (
        (PaymentTransaction.date_time >= start)
        & (PaymentTransaction.date_time < end)
    )
    with SessionLocal() as session:
        total = session.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount_paid), 0)).where(
                date_filter
            )
        )
        payment_rows = session.execute(
            select(
                PaymentTransaction.payment_mode,
                func.sum(PaymentTransaction.amount_paid),
            )
            .where(date_filter)
            .group_by(PaymentTransaction.payment_mode)
        ).all()
        fee_rows = session.execute(
            select(
                PaymentTransaction.fee_head,
                func.sum(PaymentTransaction.amount_paid),
            )
            .where(date_filter)
            .group_by(PaymentTransaction.fee_head)
        ).all()
        counter_rows = session.execute(
            select(
                PaymentTransaction.counter_id,
                func.sum(PaymentTransaction.amount_paid),
            )
            .where(date_filter)
            .group_by(PaymentTransaction.counter_id)
        ).all()

    payment_totals: dict[str, Decimal] = {
        "Cash": Decimal("0.00"),
        "UPI": Decimal("0.00"),
        "Direct Bank Transfer": Decimal("0.00"),
        "Government Scholarship Transfer": Decimal("0.00"),
    }
    for payment_mode, amount in payment_rows:
        if payment_mode in ("Bank", "Bank Transfer"):
            report_mode = "Direct Bank Transfer"
        elif payment_mode == "Govt Transfer":
            report_mode = "Government Scholarship Transfer"
        else:
            report_mode = payment_mode
        payment_totals[report_mode] = payment_totals.get(
            report_mode, Decimal("0.00")
        ) + _decimal(amount)

    fee_totals: dict[str, Decimal] = {head: Decimal("0.00") for head in DAILY_FEE_HEADS}
    for fee_head, amount in fee_rows:
        report_head = "Examination" if fee_head == "Exam" else fee_head
        fee_totals[report_head] = fee_totals.get(
            report_head, Decimal("0.00")
        ) + _decimal(amount)

    counter_totals = {"1": Decimal("0.00"), "2": Decimal("0.00"), "Bank": Decimal("0.00")}
    for counter_id, amount in counter_rows:
        counter_totals[counter_id] = counter_totals.get(
            counter_id, Decimal("0.00")
        ) + _decimal(amount)

    return {
        "report_date": report_date,
        "total_collected": _decimal(total),
        "by_payment_mode": [
            {"payment_mode": payment_mode, "total": amount}
            for payment_mode, amount in payment_totals.items()
        ],
        "by_fee_head": [
            {"fee_head": fee_head, "total": amount}
            for fee_head, amount in fee_totals.items()
        ],
        "by_counter": [
            {"counter_id": counter_id, "total": amount}
            for counter_id, amount in counter_totals.items()
        ],
    }


@router.get("/outstanding-arrears")
def get_outstanding_arrears(
    semester: int | None = Query(default=None, gt=0),
) -> dict[str, Any]:
    demand_filter = FeeDemand.semester == semester if semester is not None else True
    with SessionLocal() as session:
        total_outstanding = session.scalar(
            select(func.coalesce(func.sum(FeeDemand.outstanding_balance), 0)).where(
                demand_filter
            )
        )

        fee_head_rows = session.execute(
            select(
                FeeDemand.fee_head,
                func.sum(FeeDemand.assessed_amount),
                func.sum(FeeDemand.amount_paid),
                func.sum(FeeDemand.outstanding_balance),
            )
            .where(demand_filter)
            .group_by(FeeDemand.fee_head)
            .order_by(FeeDemand.fee_head)
        ).all()
        department_rows = session.execute(
            select(
                Student.department,
                func.sum(FeeDemand.assessed_amount),
                func.sum(FeeDemand.amount_paid),
                func.sum(FeeDemand.outstanding_balance),
            )
            .join(Student, Student.d_no == FeeDemand.d_no)
            .where(demand_filter)
            .group_by(Student.department)
            .order_by(Student.department)
        ).all()
        course_rows = session.execute(
            select(
                Student.course,
                Student.department,
                func.sum(FeeDemand.assessed_amount),
                func.sum(FeeDemand.amount_paid),
                func.sum(FeeDemand.outstanding_balance),
            )
            .join(Student, Student.d_no == FeeDemand.d_no)
            .where(demand_filter)
            .group_by(Student.course, Student.department)
            .order_by(Student.department, Student.course)
        ).all()
        semester_rows = session.execute(
            select(
                FeeDemand.semester,
                func.sum(FeeDemand.assessed_amount),
                func.sum(FeeDemand.amount_paid),
                func.sum(FeeDemand.outstanding_balance),
            )
            .group_by(FeeDemand.semester)
            .order_by(FeeDemand.semester)
        ).all()
        student_rows = session.execute(
            select(
                Student.d_no,
                Student.name,
                Student.department,
                Student.course,
                func.sum(FeeDemand.assessed_amount).label("assessed"),
                func.sum(FeeDemand.amount_paid).label("paid"),
                func.sum(FeeDemand.outstanding_balance).label("outstanding"),
            )
            .join(FeeDemand, FeeDemand.d_no == Student.d_no)
            .where(demand_filter)
            .group_by(
                Student.d_no,
                Student.name,
                Student.department,
                Student.course,
            )
            .having(func.sum(FeeDemand.assessed_amount) > 0)
            .order_by(Student.department, Student.name)
        ).all()
        legacy_scholarship_rows = session.execute(
            select(
                Scholarship.d_no,
                Student.name,
                Student.department,
                Scholarship.category,
                Scholarship.pending_amount,
            )
            .join(Student, Student.d_no == Scholarship.d_no)
            .where(Scholarship.pending_amount > 0)
            .order_by(Student.department, Student.name)
        ).all()
        pending_claim_rows = session.execute(
            select(
                ScholarshipClaim.d_no,
                Student.name,
                Student.department,
                ScholarshipClaim.category,
                ScholarshipClaim.expected_amount,
            )
            .join(Student, Student.d_no == ScholarshipClaim.d_no)
            .where(ScholarshipClaim.status == "Pending")
            .order_by(Student.department, Student.name)
        ).all()

    students = [
        {
            "d_no": d_no,
            "name": name,
            "department": department,
            "course": course,
            "assessed_amount": _decimal(assessed),
            "amount_paid": _decimal(paid),
            "outstanding_balance": _decimal(outstanding),
        }
        for d_no, name, department, course, assessed, paid, outstanding in student_rows
    ]
    return {
        "semester_filter": semester,
        "total_outstanding": _decimal(total_outstanding),
        "by_fee_head": [
            {
                "fee_head": fee_head,
                "assessed_amount": _decimal(assessed),
                "amount_paid": _decimal(paid),
                "outstanding_balance": _decimal(outstanding),
            }
            for fee_head, assessed, paid, outstanding in fee_head_rows
        ],
        "by_department": [
            {
                "department": department,
                "assessed_amount": _decimal(assessed),
                "amount_paid": _decimal(paid),
                "outstanding_balance": _decimal(outstanding),
            }
            for department, assessed, paid, outstanding in department_rows
        ],
        "by_course": [
            {
                "course": course,
                "department": department,
                "assessed_amount": _decimal(assessed),
                "amount_paid": _decimal(paid),
                "outstanding_balance": _decimal(outstanding),
            }
            for course, department, assessed, paid, outstanding in course_rows
        ],
        "by_semester": [
            {
                "semester": semester_number,
                "assessed_amount": _decimal(assessed),
                "amount_paid": _decimal(paid),
                "outstanding_balance": _decimal(outstanding),
            }
            for semester_number, assessed, paid, outstanding in semester_rows
        ],
        "partially_paid_students": [
            student
            for student in students
            if student["amount_paid"] > 0 and student["outstanding_balance"] > 0
        ],
        "unpaid_students": [
            student for student in students if student["amount_paid"] == 0
        ],
        "pending_government_scholarships": [
            {
                "d_no": d_no,
                "name": name,
                "department": department,
                "category": category,
                "amount_pending": _decimal(amount),
                "source": "Scholarship",
            }
            for d_no, name, department, category, amount in legacy_scholarship_rows
        ]
        + [
            {
                "d_no": d_no,
                "name": name,
                "department": department,
                "category": category,
                "amount_pending": _decimal(amount),
                "source": "Scholarship claim",
            }
            for d_no, name, department, category, amount in pending_claim_rows
        ],
    }
