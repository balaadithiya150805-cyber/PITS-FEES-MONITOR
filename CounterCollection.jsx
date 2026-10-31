import { useRef, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const PAYMENT_MODES = ["Cash", "UPI", "Bank Transfer"];
const currencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
});

function formatCurrency(value) {
  return currencyFormatter.format(Number(value ?? 0));
}

function getErrorMessage(payload, fallback) {
  return typeof payload?.detail === "string" ? payload.detail : fallback;
}

function getCounterNumber() {
  const counterNumber = window.sessionStorage.getItem("counter_number");
  return counterNumber === "2" ? "2" : "1";
}

function formatDateTime(value) {
  const date = value ? new Date(value) : new Date();
  return date.toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function ReceiptComponent({ student, transaction, outstandingBalance }) {
  return (
    <article
      className="mx-auto mt-8 max-w-2xl rounded-lg border border-slate-300 bg-white p-6 text-slate-900 shadow-sm print:mt-0 print:max-w-none print:border-0 print:p-0 print:shadow-none"
      id="fee-collection-receipt"
    >
      <style>{`
        @media print {
          body * { visibility: hidden; }
          #fee-collection-receipt, #fee-collection-receipt * { visibility: visible; }
          #fee-collection-receipt {
            position: absolute;
            inset: 0;
            width: 100%;
            max-width: none;
            margin: 0;
            border: 0;
            box-shadow: none;
          }
          @page { margin: 14mm; }
        }
      `}</style>
      <header className="border-b-2 border-slate-900 pb-4 text-center">
        <h2 className="text-xl font-bold tracking-wide">
          PARISUTHAM INSTITUTE OF TECHNOLOGY &amp; SCIENCE
        </h2>
        <p className="mt-2 text-sm font-semibold">FEE COLLECTION RECEIPT</p>
        <p className="mt-1 text-sm">
          Receipt No: {transaction.receipt_no ?? transaction.transaction_id}
        </p>
      </header>

      <dl className="my-5 grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
        <div><dt className="inline font-semibold">Date &amp; Time: </dt><dd className="inline">{formatDateTime(transaction.date_time)}</dd></div>
        <div><dt className="inline font-semibold">D.No: </dt><dd className="inline">{student.d_no}</dd></div>
        <div><dt className="inline font-semibold">Student: </dt><dd className="inline">{student.name}</dd></div>
        <div><dt className="inline font-semibold">Department: </dt><dd className="inline">{student.department}</dd></div>
        <div><dt className="inline font-semibold">Semester: </dt><dd className="inline">{student.semester}</dd></div>
        <div><dt className="inline font-semibold">Payment Mode: </dt><dd className="inline">{transaction.payment_mode}</dd></div>
      </dl>

      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-y border-slate-400">
            <th className="py-2 pr-3">Fee Head</th>
            <th className="py-2 pr-3 text-right">Amount Paid</th>
            <th className="py-2 text-right">Balance Outstanding</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-slate-300">
            <td className="py-3 pr-3">{transaction.fee_head}</td>
            <td className="py-3 pr-3 text-right">{formatCurrency(transaction.amount)}</td>
            <td className="py-3 text-right">{formatCurrency(outstandingBalance)}</td>
          </tr>
        </tbody>
      </table>
      <p className="mt-8 text-center text-sm">Thank you.</p>
    </article>
  );
}

export default function CounterCollection() {
  const [dNo, setDNo] = useState("");
  const [studentResult, setStudentResult] = useState(null);
  const [paymentAmounts, setPaymentAmounts] = useState({});
  const [counterNumber] = useState(getCounterNumber);
  const [paymentMode, setPaymentMode] = useState("Cash");
  const [receipt, setReceipt] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const submissionLock = useRef(false);

  async function searchStudent(event) {
    event.preventDefault();
    const searchValue = dNo.trim();
    if (!searchValue) {
      setError("Enter a D.No to search.");
      return;
    }

    setIsSearching(true);
    setError("");
    setMessage("");
    setReceipt(null);
    setStudentResult(null);
    setPaymentAmounts({});

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/student/${encodeURIComponent(searchValue)}`,
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Unable to find student."));
      }
      setStudentResult(payload);
    } catch (requestError) {
      setError(requestError.message || "Unable to find student.");
    } finally {
      setIsSearching(false);
    }
  }

  async function submitPayment(event) {
    event.preventDefault();
    if (submissionLock.current) return;
    submissionLock.current = true;

    const student = studentResult?.student;
    if (!student) {
      setError("Search for a student before recording a payment.");
      submissionLock.current = false;
      return;
    }

    const payments = (studentResult.assessed_fees ?? [])
      .map((fee) => ({
        fee,
        amount: String(paymentAmounts[fee.fee_head] ?? "").trim(),
      }))
      .filter((payment) => payment.amount !== "");

    if (
      payments.length !== 1
      || !/^\d+(\.\d{1,2})?$/.test(payments[0]?.amount ?? "")
      || Number(payments[0]?.amount) <= 0
    ) {
      setError("Enter a valid payment greater than zero for exactly one fee head.");
      submissionLock.current = false;
      return;
    }

    const { fee, amount } = payments[0];
    if (Number(amount) > Number(fee.outstanding_balance)) {
      setError("Payment cannot exceed the outstanding balance.");
      submissionLock.current = false;
      return;
    }

    setIsSubmitting(true);
    setError("");
    setMessage("");
    setReceipt(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/pay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          d_no: student.d_no,
          fee_head: fee.fee_head,
          amount,
          payment_mode: paymentMode,
          counter_number: counterNumber,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Unable to record payment."));
      }
      if (!payload.transaction) {
        throw new Error("Payment was accepted, but no receipt details were returned.");
      }

      const outstandingBalance = Number(payload.outstanding_balance);
      setReceipt({
        student,
        transaction: payload.transaction,
        outstandingBalance,
      });
      setStudentResult((current) => ({
        ...current,
        assessed_fees: current.assessed_fees.map((currentFee) =>
          currentFee.fee_head === fee.fee_head
            ? {
                ...currentFee,
                paid_amount: Number(currentFee.paid_amount ?? 0) + Number(amount),
                outstanding_balance: outstandingBalance,
              }
            : currentFee,
        ),
      }));
      setPaymentAmounts({});
      setMessage("Payment recorded successfully. Your receipt is ready to print.");
    } catch (requestError) {
      setError(requestError.message || "Unable to record payment.");
    } finally {
      setIsSubmitting(false);
      submissionLock.current = false;
    }
  }

  const student = studentResult?.student;
  const fees = studentResult?.assessed_fees ?? [];

  return (
    <main className="mx-auto max-w-5xl p-4 sm:p-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7 print:hidden">
        <header className="mb-6">
          <p className="text-sm font-semibold uppercase tracking-wide text-blue-700">
            PITS Fees Monitor
          </p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">
            Daily Fee Collection
          </h1>
        </header>

        <form className="mb-6 flex flex-col gap-3 sm:flex-row" onSubmit={searchStudent}>
          <label className="sr-only" htmlFor="student-dno">Student D.No</label>
          <input
            id="student-dno"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2"
            value={dNo}
            onChange={(event) => setDNo(event.target.value)}
            placeholder="Enter student D.No"
            autoComplete="off"
            disabled={isSearching || isSubmitting}
          />
          <button
            className="rounded-md bg-blue-700 px-5 py-2 font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
            type="submit"
            disabled={isSearching || isSubmitting}
          >
            {isSearching ? "Searching..." : "Search student"}
          </button>
        </form>

        {error && <p className="mb-4 rounded-md bg-red-50 p-3 text-red-700" role="alert">{error}</p>}
        {message && <p className="mb-4 rounded-md bg-green-50 p-3 text-green-800" role="status">{message}</p>}

        {student && (
          <form onSubmit={submitPayment}>
            <section
              aria-label="Student details"
              className="mb-6 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-3"
            >
              <p><strong>Name:</strong> {student.name}</p>
              <p><strong>Department:</strong> {student.department}</p>
              <p><strong>Semester:</strong> {student.semester}</p>
            </section>

            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-slate-300 text-sm text-slate-600">
                    <th className="p-3">Fee Head</th>
                    <th className="p-3 text-right">Outstanding Balance</th>
                    <th className="p-3 text-right">Amount Paid</th>
                  </tr>
                </thead>
                <tbody>
                  {fees.map((fee) => (
                    <tr className="border-b border-slate-200" key={fee.fee_head}>
                      <td className="p-3 font-medium text-slate-800">{fee.fee_head}</td>
                      <td className="p-3 text-right">{formatCurrency(fee.outstanding_balance)}</td>
                      <td className="p-3 text-right">
                        <label className="sr-only" htmlFor={`payment-${fee.fee_head}`}>
                          Payment amount for {fee.fee_head}
                        </label>
                        <input
                          id={`payment-${fee.fee_head}`}
                          className="w-36 rounded-md border border-slate-300 px-2 py-1 text-right disabled:bg-slate-100"
                          type="number"
                          min="0"
                          max={fee.outstanding_balance}
                          step="0.01"
                          inputMode="decimal"
                          value={paymentAmounts[fee.fee_head] ?? ""}
                          onChange={(event) =>
                            setPaymentAmounts((current) => ({
                              ...current,
                              [fee.fee_head]: event.target.value,
                            }))
                          }
                          placeholder="0.00"
                          disabled={isSubmitting || Number(fee.outstanding_balance) <= 0}
                        />
                      </td>
                    </tr>
                  ))}
                  {fees.length === 0 && (
                    <tr>
                      <td className="p-4 text-slate-500" colSpan="3">
                        No assessed fee heads found for this student.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-end">
              <div>
                <label className="mb-1 block text-sm font-medium" htmlFor="payment-mode">
                  Payment Mode
                </label>
                <select
                  id="payment-mode"
                  className="rounded-md border border-slate-300 px-3 py-2"
                  value={paymentMode}
                  onChange={(event) => setPaymentMode(event.target.value)}
                  disabled={isSubmitting}
                >
                  {PAYMENT_MODES.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
                </select>
              </div>

              <button
                className="inline-flex min-w-56 items-center justify-center gap-2 rounded-md bg-green-700 px-5 py-2 font-semibold text-white hover:bg-green-800 disabled:cursor-not-allowed disabled:opacity-60"
                type="submit"
                disabled={isSubmitting || fees.length === 0}
                aria-busy={isSubmitting}
              >
                {isSubmitting && (
                  <span
                    className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
                    aria-hidden="true"
                  />
                )}
                {isSubmitting ? "Recording payment..." : "Record payment"}
              </button>
            </div>
          </form>
        )}
      </section>

      {receipt && (
        <section aria-label="Payment receipt">
          <div className="mt-6 flex justify-end print:hidden">
            <button
              className="rounded-md bg-slate-900 px-5 py-2 font-semibold text-white hover:bg-slate-700"
              type="button"
              onClick={() => window.print()}
            >
              Print receipt
            </button>
          </div>
          <ReceiptComponent
            student={receipt.student}
            transaction={receipt.transaction}
            outstandingBalance={receipt.outstandingBalance}
          />
        </section>
      )}
    </main>
  );
}
