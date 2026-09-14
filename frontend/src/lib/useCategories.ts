"use client";

import useSWR from "swr";
import { listCategories } from "./traceback";
import { Category } from "./types";

export function useCategories() {
  const { data, error, isLoading } = useSWR<Category[]>("categories", listCategories);
  return { categories: data ?? [], error, isLoading };
}

export function categoryName(categories: Category[], id: string | null): string | null {
  if (!id) return null;
  return categories.find((c) => c.id === id)?.name ?? null;
}

export function categoryBySlug(categories: Category[], slug: string): Category | undefined {
  return categories.find((c) => c.slug === slug);
}
