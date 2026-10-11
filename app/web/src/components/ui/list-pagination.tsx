"use client";
import { Button } from "@/components/ui/button";
export function ListPagination({
  label,
  page,
  total,
  pageSize,
  onPage,
}: {
  label: string;
  page: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav
      aria-label={`${label} pages`}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3 text-sm"
    >
      <span role="status" className="text-muted">
        {total ? page * pageSize + 1 : 0}–
        {Math.min((page + 1) * pageSize, total)} of {total}
      </span>
      {pages > 1 && (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            disabled={page === 0}
            onClick={() => onPage(page - 1)}
            aria-label={`Previous ${label.toLowerCase()} page`}
          >
            Previous
          </Button>
          <span className="text-xs text-muted">
            {page + 1} / {pages}
          </span>
          <Button
            size="sm"
            disabled={page + 1 >= pages}
            onClick={() => onPage(page + 1)}
            aria-label={`Next ${label.toLowerCase()} page`}
          >
            Next
          </Button>
        </div>
      )}
    </nav>
  );
}
