"use client";

import useSWR from "swr";
import { forecast } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
  Legend,
} from "recharts";
import { AlertTriangle, CheckCircle, TrendingUp } from "lucide-react";

function fmt(n: number) {
  return `£${n.toLocaleString("en-GB", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

const ALERT_STYLES: Record<string, string> = {
  negative_balance:
    "border-red-200 bg-red-50 text-red-700",
  low_balance:
    "border-amber-200 bg-amber-50 text-amber-700",
  "": "border-slate-100",
};

export default function ForecastPage() {
  const { data: flowData, error: flowError } =
    useSWR("cashflow-full", forecast.cashflow);
  const { data: vatData } = useSWR("vat-full", forecast.vat);

  const chartData = flowData?.weeks.map((w) => ({
    week: w.week_start.slice(5),       // MM-DD
    Income: parseFloat(w.projected_income.toFixed(2)),
    Expenses: parseFloat(w.projected_expenses.toFixed(2)),
    Balance: parseFloat(w.cumulative_balance.toFixed(2)),
    alert: w.alert,
  })) ?? [];

  const negativeWeeks = flowData?.weeks.filter(
    (w) => w.alert === "negative_balance"
  ).length ?? 0;

  const vatPct = vatData?.percentage_used ?? 0;
  const vatBarColour =
    vatPct >= 95
      ? "bg-red-500"
      : vatPct >= 80
      ? "bg-amber-400"
      : "bg-green-500";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Cash Flow Forecast
        </h1>
        <p className="text-slate-500 text-sm">
          13-week projection based on your last 90 days
        </p>
      </div>

      {/* Summary banner */}
      {flowData && (
        <div
          className={`rounded-lg border p-4 text-sm font-medium ${
            negativeWeeks > 0
              ? "bg-red-50 border-red-200 text-red-700"
              : "bg-green-50 border-green-200 text-green-700"
          }`}
        >
          {negativeWeeks > 0 ? (
            <span className="flex items-center gap-2">
              <AlertTriangle size={16} />
              {flowData.summary}
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <CheckCircle size={16} />
              {flowData.summary}
            </span>
          )}
        </div>
      )}

      {/* Averages */}
      {flowData && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            {
              label: "Avg Weekly Income",
              value: flowData.averages.weekly_income,
              colour: "text-green-600",
            },
            {
              label: "Avg Weekly Expenses",
              value: flowData.averages.weekly_expenses,
              colour: "text-red-500",
            },
            {
              label: "Avg Weekly Net",
              value: flowData.averages.weekly_net,
              colour:
                flowData.averages.weekly_net >= 0
                  ? "text-violet-600"
                  : "text-red-600",
            },
          ].map(({ label, value, colour }) => (
            <Card key={label}>
              <CardContent className="pt-4">
                <p className="text-xs text-slate-500">{label}</p>
                <p className={`text-xl font-bold mt-1 ${colour}`}>
                  {value >= 0 ? "+" : ""}
                  {fmt(value)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Cumulative balance area chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Cumulative Balance Projection
          </CardTitle>
        </CardHeader>
        <CardContent>
          {flowError ? (
            <p className="text-red-500 text-sm">
              Failed to load forecast data.
            </p>
          ) : !flowData ? (
            <p className="text-slate-500 text-sm">Loading...</p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart
                data={chartData}
                margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient
                    id="balanceGradient"
                    x1="0" y1="0" x2="0" y2="1"
                  >
                    <stop
                      offset="5%"
                      stopColor="#7c3aed"
                      stopOpacity={0.2}
                    />
                    <stop
                      offset="95%"
                      stopColor="#7c3aed"
                      stopOpacity={0}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="week"
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => `£${v}`}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  formatter={(v: number) => fmt(v)}
                  labelStyle={{ color: "#475569" }}
                />
                {/* Zero line — going below this is bad */}
                <ReferenceLine
                  y={0}
                  stroke="#ef4444"
                  strokeDasharray="4 4"
                  label={{
                    value: "£0",
                    position: "right",
                    fontSize: 11,
                    fill: "#ef4444",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="Balance"
                  stroke="#7c3aed"
                  strokeWidth={2}
                  fill="url(#balanceGradient)"
                  dot={(props) => {
                    const { cx, cy, payload } = props;
                    if (payload.alert === "negative_balance") {
                      return (
                        <circle
                          key={cx}
                          cx={cx}
                          cy={cy}
                          r={5}
                          fill="#ef4444"
                          stroke="#fff"
                          strokeWidth={2}
                        />
                      );
                    }
                    return (
                      <circle
                        key={cx}
                        cx={cx}
                        cy={cy}
                        r={3}
                        fill="#7c3aed"
                        stroke="#fff"
                        strokeWidth={1.5}
                      />
                    );
                  }}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
          <p className="text-xs text-slate-400 mt-2 text-right">
            Red dots = negative balance weeks ·
            Confidence decays further out
          </p>
        </CardContent>
      </Card>

      {/* Income vs Expenses bar chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Weekly Income vs Expenses
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart
              data={chartData}
              margin={{ top: 5, right: 10, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="week"
                tick={{ fontSize: 11 }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => `£${v}`}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip formatter={(v: number) => fmt(v)} />
              <Legend />
              <Area
                type="monotone"
                dataKey="Income"
                stroke="#22c55e"
                fill="#dcfce7"
                strokeWidth={2}
              />
              <Area
                type="monotone"
                dataKey="Expenses"
                stroke="#f87171"
                fill="#fee2e2"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Weekly breakdown table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Week-by-Week Detail</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-slate-50">
                <tr>
                  {[
                    "Week",
                    "Projected Income",
                    "Projected Expenses",
                    "Net",
                    "Cumulative Balance",
                    "Confidence",
                  ].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 text-xs
                                 font-medium text-slate-500
                                 uppercase tracking-wide whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {flowData?.weeks.map((w, i) => (
                  <tr
                    key={i}
                    className={`transition-colors ${
                      w.alert === "negative_balance"
                        ? "bg-red-50"
                        : w.alert === "low_balance"
                        ? "bg-amber-50"
                        : "hover:bg-slate-50"
                    }`}
                  >
                    <td className="px-4 py-2.5 text-slate-600 whitespace-nowrap">
                      {w.week_start}
                    </td>
                    <td className="px-4 py-2.5 text-green-600 font-medium">
                      +{fmt(w.projected_income)}
                    </td>
                    <td className="px-4 py-2.5 text-red-500 font-medium">
                      -{fmt(w.projected_expenses)}
                    </td>
                    <td
                      className={`px-4 py-2.5 font-semibold ${
                        w.net >= 0 ? "text-slate-700" : "text-red-600"
                      }`}
                    >
                      {w.net >= 0 ? "+" : ""}
                      {fmt(w.net)}
                    </td>
                    <td
                      className={`px-4 py-2.5 font-semibold ${
                        w.cumulative_balance < 0
                          ? "text-red-600"
                          : "text-slate-700"
                      }`}
                    >
                      {fmt(w.cumulative_balance)}
                      {w.alert === "negative_balance" && (
                        <span className="ml-2 text-xs text-red-500">
                          ⚠️ negative
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-slate-100 rounded-full">
                          <div
                            className="h-full bg-violet-400 rounded-full"
                            style={{
                              width: `${(w.confidence * 100).toFixed(0)}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs text-slate-400">
                          {(w.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* VAT threshold card */}
      {vatData && (
        <Card
          className={
            vatData.warning_level !== "safe"
              ? "border-amber-300"
              : ""
          }
        >
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp size={16} className="text-violet-500" />
              VAT Threshold Monitor
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-slate-600">
                Rolling 12-month income
              </span>
              <span className="font-semibold">
                {fmt(vatData.rolling_12m_income)}
              </span>
            </div>

            {/* Progress bar */}
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-slate-400">
                <span>£0</span>
                <span>£90,000 threshold</span>
              </div>
              <div className="h-3 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${vatBarColour}`}
                  style={{
                    width: `${Math.min(vatPct, 100)}%`,
                  }}
                />
              </div>
              <p className="text-xs text-slate-500 text-right">
                {vatPct.toFixed(1)}% used ·{" "}
                {fmt(vatData.amount_remaining)} remaining
              </p>
            </div>

            {vatData.warning_level !== "safe" && (
              <div
                className={`text-sm rounded-lg p-3 border ${
                  vatData.warning_level === "exceeded"
                    ? "bg-red-50 border-red-200 text-red-700"
                    : "bg-amber-50 border-amber-200 text-amber-700"
                }`}
              >
                {vatData.alert_message}
                {vatData.registration_deadline_note && (
                  <p className="mt-1 font-semibold">
                    {vatData.registration_deadline_note}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}