"use client";

import { useState } from "react";
import useSWR from "swr";
import { invoices, type Invoice } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Plus, Download, Send, CheckCircle } from "lucide-react";

const STATUS_COLOURS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  sent: "bg-blue-100 text-blue-700",
  paid: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  void: "bg-slate-200 text-slate-500",
};

function fmt(n: number) {
  return `£${n.toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export default function InvoicesPage() {
  const { data, mutate } = useSWR("invoices", () => invoices.list());
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // Create invoice form state
  const [form, setForm] = useState({
    client_name: "",
    client_email: "",
    description: "",
    quantity: "1",
    unit_price: "",
    tax_rate: "20",
    due_date: "",
    send_immediately: false,
  });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await invoices.create({
        client_name: form.client_name,
        client_email: form.client_email || undefined,
        line_items: [
          {
            description: form.description,
            quantity: parseFloat(form.quantity),
            unit_price: parseFloat(form.unit_price),
          },
        ],
        tax_rate: parseFloat(form.tax_rate),
        due_date: form.due_date || undefined,
        send_immediately: form.send_immediately,
      });
      await mutate();
      setOpen(false);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  };

  const markPaid = async (id: string) => {
    await invoices.updateStatus(id, "paid");
    await mutate();
  };

  const sendInvoice = async (id: string) => {
    await invoices.send(id);
    await mutate();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Invoices</h1>
          <p className="text-slate-500 text-sm">
            {data?.length ?? 0} invoice{data?.length !== 1 ? "s" : ""}
          </p>
        </div>

        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button className="bg-violet-600 hover:bg-violet-700">
              <Plus size={16} className="mr-2" />
              New Invoice
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>Create Invoice</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              {[
                { label: "Client Name", key: "client_name", required: true },
                { label: "Client Email", key: "client_email", type: "email" },
                { label: "Description", key: "description", required: true },
                { label: "Quantity", key: "quantity", type: "number" },
                { label: "Unit Price (£)", key: "unit_price",
                  type: "number", required: true },
                { label: "VAT Rate (%)", key: "tax_rate", type: "number" },
                { label: "Due Date", key: "due_date", type: "date" },
              ].map(({ label, key, type = "text", required }) => (
                <div key={key} className="space-y-1">
                  <Label>{label}</Label>
                  <Input
                    type={type}
                    value={form[key as keyof typeof form] as string}
                    onChange={(e) =>
                      setForm({ ...form, [key]: e.target.value })
                    }
                    required={required}
                    step={type === "number" ? "0.01" : undefined}
                  />
                </div>
              ))}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="send_now"
                  checked={form.send_immediately}
                  onChange={(e) =>
                    setForm({ ...form, send_immediately: e.target.checked })
                  }
                />
                <Label htmlFor="send_now">Send email immediately</Label>
              </div>
              <Button
                type="submit"
                className="w-full bg-violet-600 hover:bg-violet-700"
                disabled={loading}
              >
                {loading ? "Creating..." : "Create Invoice"}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardContent className="p-0">
          {!data || data.length === 0 ? (
            <div className="p-8 text-center text-slate-500">
              No invoices yet. Create your first one.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b bg-slate-50">
                <tr>
                  {["Invoice", "Client", "Amount", "Due", "Status",
                    "Actions"].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 text-slate-600
                                 font-medium text-xs uppercase tracking-wide"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {data.map((inv) => (
                  <tr key={inv.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-800">
                      {inv.invoice_number}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {inv.client_name}
                    </td>
                    <td className="px-4 py-3 font-semibold">
                      {fmt(inv.total)}
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {inv.due_date ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-1 rounded-full text-xs
                                    font-medium ${STATUS_COLOURS[inv.status]}`}
                      >
                        {inv.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button
                          onClick={() =>
                            invoices.downloadPdf(
                              inv.id,
                              `${inv.invoice_number}.pdf`
                            )
                          }
                          className="p-1.5 rounded hover:bg-slate-100"
                          title="Download PDF"
                        >
                          <Download size={14} className="text-slate-500" />
                        </button>
                        {inv.status === "draft" && (
                          <button
                            onClick={() => sendInvoice(inv.id)}
                            className="p-1.5 rounded hover:bg-blue-50"
                            title="Send"
                          >
                            <Send size={14} className="text-blue-500" />
                          </button>
                        )}
                        {inv.status === "sent" && (
                          <button
                            onClick={() => markPaid(inv.id)}
                            className="p-1.5 rounded hover:bg-green-50"
                            title="Mark paid"
                          >
                            <CheckCircle
                              size={14}
                              className="text-green-500"
                            />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}