import argparse
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import exc
from sqlalchemy.dialects.postgresql import insert

from database import SessionLocal
from models import Student


LOGGER = logging.getLogger("import_excel")
D_NO_PATTERN = re.compile(r"^(\d)(\d)(\d{2,3})$")
REQUIRED_COLUMNS = {
    "D_No",
    "Student_Name",
    "Department",
    "Semester",
    "Scholarship_Category",
}


def _clean_text(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def parse_d_no(d_no: str) -> tuple[int, int, int]:
    match = D_NO_PATTERN.fullmatch(d_no)
    if match is None:
        raise ValueError(
            f"Invalid D_No {d_no!r}: expected a batch digit, a course digit, "
            "and a 2- or 3-digit roll number."
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _semester_number(value: Any) -> int | None:
    if pd.isna(value):
        return None
    try:
        semester = int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not numeric_value.is_integer():
            return None
        semester = int(numeric_value)
    return semester if semester > 0 else None


def import_students(file_path: Path) -> tuple[int, int]:
    dataframe = pd.read_excel(file_path, dtype={"D_No": "string"})
    missing_columns = REQUIRED_COLUMNS - set(dataframe.columns)
    if missing_columns:
        raise ValueError(
            f"Excel file is missing required columns: {', '.join(sorted(missing_columns))}"
        )

    records: list[dict[str, Any]] = []
    for row_number, row in dataframe.iterrows():
        excel_row = row_number + 2
        d_no = _clean_text(row["D_No"])
        if d_no is None:
            raise ValueError(f"Excel row {excel_row} is missing D_No.")

        try:
            batch, course, roll_number = parse_d_no(d_no)
        except ValueError as error:
            raise ValueError(f"Excel row {excel_row}: {error}") from error

        name = _clean_text(row["Student_Name"])
        department = _clean_text(row["Department"])
        semester = _semester_number(row["Semester"])
        if name is None or department is None or semester is None:
            raise ValueError(
                f"Excel row {excel_row} (D_No {d_no}): Student_Name, Department, "
                "and Semester must contain valid values."
            )

        records.append(
            {
                "d_no": d_no,
                "name": name,
                "department": department,
                "batch": batch,
                "course": course,
                "roll_number": roll_number,
                "semester": semester,
                "scholarship_type": _clean_text(row["Scholarship_Category"]),
                "status": "Active",
            }
        )

    if not records:
        return 0, 0

    statement = insert(Student).values(records).on_conflict_do_nothing(
        index_elements=[Student.d_no]
    )
    try:
        with SessionLocal.begin() as session:
            result = session.execute(statement)
    except exc.SQLAlchemyError:
        LOGGER.exception("Database insertion failed for %s.", file_path)
        raise

    imported = result.rowcount or 0
    duplicates = len(records) - imported
    return imported, duplicates


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Import student records from an Excel workbook."
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=Path("students_data.xlsx"),
        help="Excel workbook path (default: students_data.xlsx)",
    )
    args = parser.parse_args()

    try:
        imported, duplicates = import_students(args.file)
        print(
            f"Import complete: {imported} students imported; "
            f"{duplicates} existing D_No values skipped."
        )
    except Exception:
        LOGGER.exception("Student import failed for %s.", args.file)
        raise


if __name__ == "__main__":
    main()
