import useSWR from "swr";
import { categories, type Category } from "./api";

export function useCategories() {
  const { data, mutate, error } = useSWR("categories", categories.list);

  // Build a lookup map: id → category object
  const categoryMap = new Map<string, Category>(
    (data ?? []).map((c) => [c.id, c])
  );

  const getCategoryName = (id: string | null): string => {
    if (!id) return "Uncategorised";
    return categoryMap.get(id)?.name ?? "Uncategorised";
  };

  const getCategoryType = (id: string | null): string => {
    if (!id) return "expense";
    return categoryMap.get(id)?.type ?? "expense";
  };

  return {
    categories: data ?? [],
    categoryMap,
    getCategoryName,
    getCategoryType,
    mutate,
    error,
    loading: !data && !error,
  };
}