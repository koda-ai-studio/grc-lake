"use client";
import {
  Children,
  isValidElement,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { ListPagination } from "./list-pagination";

/** Paginate an already-loaded collection without hiding its total. */
export function PaginatedCollection({
  children,
  label,
  pageSize = 8,
}: {
  children: ReactNode;
  label: string;
  pageSize?: number;
}) {
  const items = Children.toArray(children);
  const [page, setPage] = useState(0);
  const order = items
    .map((item, index) => (isValidElement(item) ? item.key : index))
    .join("|");
  useEffect(() => setPage(0), [order]);
  const current = Math.min(
    page,
    Math.max(0, Math.ceil(items.length / pageSize) - 1),
  );
  return (
    <>
      {items.slice(current * pageSize, (current + 1) * pageSize)}
      <div className="col-span-full px-4 py-3">
        <ListPagination
          label={label}
          page={current}
          total={items.length}
          pageSize={pageSize}
          onPage={setPage}
        />
      </div>
    </>
  );
}
