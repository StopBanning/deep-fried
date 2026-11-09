import type React from 'react';
import { useEffect, useState } from 'react';
import { NotebookPen } from 'lucide-react';
import { Card } from '../common';
import { ReportMarkdownBody } from '../report/ReportMarkdownBody';
import { portfolioApi } from '../../api/portfolio';
import type { PortfolioDeskNote } from '../../types/portfolio';

/** Desk mode: the latest note written by the assistant (scripts/desk.py note). Hidden when there is none. */
export const DeskNoteCard: React.FC<{ refreshKey?: number }> = ({ refreshKey = 0 }) => {
  const [note, setNote] = useState<PortfolioDeskNote | null>(null);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await portfolioApi.getDeskNote();
        if (alive) setNote(data);
      } catch {
        if (alive) setNote(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  if (!note?.available || !note.markdown) return null;
  return (
    <section>
      <Card padding="md">
        <button type="button" className="flex w-full items-center justify-between gap-2 text-left" onClick={() => setOpen((v) => !v)}>
          <span className="flex items-center gap-2">
            <NotebookPen className="h-4 w-4 text-cyan" />
            <span className="text-sm font-semibold text-foreground">Desk note</span>
            <span className="text-[11px] text-secondary">{note.date}</span>
          </span>
          <span className="text-[11px] text-secondary">{open ? 'Hide' : 'Show'}</span>
        </button>
        {open ? <ReportMarkdownBody content={note.markdown} className="mt-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2 [&_li]:my-1 [&_li>p]:m-0" testId="desk-note-body" /> : null}
      </Card>
    </section>
  );
};

export default DeskNoteCard;
