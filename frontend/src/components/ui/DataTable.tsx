import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Icon } from "../icons";

export type Column<T> = {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Value used for sorting; the column is sortable when present. */
  sort?: (row: T) => string | number | null | undefined;
  align?: "left" | "right";
  width?: number | string;
  className?: string;
};

export type SortState = { key: string; dir: "asc" | "desc" } | null;

/**
 * Brisk-style data table. Sorting and pagination are client-side over the rows
 * given; sort can also be controlled by the page when it owns the order.
 */
export function DataTable<T>({
  columns, rows, rowKey, loading, empty, onRowClick, expanded, pageSize, sort: sortProp, onSort, defaultSort,
  selectable, selected, onSelect, rowClass, caption,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  expanded?: (row: T) => ReactNode;
  pageSize?: number;
  sort?: SortState;
  onSort?: (sort: SortState) => void;
  defaultSort?: SortState;
  selectable?: boolean;
  selected?: Set<string>;
  onSelect?: (next: Set<string>) => void;
  rowClass?: (row: T) => string;
  caption?: string;
}) {
  const [innerSort, setInnerSort] = useState<SortState>(defaultSort ?? null);
  const [page, setPage] = useState(0);
  const sort = sortProp !== undefined ? sortProp : innerSort;

  const sorted = useMemo(() => {
    if (!sort || onSort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sort) return rows;
    const get = col.sort;
    return [...rows].sort((a, b) => {
      const av = get(a); const bv = get(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, columns, sort, onSort]);

  const pages = pageSize ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1;
  const current = Math.min(page, pages - 1);
  const visible = pageSize ? sorted.slice(current * pageSize, current * pageSize + pageSize) : sorted;

  const toggleSort = (key: string) => {
    const next: SortState = !sort || sort.key !== key ? { key, dir: "asc" } : sort.dir === "asc" ? { key, dir: "desc" } : null;
    if (onSort) onSort(next); else setInnerSort(next);
    setPage(0);
  };

  const allIds = visible.map(rowKey);
  const allChecked = !!selected && allIds.length > 0 && allIds.every((id) => selected.has(id));
  const toggleAll = () => {
    if (!onSelect) return;
    const next = new Set(selected);
    allIds.forEach((id) => (allChecked ? next.delete(id) : next.add(id)));
    onSelect(next);
  };
  const toggleOne = (id: string) => {
    if (!onSelect) return;
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    onSelect(next);
  };
  const span = columns.length + (selectable ? 1 : 0);

  return (
    <>
      <div className="table-wrap">
        <table className="table">
          {caption ? <caption className="sr-only">{caption}</caption> : null}
          <thead>
            <tr>
              {selectable ? <th className="th-check"><input type="checkbox" className="checkbox" checked={allChecked} onChange={toggleAll} aria-label="Select all rows" /></th> : null}
              {columns.map((col) => {
                const dir = sort?.key === col.key ? sort.dir : null;
                return (
                  <th key={col.key} className={`${col.align === "right" ? "num" : ""} ${col.className || ""}`} style={col.width ? { width: col.width } : undefined}
                    aria-sort={col.sort ? (dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none") : undefined}>
                    {col.sort ? (
                      <button type="button" className="th-sort" onClick={() => toggleSort(col.key)}>
                        {col.header}
                        <Icon name={dir === "asc" ? "sort-asc" : dir === "desc" ? "sort-desc" : "sort"} size={13} />
                      </button>
                    ) : col.header}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading ? Array.from({ length: 4 }, (_, i) => (
              <tr key={`sk-${i}`}>
                {selectable ? <td /> : null}
                {columns.map((col, c) => <td key={col.key}><span className="sk" style={{ width: c === 0 ? "70%" : "50%" }} /></td>)}
              </tr>
            )) : null}
            {!loading && !visible.length ? <tr><td colSpan={span} style={{ padding: 0 }}>{empty}</td></tr> : null}
            {!loading ? visible.map((row) => {
              const id = rowKey(row);
              const detail = expanded?.(row);
              return (
                <Fragment key={id}>
                  <tr className={`${onRowClick ? "clickable" : ""} ${selected?.has(id) ? "selected" : ""} ${rowClass?.(row) || ""}`}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}>
                    {selectable ? (
                      <td className="td-check" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" className="checkbox" checked={!!selected?.has(id)} onChange={() => toggleOne(id)} aria-label="Select row" />
                      </td>
                    ) : null}
                    {columns.map((col) => <td key={col.key} className={`${col.align === "right" ? "num" : ""} ${col.className || ""}`}>{col.cell(row)}</td>)}
                  </tr>
                  {detail ? <tr className="row-detail"><td colSpan={span}>{detail}</td></tr> : null}
                </Fragment>
              );
            }) : null}
          </tbody>
        </table>
      </div>
      {pageSize && sorted.length > pageSize ? (
        <div className="table-foot">
          <span>Showing {current * pageSize + 1} to {Math.min(sorted.length, (current + 1) * pageSize)} of {sorted.length}</span>
          <nav className="pager" aria-label="Pages">
            <button type="button" onClick={() => setPage(current - 1)} disabled={current === 0} aria-label="Previous page"><Icon name="chevron" size={14} className="rot-180" /></button>
            {Array.from({ length: pages }, (_, i) => (
              <button type="button" key={i} aria-current={i === current ? "page" : undefined} onClick={() => setPage(i)}>{i + 1}</button>
            ))}
            <button type="button" onClick={() => setPage(current + 1)} disabled={current >= pages - 1} aria-label="Next page"><Icon name="chevron" size={14} /></button>
          </nav>
        </div>
      ) : null}
    </>
  );
}
