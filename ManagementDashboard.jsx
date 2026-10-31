import { useCallback, useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const TABS = [
  { id: "daily", label: "Daily Collections" },
  { id: "arrears", label: "Student Ledgers / Arrears" },
];
const currencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
});

function localDateValue() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function formatCurrency(value) {
  return currencyFormatter.format(Number(value ?? 0));
}

function formatReportDate(value) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    dateStyle: "long",
  });
}

async function fetchReport(url, fallback) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(
      typeof payload?.detail === "string" ? payload.detail : fallback,
    );
  }
  return payload;
}

function csvCell(value) {
  let text = String(value ?? "");
  if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(filename, headers, rows) {
  const content = [headers, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n");
  const blob = new Blob(["\uFEFF", content], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function dailyExportRows(report) {
  const rows = [
    ["Summary", "Report Date", report.report_date],
    ["Summary", "Total Collected", report.total_collected],
  ];
  for (const [section, items, labelFor] of [
    ["Payment Mode", report.by_payment_mode, (item) => item.payment_mode],
    ["Fee Head", report.by_fee_head, (item) => item.fee_head],
    ["Counter", report.by_counter, (item) => `Counter ${item.counter_id}`],
  ]) {
    for (const item of items ?? []) {
      rows.push([section, labelFor(item), item.total]);
    }
  }
  return rows;
}

function arrearsExportRows(report) {
  const rows = [
    ["Summary", "", "", "", `Semester ${report.semester_filter ?? "All"}`, report.total_outstanding, "", "", ""],
  ];
  for (const [section, students] of [
    ["Partially Paid Students", report.partially_paid_students],
    ["Unpaid Students", report.unpaid_students],
  ]) {
    for (const student of students ?? []) {
      rows.push([
        section,
        student.d_no,
        student.name,
        student.department,
        student.course ?? "",
        student.assessed_amount,
        student.amount_paid,
        student.outstanding_balance,
        "",
      ]);
    }
  }
  for (const claim of report.pending_government_scholarships ?? []) {
    rows.push([
      "Pending Government Scholarship",
      claim.d_no,
      claim.name,
      claim.department,
      claim.category,
      claim.amount_pending,
      "",
      "",
      claim.source,
    ]);
  }
  return rows;
}

function DataTable({ headers, children, emptyMessage, isEmpty = false }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-slate-500">
            {headers.map((header) => (
              <th className="whitespace-nowrap px-3 py-3 font-medium" key={header}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {isEmpty ? (
            <tr>
              <td className="px-3 py-5 text-slate-500" colSpan={headers.length}>
                {emptyMessage}
              </td>
            </tr>
          ) : children}
        </tbody>
      </table>
    </div>
  );
}

function AmountRows({ rows, nameKey, nameLabel }) {
  if (!rows?.length) return null;
  return rows.map((row) => (
    <tr className="border-b border-slate-100 last:border-0" key={row[nameKey]}>
      <td className="px-3 py-3 font-medium text-slate-800">{row[nameKey] ?? "Unspecified"}</td>
      {nameLabel === "Balances" ? (
        <>
          <td className="px-3 py-3 text-right">{formatCurrency(row.assessed_amount)}</td>
          <td className="px-3 py-3 text-right">{formatCurrency(row.amount_paid)}</td>
          <td className="px-3 py-3 text-right font-semibold">{formatCurrency(row.outstanding_balance)}</td>
        </>
      ) : (
        <td className="px-3 py-3 text-right">{formatCurrency(row.total)}</td>
      )}
    </tr>
  ));
}

function StudentRows({ students }) {
  if (!students?.length) return null;
  return students.map((student) => (
    <tr className="border-b border-slate-100 last:border-0" key={student.d_no}>
      <td className="whitespace-nowrap px-3 py-3 font-medium">{student.d_no}</td>
      <td className="px-3 py-3">{student.name}</td>
      <td className="px-3 py-3">{student.department}</td>
      <td className="px-3 py-3">{student.course ?? "—"}</td>
      <td className="px-3 py-3 text-right">{formatCurrency(student.assessed_amount)}</td>
      <td className="px-3 py-3 text-right">{formatCurrency(student.amount_paid)}</td>
      <td className="px-3 py-3 text-right font-semibold">{formatCurrency(student.outstanding_balance)}</td>
    </tr>
  ));
}

export default function ManagementDashboard() {
  const [activeTab, setActiveTab] = useState("daily");
  const [reportDate, setReportDate] = useState(localDateValue);
  const [semester, setSemester] = useState("");
  const [dailyReport, setDailyReport] = useState(null);
  const [arrearsReport, setArrearsReport] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const loadReports = useCallback(async () => {
    setIsLoading(true);
    setError("");
    const dailyUrl = `${API_BASE_URL}/api/reports/daily-collections?report_date=${encodeURIComponent(reportDate)}`;
    const semesterFilter = semester
      ? `?semester=${encodeURIComponent(semester)}`
      : "";
    const arrearsUrl =
      `${API_BASE_URL}/api/reports/outstanding-arrears${semesterFilter}`;

    try {
      const [daily, arrears] = await Promise.all([
        fetchReport(dailyUrl, "Unable to load daily collections."),
        fetchReport(arrearsUrl, "Unable to load outstanding arrears."),
      ]);
      setDailyReport(daily);
      setArrearsReport(arrears);
    } catch (requestError) {
      setError(requestError.message || "Unable to load management reports.");
    } finally {
      setIsLoading(false);
    }
  }, [reportDate, semester]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  const semesters = arrearsReport?.by_semester ?? [];
  const dailyRows = dailyReport?.by_payment_mode ?? [];

  function exportCurrentReport() {
    if (activeTab === "daily" && dailyReport) {
      downloadCsv(
        `daily-collections-${dailyReport.report_date}.csv`,
        ["Report", "Label", "Amount"],
        dailyExportRows(dailyReport),
      );
    } else if (activeTab === "arrears" && arrearsReport) {
      downloadCsv(
        `student-arrears-${arrearsReport.semester_filter ?? "all"}.csv`,
        ["Record Type", "D.No", "Name", "Department", "Course / Category", "Assessed / Pending", "Paid", "Outstanding", "Source"],
        arrearsExportRows(arrearsReport),
      );
    }
  }

  return (
    <main className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      <style>{`
        @media print {
          body { background: white !important; }
          .dashboard-no-print { display: none !important; }
          .dashboard-card, .dashboard-panel { box-shadow: none !important; }
          main { max-width: none !important; padding: 0 !important; }
        }
      `}</style>
      <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-blue-700">
            PITS Fees Monitor
          </p>
          <h1 className="mt-1 text-3xl font-bold text-slate-900">
            Management Dashboard
          </h1>
          <p className="mt-2 text-slate-600">
            Daily collections and student arrears
          </p>
        </div>
        <div className="dashboard-no-print flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700" htmlFor="report-date">
              Collection date
            </label>
            <input
              className="rounded-md border border-slate-300 px-3 py-2"
              id="report-date"
              type="date"
              value={reportDate}
              onChange={(event) => setReportDate(event.target.value)}
            />
          </div>
          <button
            className="rounded-md border border-slate-300 bg-white px-4 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            type="button"
            onClick={loadReports}
            disabled={isLoading}
          >
            {isLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800" role="alert">
          <p>{error}</p>
          <button className="mt-2 font-semibold underline" type="button" onClick={loadReports}>
            Try again
          </button>
        </div>
      )}

      <section aria-label="Summary metrics" className="mb-8 grid gap-4 sm:grid-cols-2">
        <article className="dashboard-card rounded-xl bg-blue-700 p-5 text-white shadow-sm">
          <h2 className="text-sm font-medium text-blue-100">
            Collection · {formatReportDate(dailyReport?.report_date)}
          </h2>
          <p className="mt-3 text-3xl font-bold">
            {formatCurrency(dailyReport?.total_collected)}
          </p>
        </article>
        <article className="dashboard-card rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-medium text-slate-500">
            {semester ? `Semester ${semester} Arrears` : "Total College Arrears"}
          </h2>
          <p className="mt-3 text-3xl font-bold text-slate-900">
            {formatCurrency(arrearsReport?.total_outstanding)}
          </p>
        </article>
      </section>

      <div className="dashboard-no-print mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex border-b border-slate-200" role="tablist" aria-label="Management reports">
          {TABS.map((tab) => (
            <button
              aria-selected={activeTab === tab.id}
              className={`border-b-2 px-4 py-3 text-sm font-semibold ${
                activeTab === tab.id
                  ? "border-blue-700 text-blue-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
              id={`tab-${tab.id}`}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              role="tab"
              type="button"
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {activeTab === "arrears" && (
            <label className="sr-only" htmlFor="semester-filter">Filter by semester</label>
          )}
          {activeTab === "arrears" && (
            <select
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
              id="semester-filter"
              value={semester}
              onChange={(event) => setSemester(event.target.value)}
            >
              <option value="">All semesters</option>
              {semesters.map((row) => (
                <option key={row.semester} value={row.semester}>
                  Semester {row.semester}
                </option>
              ))}
            </select>
          )}
          <button
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            type="button"
            onClick={exportCurrentReport}
            disabled={isLoading || (activeTab === "daily" ? !dailyReport : !arrearsReport)}
          >
            Export to Excel (.csv)
          </button>
          <button
            className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
            type="button"
            onClick={() => window.print()}
          >
            Export to PDF
          </button>
        </div>
      </div>

      {isLoading && !dailyReport && !arrearsReport ? (
        <p className="rounded-lg bg-white p-6 text-slate-600 shadow-sm" role="status">
          Loading management reports...
        </p>
      ) : (
        <>
          {activeTab === "daily" && (
            <section
              aria-labelledby="tab-daily"
              className="dashboard-panel space-y-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
              role="tabpanel"
            >
              <header>
                <h2 className="text-lg font-semibold text-slate-900">
                  Daily Collections · {formatReportDate(dailyReport?.report_date)}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Totals include recorded collections and government scholarship transfers.
                </p>
              </header>
              <div className="grid gap-6 lg:grid-cols-2">
                <section>
                  <h3 className="mb-2 font-semibold text-slate-800">By Payment Mode</h3>
                  <DataTable
                    headers={["Payment Mode", "Collected"]}
                    emptyMessage="No collections for this date."
                    isEmpty={!dailyRows.length}
                  >
                    <AmountRows rows={dailyRows} nameKey="payment_mode" />
                  </DataTable>
                </section>
                <section>
                  <h3 className="mb-2 font-semibold text-slate-800">By Fee Head</h3>
                  <DataTable
                    headers={["Fee Head", "Collected"]}
                    emptyMessage="No collections for this date."
                    isEmpty={!dailyReport?.by_fee_head?.length}
                  >
                    <AmountRows rows={dailyReport?.by_fee_head} nameKey="fee_head" />
                  </DataTable>
                </section>
                <section>
                  <h3 className="mb-2 font-semibold text-slate-800">By Counter</h3>
                  <DataTable
                    headers={["Counter", "Collected"]}
                    emptyMessage="No counter collections for this date."
                    isEmpty={!dailyReport?.by_counter?.length}
                  >
                    <AmountRows
                      rows={(dailyReport?.by_counter ?? []).map((row) => ({
                        ...row,
                        counter_label: row.counter_id === "Bank" ? "Bank" : `Counter ${row.counter_id}`,
                      }))}
                      nameKey="counter_label"
                    />
                  </DataTable>
                </section>
              </div>
            </section>
          )}

          {activeTab === "arrears" && (
            <section
              aria-labelledby="tab-arrears"
              className="dashboard-panel space-y-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
              role="tabpanel"
            >
              <header>
                <h2 className="text-lg font-semibold text-slate-900">
                  Student Ledgers / Arrears
                  {semester ? ` · Semester ${semester}` : " · Consolidated"}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Semester totals remain available for comparison when viewing consolidated arrears.
                </p>
              </header>

              <section>
                <h3 className="mb-2 font-semibold text-slate-800">Arrears by Fee Head</h3>
                <DataTable
                  headers={["Fee Head", "Assessed", "Paid", "Outstanding"]}
                  emptyMessage="No fee demands found."
                  isEmpty={!arrearsReport?.by_fee_head?.length}
                >
                  <AmountRows rows={arrearsReport?.by_fee_head} nameKey="fee_head" nameLabel="Balances" />
                </DataTable>
              </section>

              <div className="grid gap-6 lg:grid-cols-2">
                <section>
                  <h3 className="mb-2 font-semibold text-slate-800">Arrears by Department</h3>
                  <DataTable
                    headers={["Department", "Assessed", "Paid", "Outstanding"]}
                    emptyMessage="No department balances found."
                    isEmpty={!arrearsReport?.by_department?.length}
                  >
                    <AmountRows rows={arrearsReport?.by_department} nameKey="department" nameLabel="Balances" />
                  </DataTable>
                </section>
                <section>
                  <h3 className="mb-2 font-semibold text-slate-800">Arrears by Course</h3>
                  <DataTable
                    headers={["Course", "Department", "Assessed", "Paid", "Outstanding"]}
                    emptyMessage="No course balances found."
                    isEmpty={!arrearsReport?.by_course?.length}
                  >
                    {(arrearsReport?.by_course ?? []).map((row) => (
                      <tr className="border-b border-slate-100 last:border-0" key={`${row.department}-${row.course}`}>
                        <td className="px-3 py-3">{row.course ?? "Unspecified"}</td>
                        <td className="px-3 py-3">{row.department}</td>
                        <td className="px-3 py-3 text-right">{formatCurrency(row.assessed_amount)}</td>
                        <td className="px-3 py-3 text-right">{formatCurrency(row.amount_paid)}</td>
                        <td className="px-3 py-3 text-right font-semibold">{formatCurrency(row.outstanding_balance)}</td>
                      </tr>
                    ))}
                  </DataTable>
                </section>
              </div>

              {!semester && (
                <section>
                  <h3 className="mb-2 font-semibold text-slate-800">Arrears by Semester</h3>
                  <DataTable
                    headers={["Semester", "Assessed", "Paid", "Outstanding"]}
                    emptyMessage="No semester balances found."
                    isEmpty={!arrearsReport?.by_semester?.length}
                  >
                    {(arrearsReport?.by_semester ?? []).map((row) => (
                      <tr className="border-b border-slate-100 last:border-0" key={row.semester}>
                        <td className="px-3 py-3">Semester {row.semester}</td>
                        <td className="px-3 py-3 text-right">{formatCurrency(row.assessed_amount)}</td>
                        <td className="px-3 py-3 text-right">{formatCurrency(row.amount_paid)}</td>
                        <td className="px-3 py-3 text-right font-semibold">{formatCurrency(row.outstanding_balance)}</td>
                      </tr>
                    ))}
                  </DataTable>
                </section>
              )}

              <section>
                <h3 className="mb-2 font-semibold text-slate-800">Partially Paid Students</h3>
                <DataTable
                  headers={["D.No", "Student", "Department", "Course", "Assessed", "Paid", "Outstanding"]}
                  emptyMessage="No partially paid student balances."
                  isEmpty={!arrearsReport?.partially_paid_students?.length}
                >
                  <StudentRows students={arrearsReport?.partially_paid_students} />
                </DataTable>
              </section>

              <section>
                <h3 className="mb-2 font-semibold text-slate-800">Students with No Payments</h3>
                <DataTable
                  headers={["D.No", "Student", "Department", "Course", "Assessed", "Paid", "Outstanding"]}
                  emptyMessage="No unpaid student balances."
                  isEmpty={!arrearsReport?.unpaid_students?.length}
                >
                  <StudentRows students={arrearsReport?.unpaid_students} />
                </DataTable>
              </section>

              <section>
                <h3 className="mb-2 font-semibold text-slate-800">
                  Scholarships Pending from Government
                </h3>
                <DataTable
                  headers={["D.No", "Student", "Department", "Category", "Amount Pending", "Record Source"]}
                  emptyMessage="No pending scholarship amounts."
                  isEmpty={!arrearsReport?.pending_government_scholarships?.length}
                >
                  {(arrearsReport?.pending_government_scholarships ?? []).map((claim, index) => (
                    <tr className="border-b border-slate-100 last:border-0" key={`${claim.source}-${claim.d_no}-${claim.category}-${index}`}>
                      <td className="px-3 py-3">{claim.d_no}</td>
                      <td className="px-3 py-3">{claim.name}</td>
                      <td className="px-3 py-3">{claim.department}</td>
                      <td className="px-3 py-3">{claim.category}</td>
                      <td className="px-3 py-3 text-right">{formatCurrency(claim.amount_pending)}</td>
                      <td className="px-3 py-3">{claim.source}</td>
                    </tr>
                  ))}
                </DataTable>
              </section>
            </section>
          )}
        </>
      )}
    </main>
  );
}
