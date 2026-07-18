import { useMemo, useState } from "react";

export interface SortColumn<T> {
  key: string;
  label: string;
  value: (item: T) => string | number;
}

/** Lightweight client-side table sorting used across standings/leaderboard/list screens. */
export function useSortableData<T>(
  data: T[] | undefined,
  columns: SortColumn<T>[],
  defaultKey?: string,
  defaultDir: "asc" | "desc" = "asc"
) {
  const [sortKey, setSortKey] = useState<string | undefined>(defaultKey ?? columns[0]?.key);
  const [dir, setDir] = useState<"asc" | "desc">(defaultDir);

  function toggle(key: string) {
    if (key === sortKey) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setDir("asc");
    }
  }

  const sorted = useMemo(() => {
    if (!data) return [];
    const col = columns.find((c) => c.key === sortKey);
    if (!col) return data;
    const copy = [...data];
    copy.sort((a, b) => {
      const av = col.value(a);
      const bv = col.value(b);
      if (typeof av === "number" && typeof bv === "number") {
        return dir === "asc" ? av - bv : bv - av;
      }
      return dir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return copy;
  }, [data, columns, sortKey, dir]);

  return { sorted, sortKey, dir, toggle };
}
