"use client";

import { useState } from "react";
import { useCategories } from "@/lib/use-categories";
import { categories } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Plus, Tag, Lock } from "lucide-react";

export default function CategoriesPage() {
  const { categories: categoryList, mutate, loading } = useCategories();

  const [name, setName] = useState("");
  const [type, setType] = useState<"income" | "expense">("expense");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const income = categoryList.filter((c) => c.type === "income");
  const expense = categoryList.filter((c) => c.type === "expense");

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!name.trim()) {
      setError("Name is required.");
      return;
    }

    setSaving(true);
    try {
      await categories.create(name.trim(), type);
      await mutate();
      setName("");
    } catch (err: any) {
      setError(err.message ?? "Failed to create category.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Categories</h1>
        <p className="text-slate-500 text-sm">
          Manage how transactions are classified.
          System categories can't be deleted.
        </p>
      </div>

      {/* Add new category */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add Custom Category</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleAdd} className="flex flex-wrap gap-3 items-end">
            <div className="space-y-1 flex-1 min-w-[180px]">
              <Label>Name</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Courses & Training"
              />
            </div>

            <div className="space-y-1">
              <Label>Type</Label>
              <select
                value={type}
                onChange={(e) =>
                  setType(e.target.value as "income" | "expense")
                }
                className="h-9 rounded-md border border-slate-200
                           bg-white px-3 text-sm text-slate-700
                           focus:outline-none focus:ring-2
                           focus:ring-violet-500"
              >
                <option value="expense">Expense</option>
                <option value="income">Income</option>
              </select>
            </div>

            <Button
              type="submit"
              className="bg-violet-600 hover:bg-violet-700"
              disabled={saving}
            >
              <Plus size={14} className="mr-2" />
              {saving ? "Adding..." : "Add"}
            </Button>
          </form>

          {error && (
            <p className="text-sm text-red-500 mt-2">{error}</p>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Income categories */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
              Income ({income.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <p className="px-4 py-6 text-sm text-slate-400">
                Loading...
              </p>
            ) : income.length === 0 ? (
              <p className="px-4 py-6 text-sm text-slate-400">
                No income categories yet.
              </p>
            ) : (
              <ul className="divide-y">
                {income.map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center justify-between
                               px-4 py-3"
                  >
                    <div className="flex items-center gap-2">
                      <Tag size={13} className="text-green-500" />
                      <span className="text-sm text-slate-700">
                        {c.name}
                      </span>
                    </div>
                    {c.is_system ? (
                      <span
                        className="flex items-center gap-1 text-xs
                                   text-slate-400"
                      >
                        <Lock size={11} />
                        System
                      </span>
                    ) : (
                      <span
                        className="text-xs px-2 py-0.5 rounded-full
                                   bg-green-100 text-green-700"
                      >
                        Custom
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* Expense categories */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-red-400" />
              Expenses ({expense.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <p className="px-4 py-6 text-sm text-slate-400">
                Loading...
              </p>
            ) : expense.length === 0 ? (
              <p className="px-4 py-6 text-sm text-slate-400">
                No expense categories yet.
              </p>
            ) : (
              <ul className="divide-y">
                {expense.map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center justify-between
                               px-4 py-3"
                  >
                    <div className="flex items-center gap-2">
                      <Tag size={13} className="text-red-400" />
                      <span className="text-sm text-slate-700">
                        {c.name}
                      </span>
                    </div>
                    {c.is_system ? (
                      <span
                        className="flex items-center gap-1 text-xs
                                   text-slate-400"
                      >
                        <Lock size={11} />
                        System
                      </span>
                    ) : (
                      <span
                        className="text-xs px-2 py-0.5 rounded-full
                                   bg-slate-100 text-slate-600"
                      >
                        Custom
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}