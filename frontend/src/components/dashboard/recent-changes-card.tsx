"use client";

import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { History } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MotionList, MotionItem } from "@/components/motion";
import type { ChangeEvent } from "@/lib/api/types";

const CHANGE_LABELS: Record<string, string> = {
  created: "creado",
  updated: "actualizado",
  deleted: "eliminado",
};

export function RecentChangesCard({ changes }: { changes: ChangeEvent[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="size-4 text-purple-400" /> Cambios recientes
        </CardTitle>
      </CardHeader>
      <CardContent>
        {changes.length === 0 && (
          <p className="text-sm text-muted-foreground">Sin cambios recientes.</p>
        )}
        <MotionList className="flex flex-col divide-y divide-border">
          {changes.slice(0, 8).map((c) => (
            <MotionItem key={c.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="truncate">
                <span className="font-medium capitalize">{c.entity_type}</span>{" "}
                <Badge variant="secondary" className="align-middle text-xs">
                  {CHANGE_LABELS[c.change_type] ?? c.change_type}
                </Badge>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(c.detected_at), { addSuffix: true, locale: es })}
              </span>
            </MotionItem>
          ))}
        </MotionList>
      </CardContent>
    </Card>
  );
}
