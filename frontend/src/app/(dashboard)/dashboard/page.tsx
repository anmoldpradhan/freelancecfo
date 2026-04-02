"use client";

import useSWR from "swr";
import { useState, useEffect } from "react";
import { tax, forecast, transactions } from "@/lib/api";
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import {
    PoundSterling,
    TrendingUp,
    TrendingDown,
    AlertTriangle,
    Receipt,
} from "lucide-react";
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    Tooltip,
    ResponsiveContainer,
    Legend,
} from "recharts";

function fmt(n: number) {
    return `£${n.toLocaleString("en-GB", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}
import { useCategories } from "@/lib/use-categories";
import { PieChart, Pie, Cell } from "recharts";

export default function DashboardPage() {
    const [today, setToday] = useState("");
    useEffect(() => {
        setToday(new Date().toLocaleDateString("en-GB", {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
        }));
    }, []);
    const { getCategoryName } = useCategories();
    const { data: taxData } = useSWR("tax-estimate", tax.estimate);
    const { data: flowData } = useSWR("cashflow", forecast.cashflow);
    const { data: vatData } = useSWR("vat", forecast.vat);
    const { data: txData } = useSWR("transactions", () =>
        transactions.list({ page: 1 })
    );

    // Build last 4 weeks chart data from transactions
    const weeklyChartData = flowData?.weeks.slice(0, 4).map((w) => ({
        week: w.week_start.slice(5),  // MM-DD
        Income: w.projected_income,
        Expenses: w.projected_expenses,
    })) || [];
    // Category breakdown for chart
    const categoryTotals = (txData ?? [])
        .filter((t) => t.amount < 0)
        .reduce<Record<string, number>>((acc, t) => {
            const name = getCategoryName(t.category_id);
            acc[name] = (acc[name] ?? 0) + Math.abs(t.amount);
            return acc;
        }, {});

    const categoryChartData = Object.entries(categoryTotals)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 6)
        .map(([name, value]) => ({ name, value }));

    const CHART_COLOURS = [
        "#7c3aed", "#a855f7", "#06b6d4",
        "#0284c7", "#f59e0b", "#ef4444",
    ];
    const vatColour =
        vatData?.warning_level === "exceeded"
            ? "text-red-600 bg-red-50 border-red-200"
            : vatData?.warning_level?.startsWith("warning")
                ? "text-amber-600 bg-amber-50 border-amber-200"
                : "text-green-600 bg-green-50 border-green-200";

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-bold text-slate-900">Overview</h1>
                <p className="text-slate-500 text-sm mt-1">
                    {today}
                </p>
            </div>

            {/* KPI cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <Card>
                    <CardHeader className="flex flex-row items-center
                                  justify-between pb-2">
                        <CardTitle className="text-sm font-medium text-slate-600">
                            YTD Income
                        </CardTitle>
                        <TrendingUp className="text-green-500" size={18} />
                    </CardHeader>
                    <CardContent>
                        <p className="text-2xl font-bold text-slate-900">
                            {taxData ? fmt(taxData.gross_income) : "—"}
                        </p>
                        <p className="text-xs text-slate-500 mt-1">
                            {taxData?.tax_year} tax year
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center
                                  justify-between pb-2">
                        <CardTitle className="text-sm font-medium text-slate-600">
                            YTD Expenses
                        </CardTitle>
                        <TrendingDown className="text-red-400" size={18} />
                    </CardHeader>
                    <CardContent>
                        <p className="text-2xl font-bold text-slate-900">
                            {taxData ? fmt(taxData.allowable_expenses) : "—"}
                        </p>
                        <p className="text-xs text-slate-500 mt-1">
                            Net profit: {taxData ? fmt(taxData.net_profit) : "—"}
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center
                                  justify-between pb-2">
                        <CardTitle className="text-sm font-medium text-slate-600">
                            Tax Liability
                        </CardTitle>
                        <Receipt className="text-violet-500" size={18} />
                    </CardHeader>
                    <CardContent>
                        <p className="text-2xl font-bold text-slate-900">
                            {taxData ? fmt(taxData.total_liability) : "—"}
                        </p>
                        <p className="text-xs text-slate-500 mt-1">
                            Set aside {taxData?.set_aside_recommended?.toFixed(1)}% of income
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center
                                  justify-between pb-2">
                        <CardTitle className="text-sm font-medium text-slate-600">
                            VAT Status
                        </CardTitle>
                        <AlertTriangle
                            className={
                                vatData?.warning_level === "safe"
                                    ? "text-green-500"
                                    : "text-amber-500"
                            }
                            size={18}
                        />
                    </CardHeader>
                    <CardContent>
                        <p className="text-2xl font-bold text-slate-900">
                            {vatData
                                ? `${vatData.percentage_used.toFixed(0)}%`
                                : "—"}
                        </p>
                        <p className="text-xs text-slate-500 mt-1">
                            of £90k VAT threshold used
                        </p>
                    </CardContent>
                </Card>
            </div>

            {/* VAT alert banner */}
            {vatData && vatData.warning_level !== "safe" && (
                <div className={`border rounded-lg p-4 text-sm ${vatColour}`}>
                    <strong>VAT Alert: </strong>
                    {vatData.alert_message}
                </div>
            )}

            {/* Cash flow chart */}
            <Card>
                <CardHeader>
                    <CardTitle className="text-base">
                        Projected Cash Flow — Next 4 Weeks
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={weeklyChartData}>
                            <XAxis dataKey="week" tick={{ fontSize: 12 }} />
                            <YAxis
                                tick={{ fontSize: 12 }}
                                tickFormatter={(v) => `£${v}`}
                            />
                            <Tooltip formatter={(v: number) => fmt(v)} />
                            <Legend />
                            <Bar dataKey="Income" fill="#7c3aed" radius={[4, 4, 0, 0]} />
                            <Bar dataKey="Expenses" fill="#e2e8f0" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                    {flowData?.summary && (
                        <p className="text-sm text-slate-600 mt-3 border-t pt-3">
                            {flowData.summary}
                        </p>
                    )}
                </CardContent>
            </Card>
            {categoryChartData.length > 0 && (
                <Card>
                    <CardHeader>
                        <CardTitle className="text-base">
                            Expenses by Category
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-center gap-8">
                            <ResponsiveContainer width={200} height={200}>
                                <PieChart>
                                    <Pie
                                        data={categoryChartData}
                                        cx="50%"
                                        cy="50%"
                                        innerRadius={55}
                                        outerRadius={85}
                                        dataKey="value"
                                    >
                                        {categoryChartData.map((_, index) => (
                                            <Cell
                                                key={index}
                                                fill={CHART_COLOURS[index % CHART_COLOURS.length]}
                                            />
                                        ))}
                                    </Pie>
                                    <Tooltip formatter={(v: number) => fmt(v)} />
                                </PieChart>
                            </ResponsiveContainer>

                            {/* Legend */}
                            <div className="flex-1 space-y-2">
                                {categoryChartData.map((entry, i) => (
                                    <div
                                        key={entry.name}
                                        className="flex items-center justify-between
                         text-sm"
                                    >
                                        <div className="flex items-center gap-2">
                                            <span
                                                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                                                style={{
                                                    background:
                                                        CHART_COLOURS[i % CHART_COLOURS.length],
                                                }}
                                            />
                                            <span className="text-slate-600 truncate max-w-[160px]">
                                                {entry.name}
                                            </span>
                                        </div>
                                        <span className="font-medium text-slate-800 ml-4">
                                            {fmt(entry.value)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </CardContent>
                </Card>
            )}
            {/* Recent transactions */}
            <Card>
                <CardHeader>
                    <CardTitle className="text-base">Recent Transactions</CardTitle>
                </CardHeader>
                <CardContent>
                    {!txData || txData.length === 0 ? (
                        <p className="text-slate-500 text-sm">
                            No transactions yet. Import a CSV or add one manually.
                        </p>
                    ) : (
                        <div className="divide-y">
                            {txData.slice(0, 8).map((tx) => (
                                <div
                                    key={tx.id}
                                    className="flex items-center justify-between py-3"
                                >
                                    <div>
                                        <p className="text-sm font-medium text-slate-800">
                                            {tx.description}
                                        </p>
                                        <p className="text-xs text-slate-400">
                                            {tx.date} · {tx.source}
                                        </p>
                                    </div>
                                    <span
                                        className={`text-sm font-semibold ${tx.amount >= 0
                                                ? "text-green-600"
                                                : "text-red-500"
                                            }`}
                                    >
                                        {tx.amount >= 0 ? "+" : ""}
                                        {fmt(tx.amount)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}