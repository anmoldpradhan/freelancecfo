"use client";

import useSWR from "swr";
import { tax } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";

function fmt(n: number) {
  return `£${n.toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export default function TaxPage() {
  const { data, error } = useSWR("tax-breakdown", tax.breakdown);

  if (error) return <p className="text-red-500">Failed to load tax data.</p>;
  if (!data) return <p className="text-slate-500">Loading...</p>;

  const pieData = [
    {
      name: "Income Tax (20%)",
      value: data.income_tax.basic_rate_20pct,
      colour: "#7c3aed",
    },
    {
      name: "Income Tax (40%)",
      value: data.income_tax.higher_rate_40pct,
      colour: "#a855f7",
    },
    {
      name: "NI Class 2",
      value: data.national_insurance.class2_flat_rate,
      colour: "#06b6d4",
    },
    {
      name: "NI Class 4 (9%)",
      value: data.national_insurance.class4_9pct_band,
      colour: "#0284c7",
    },
  ].filter((d) => d.value > 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Tax Estimate
        </h1>
        <p className="text-slate-500 text-sm">
          {data.tax_year} · Based on your YTD transactions
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { label: "Net Profit", value: data.income_summary.net_profit },
          { label: "Total Tax Due", value: data.total_liability },
          {
            label: "Effective Rate",
            value: null,
            text: `${data.effective_rate_pct.toFixed(1)}%`,
          },
        ].map(({ label, value, text }) => (
          <Card key={label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-slate-500">
                {label}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-slate-900">
                {text ?? fmt(value!)}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Breakdown table */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Detailed Breakdown</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm font-semibold text-slate-600 uppercase
                            tracking-wide pb-1 border-b">
              Income
            </div>
            {[
              ["Gross Income", data.income_summary.gross_income],
              ["Allowable Expenses", -data.income_summary.allowable_expenses],
              ["Net Profit", data.income_summary.net_profit],
            ].map(([label, val]) => (
              <div key={label as string}
                   className="flex justify-between text-sm">
                <span className="text-slate-600">{label}</span>
                <span className="font-medium">{fmt(val as number)}</span>
              </div>
            ))}

            <div className="text-sm font-semibold text-slate-600 uppercase
                            tracking-wide pb-1 border-b mt-4">
              Income Tax
            </div>
            {[
              ["Personal Allowance", data.income_tax.personal_allowance],
              ["Basic Rate (20%)", data.income_tax.basic_rate_20pct],
              ["Higher Rate (40%)", data.income_tax.higher_rate_40pct],
              ["Additional Rate (45%)", data.income_tax.additional_rate_45pct],
            ].map(([label, val]) => (
              <div key={label as string}
                   className="flex justify-between text-sm">
                <span className="text-slate-600">{label}</span>
                <span className="font-medium">{fmt(val as number)}</span>
              </div>
            ))}

            <div className="text-sm font-semibold text-slate-600 uppercase
                            tracking-wide pb-1 border-b mt-4">
              National Insurance
            </div>
            {[
              ["Class 2 (flat)", data.national_insurance.class2_flat_rate],
              ["Class 4 (9%)", data.national_insurance.class4_9pct_band],
              ["Class 4 (2%)", data.national_insurance.class4_2pct_above_upper],
            ].map(([label, val]) => (
              <div key={label as string}
                   className="flex justify-between text-sm">
                <span className="text-slate-600">{label}</span>
                <span className="font-medium">{fmt(val as number)}</span>
              </div>
            ))}

            <div className="flex justify-between text-sm font-bold
                            border-t pt-3 mt-2">
              <span>Total Liability</span>
              <span className="text-violet-600">
                {fmt(data.total_liability)}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Pie chart + Payments on account */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Tax Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    dataKey="value"
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={index} fill={entry.colour} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => typeof v === "number" ? fmt(v) : v} />
                  <Legend
                    formatter={(value) => (
                      <span className="text-xs">{value}</span>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card className="border-amber-200 bg-amber-50">
            <CardHeader className="pb-2">
              <CardTitle className="text-base text-amber-800">
                ⏰ Payments on Account
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-amber-900">
              <div className="flex justify-between">
                <span>31 January</span>
                <span className="font-semibold">
                  {fmt(data.payments_on_account.january_31)}
                </span>
              </div>
              <div className="flex justify-between">
                <span>31 July</span>
                <span className="font-semibold">
                  {fmt(data.payments_on_account.july_31)}
                </span>
              </div>
              <p className="text-xs text-amber-700 pt-1">
                {data.payments_on_account.note}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}