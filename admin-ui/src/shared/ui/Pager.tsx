export type PaginationMeta = {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_prev: boolean;
  has_next: boolean;
};

type Props = {
  pagination: PaginationMeta | null;
  onPageChange: (page: number) => void;
};

export function Pager({ pagination, onPageChange }: Props) {
  if (!pagination || pagination.total_pages <= 1) {
    return null;
  }
  return (
    <div className="pager-row">
      <button
        className="btn btn-secondary"
        type="button"
        disabled={!pagination.has_prev}
        onClick={() => onPageChange(Math.max(1, pagination.page - 1))}
      >
        Prev
      </button>
      <span className="pager-meta">
        Page {pagination.page}/{pagination.total_pages} | total {pagination.total}
      </span>
      <button
        className="btn btn-secondary"
        type="button"
        disabled={!pagination.has_next}
        onClick={() => onPageChange(Math.min(pagination.total_pages, pagination.page + 1))}
      >
        Next
      </button>
    </div>
  );
}
