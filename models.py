from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from database import Base


class Student(Base):
    __tablename__ = "students"

    d_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    batch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    course: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roll_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    scholarship_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    fee_demands: Mapped[list["FeeDemand"]] = relationship(back_populates="student")
    transactions: Mapped[list["PaymentTransaction"]] = relationship(back_populates="student")
    scholarships: Mapped[list["Scholarship"]] = relationship(back_populates="student")
    scholarship_claims: Mapped[list["ScholarshipClaim"]] = relationship(
        back_populates="student"
    )


class FeeDemand(Base):
    __tablename__ = "fee_demands"
    __table_args__ = (
        CheckConstraint("assessed_amount >= 0", name="ck_fee_demands_assessed_amount_nonnegative"),
        CheckConstraint("amount_paid >= 0", name="ck_fee_demands_amount_paid_nonnegative"),
        CheckConstraint(
            "amount_paid <= assessed_amount",
            name="ck_fee_demands_amount_paid_not_over_assessed",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    d_no: Mapped[str] = mapped_column(ForeignKey("students.d_no"), nullable=False)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    fee_head: Mapped[str] = mapped_column(String(50), nullable=False)
    assessed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0"
    )
    outstanding_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        Computed("assessed_amount - amount_paid", persisted=True),
        nullable=False,
    )
    created_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())

    student: Mapped[Student] = relationship(back_populates="fee_demands")
    student_id = synonym("d_no")
    amount_assessed = synonym("assessed_amount")


class PaymentTransaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("counter_id IN ('1', '2', 'Bank')", name="ck_transactions_counter_id"),
        CheckConstraint(
            "payment_mode IN ('Cash', 'UPI', 'Bank', 'Bank Transfer', 'Govt Transfer')",
            name="ck_transactions_payment_mode",
        ),
        CheckConstraint("amount_paid >= 0", name="ck_transactions_amount_paid_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_no: Mapped[str] = mapped_column(
        String(32),
        Computed("CAST(id AS VARCHAR)", persisted=True),
        unique=True,
        nullable=False,
    )
    d_no: Mapped[str] = mapped_column(ForeignKey("students.d_no"), nullable=False)
    counter_id: Mapped[str] = mapped_column(String(10), nullable=False)
    fee_head: Mapped[str] = mapped_column(String(50), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    date_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    student: Mapped[Student] = relationship(back_populates="transactions")
    transaction_id = synonym("id")
    student_id = synonym("d_no")
    amount = synonym("amount_paid")
    counter_number = synonym("counter_id")


Transaction = PaymentTransaction


class Scholarship(Base):
    __tablename__ = "scholarships"
    __table_args__ = (
        CheckConstraint("sanctioned_amount >= 0", name="ck_scholarships_sanctioned_nonnegative"),
        CheckConstraint("pending_amount >= 0", name="ck_scholarships_pending_nonnegative"),
        CheckConstraint("received_amount >= 0", name="ck_scholarships_received_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    d_no: Mapped[str] = mapped_column(ForeignKey("students.d_no"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    sanctioned_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    pending_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    received_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    student: Mapped[Student] = relationship(back_populates="scholarships")


class ScholarshipClaim(Base):
    __tablename__ = "scholarship_claims"
    __table_args__ = (
        CheckConstraint("expected_amount >= 0", name="ck_scholarship_claims_expected_nonnegative"),
        CheckConstraint(
            "status IN ('Pending', 'Received')",
            name="ck_scholarship_claims_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    d_no: Mapped[str] = mapped_column(ForeignKey("students.d_no"), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Pending", server_default="Pending"
    )

    student: Mapped[Student] = relationship(back_populates="scholarship_claims")
    student_id = synonym("d_no")
    claim_id = synonym("id")
