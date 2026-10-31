import argparse
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from database import SessionLocal
from models import Student


LOGGER = logging.getLogger("ingest_students")
D_NO_PATTERN = re.compile(r"^\d{3,}$")
REQUIRED_COLUMNS = {"D.No", "Name", "Department", "Current_Semester"}


def _clean_text(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


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


def ingest_students(file_path: Path) -> tuple[int, int]:
    dataframe = pd.read_excel(file_path, dtype={"D.No": "string"})
    missing_columns = REQUIRED_COLUMNS - set(dataframe.columns)
    if missing_columns:
        raise ValueError(f"Excel file is missing required columns: {', '.join(sorted(missing_columns))}")

    records: list[dict[str, Any]] = []
    for row_number, row in dataframe.iterrows():
        excel_row = row_number + 2
        d_no = _clean_text(row["D.No"])
        if d_no is None or D_NO_PATTERN.fullmatch(d_no) is None:
            LOGGER.warning(
                "Skipping Excel row %s: invalid D.No %r; expected digits "
                "with batch (1 digit), course (1 digit), and roll number.",
                excel_row,
                d_no,
            )
            continue

        name = _clean_text(row["Name"])
        department = _clean_text(row["Department"])
        semester = _semester_number(row["Current_Semester"])
        if name is None or department is None or semester is None:
            LOGGER.warning(
                "Skipping Excel row %s (D.No %s): Name, Department, and "
                "Current_Semester must be populated with valid values.",
                excel_row,
                d_no,
            )
            continue

        records.append(
            {
                "d_no": d_no,
                "name": name,
                "department": department,
                "semester": semester,
                "status": "Active",
            }
        )

    if not records:
        LOGGER.info("No valid student records found in %s.", file_path)
        return 0, 0

    statement = insert(Student).values(records).on_conflict_do_nothing(
        index_elements=[Student.d_no]
    )
    with SessionLocal.begin() as session:
        result = session.execute(statement)

    inserted = result.rowcount or 0
    duplicates = len(records) - inserted
    LOGGER.info("Inserted %s students; skipped %s duplicate D.No values.", inserted, duplicates)
    return inserted, duplicates


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Import students from an Excel workbook.")
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=Path("students.xlsx"),
        help="Excel workbook path (default: students.xlsx)",
    )
    args = parser.parse_args()

    try:
        ingest_students(args.file)
    except Exception:
        LOGGER.exception("Student import failed for %s.", args.file)
        raise


if __name__ == "__main__":
    main()
