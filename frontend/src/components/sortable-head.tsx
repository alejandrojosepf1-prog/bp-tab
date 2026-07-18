"use client";

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { TableHead } from "@/components/ui/table";
import { cn } from "@/lib/utils";

export function SortableHead({
  label,
  columnKey,
  activeKey,
  dir,
  onSort,
  className,
}: {
  label: string;
  columnKey: string;
  activeKey?: string;
  dir: "asc" | "desc";
  onSort: (key: string) => void;
  className?: string;
}) {
  const isActive = activeKey === columnKey;
  const Icon = isActive ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;

  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        className={cn(
          "flex items-center gap-1 text-xs font-medium uppercase tracking-wide hover:text-foreground transition-colors",
          isActive ? "text-foreground" : "text-muted-foreground"
        )}
      >
        {label}
        <Icon className="size-3" />
      </button>
    </TableHead>
  );
}
