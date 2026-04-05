"use client";

import { useState, useRef } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { transactions } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Plus,
  Upload,
  TrendingUp,
  TrendingDown,
  CheckCircle,
  Clock,
  Trash2,
} from "lucide-react";
import { useCategories } from "@/lib/use-categories";

function fmt(n: number) {
  return `£${Math.abs(n).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

const SOURCE_COLOURS: Record<string, string> = {
  stripe: "bg-blue-100 text-blue-700",
  csv: "bg-violet-100 text-violet-700",
  pdf: "bg-amber-100 text-amber-700",
  manual: "bg-slate-100 text-slate-600",
};

export default function TransactionsPage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [source, setSource] = useState("");
  const [page, setPage] = useState(1);
  const [addOpen, setAddOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const {
    categories: categoryList,
    getCategoryName,
    getCategoryType,
  } = useCategories();
  // Manual add form
  const [form, setForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    description: "",
    amount: "",
    notes: "",
    category_id: "",
  });
  const [addLoading, setAddLoading] = useState(false);

  const { data, error, isLoading, mutate } = useSWR(
    ["transactions", page, dateFrom, dateTo, source],
    () =>
      transactions.list({
        page,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        source: source || undefined,
      })
  );

  // Summary stats from current page
  const income = data
    ?.filter((t) => t.amount > 0)
    .reduce((s, t) => s + t.amount, 0) ?? 0;
  const expenses = data
    ?.filter((t) => t.amount < 0)
    .reduce((s, t) => s + Math.abs(t.amount), 0) ?? 0;
  const unconfirmed = data?.filter((t) => !t.is_confirmed).length ?? 0;

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportMsg("");
    try {
      const result = await transactions.importCsv(file);
      setImportMsg(
        `✅ Import queued — task ID: ${result.task_id}. ` +
        `Transactions will appear shortly.`
      );
      pollTaskStatus(result.task_id)
    } catch {
      setImportMsg("❌ Import failed. Check file format.");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  // After importCsv succeeds, poll for completion
  const pollTaskStatus = async (taskId: string) => {
    const maxAttempts = 12;   // poll for up to 60 seconds
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 5000));  // wait 5s
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/transactions/tasks/${taskId}`,
        {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("access_token")}`,
          },
        }
      );
      const data = await res.json();
      if (data.status === "complete") {
        setImportMsg(
          `✅ Import complete — ${data.result?.imported ?? 0} transactions added.`
        );
        await mutate();   // refresh transaction list
        return;
      }
      if (data.status === "failed") {
        setImportMsg("❌ Import failed — check your CSV format.");
        return;
      }
      setImportMsg(`⏳ Processing... (${i + 1}/${maxAttempts})`);
    }
    setImportMsg("⚠️ Import is taking longer than expected. Check back shortly.");
  };
  const handleDelete = async (id: string) => {
    if (!confirm("Delete this transaction? This cannot be undone.")) return;
    try {
      await transactions.delete(id);
      await mutate();
      toast.success("Transaction deleted");
    } catch (err: any) {
      toast.error(err.message ?? "Failed to delete transaction");
    }
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddLoading(true);
    try {
      await transactions.create({
        date: form.date,
        description: form.description,
        amount: parseFloat(form.amount),
        category_id: form.category_id || undefined,
        notes: form.notes || undefined,
        source: "manual",
      });
      await mutate();
      setAddOpen(false);
      setForm({
        date: new Date().toISOString().slice(0, 10),
        description: "",
        amount: "",
        notes: "",
        category_id: "",
      });
      toast.success("Transaction added");
    } catch (err: any) {
      toast.error(err.message ?? "Failed to add transaction");
    } finally {
      setAddLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Transactions</h1>
          <p className="text-slate-500 text-sm">
            {data?.length ?? 0} records shown
          </p>
        </div>
        <div className="flex gap-2">
          {/* CSV upload */}
          <Button
            variant="outline"
            disabled={importing}
            onClick={() => fileRef.current?.click()}
          >
            <Upload size={14} className="mr-2" />
            {importing ? "Importing..." : "Import CSV"}
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleCsvUpload}
          />

          {/* Manual add */}
          <Dialog open={addOpen} onOpenChange={setAddOpen}>
            <DialogTrigger asChild>
              <Button className="bg-violet-600 hover:bg-violet-700">
                <Plus size={14} className="mr-2" />
                Add
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Add Transaction</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleAdd} className="space-y-4">
                <div className="space-y-1">
                  <Label>Date</Label>
                  <Input
                    type="date"
                    value={form.date}
                    onChange={(e) =>
                      setForm({ ...form, date: e.target.value })
                    }
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label>Description</Label>
                  <Input
                    value={form.description}
                    onChange={(e) =>
                      setForm({ ...form, description: e.target.value })
                    }
                    placeholder="e.g. Client payment — ACME Ltd"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label>Category</Label>
                  <select
                    value={form.category_id}
                    onChange={(e) =>
                      setForm({ ...form, category_id: e.target.value })
                    }
                    className="w-full h-9 rounded-md border border-slate-200
               bg-white px-3 text-sm text-slate-700
               focus:outline-none focus:ring-2
               focus:ring-violet-500"
                  >
                    <option value="">— Select category —</option>
                    {categoryList
                      .filter((c) =>
                        parseFloat(form.amount) >= 0
                          ? c.type === "income"
                          : c.type === "expense"
                      )
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </select>
                  <p className="text-xs text-slate-400">
                    Filtered by income/expense based on amount
                  </p>
                </div>
                <div className="space-y-1">
                  <Label>Amount (£)</Label>
                  <Input
                    type="number"
                    step="0.01"
                    value={form.amount}
                    onChange={(e) =>
                      setForm({ ...form, amount: e.target.value })
                    }
                    placeholder="Positive = income, negative = expense"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label>Notes (optional)</Label>
                  <Input
                    value={form.notes}
                    onChange={(e) =>
                      setForm({ ...form, notes: e.target.value })
                    }
                    placeholder="Any additional notes"
                  />
                </div>
                <Button
                  type="submit"
                  className="w-full bg-violet-600 hover:bg-violet-700"
                  disabled={addLoading}
                >
                  {addLoading ? "Adding..." : "Add Transaction"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Import status message */}
      {importMsg && (
        <div className="text-sm bg-slate-50 border border-slate-200
                        rounded-lg p-3 text-slate-700">
          {importMsg}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <div className="p-2 bg-green-100 rounded-lg">
              <TrendingUp size={18} className="text-green-600" />
            </div>
            <div>
              <p className="text-xs text-slate-500">Income shown</p>
              <p className="text-lg font-bold text-green-600">
                +{fmt(income)}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <div className="p-2 bg-red-100 rounded-lg">
              <TrendingDown size={18} className="text-red-500" />
            </div>
            <div>
              <p className="text-xs text-slate-500">Expenses shown</p>
              <p className="text-lg font-bold text-red-500">
                -{fmt(expenses)}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <div className="p-2 bg-amber-100 rounded-lg">
              <Clock size={18} className="text-amber-600" />
            </div>
            <div>
              <p className="text-xs text-slate-500">
                Awaiting confirmation
              </p>
              <p className="text-lg font-bold text-amber-600">
                {unconfirmed}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="space-y-1">
              <Label className="text-xs">From</Label>
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value);
                  setPage(1);
                }}
                className="w-36"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">To</Label>
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setPage(1);
                }}
                className="w-36"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Source</Label>
              <select
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  setPage(1);
                }}
                className="h-9 rounded-md border border-slate-200
                           bg-white px-3 text-sm text-slate-700
                           focus:outline-none focus:ring-2
                           focus:ring-violet-500"
              >
                <option value="">All sources</option>
                <option value="manual">Manual</option>
                <option value="csv">CSV</option>
                <option value="pdf">PDF</option>
                <option value="stripe">Stripe</option>
              </select>
            </div>
            {(dateFrom || dateTo || source) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setDateFrom("");
                  setDateTo("");
                  setSource("");
                  setPage(1);
                }}
              >
                Clear filters
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading && (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex gap-4 items-center">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-4 flex-1" />
                  <Skeleton className="h-5 w-20 rounded-full" />
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-5 w-14 rounded-full" />
                  <Skeleton className="h-4 w-20" />
                </div>
              ))}
            </div>
          )}
          {error && !isLoading && (
            <div className="p-8 text-center">
              <p className="text-red-500 font-medium">Failed to load transactions.</p>
              <p className="text-sm text-slate-500 mt-1">Check your connection and try refreshing.</p>
            </div>
          )}
          {!isLoading && !error && (!data || data.length === 0) ? (
            <div className="p-10 text-center text-slate-500">
              <p className="font-medium">No transactions found.</p>
              <p className="text-sm mt-1">
                Import a CSV or add one manually above.
              </p>
            </div>
          ) : !isLoading && !error && data && data.length > 0 ? (
            <>
              <table className="w-full text-sm">
                <thead className="border-b bg-slate-50">
                  <tr>
                    {[
                      "Date",
                      "Description",
                      "Category",
                      "Amount",
                      "Source",
                      "Status",
                      "",
                    ].map((h) => (
                      <th
                        key={h}
                        className="text-left px-4 py-3 text-xs
                                   font-medium text-slate-500
                                   uppercase tracking-wide"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.map((tx) => (
                    <tr
                      key={tx.id}
                      className="hover:bg-slate-50 transition-colors"
                    >
                      <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                        {tx.date}
                      </td>
                      <td className="px-4 py-3 text-slate-800 max-w-xs">
                        <p className="truncate font-medium">
                          {tx.description}
                        </p>
                        {tx.notes && (
                          <p className="text-xs text-slate-400 truncate">
                            {tx.notes}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs font-medium ${getCategoryType(tx.category_id) === "income"
                            ? "bg-green-100 text-green-700"
                            : "bg-slate-100 text-slate-600"
                            }`}
                        >
                          {getCategoryName(tx.category_id)}
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span
                          className={`font-semibold ${tx.amount >= 0
                            ? "text-green-600"
                            : "text-red-500"
                            }`}
                        >
                          {tx.amount >= 0 ? "+" : "-"}
                          {fmt(tx.amount)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs
                                      font-medium ${SOURCE_COLOURS[tx.source] ??
                            "bg-slate-100 text-slate-600"
                            }`}
                        >
                          {tx.source}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {tx.is_confirmed ? (
                          <span className="flex items-center gap-1
                                           text-xs text-green-600">
                            <CheckCircle size={12} />
                            Confirmed
                          </span>
                        ) : (
                          <span className="flex items-center gap-1
                                           text-xs text-amber-500">
                            <Clock size={12} />
                            {tx.confidence != null
                              ? `${(tx.confidence * 100).toFixed(0)}% confident`
                              : "Pending"}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleDelete(tx.id)}
                          className="p-1.5 rounded hover:bg-red-50"
                          title="Delete"
                        >
                          <Trash2 size={14} className="text-slate-400 hover:text-red-500" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Pagination */}
              <div className="flex items-center justify-between
                              px-4 py-3 border-t bg-slate-50">
                <p className="text-xs text-slate-500">
                  Page {page}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 1}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(data?.length ?? 0) < 50}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}