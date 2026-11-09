import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DeskNoteCard } from '../DeskNoteCard';

const { getDeskNote } = vi.hoisted(() => ({ getDeskNote: vi.fn() }));
vi.mock('../../../api/portfolio', () => ({ portfolioApi: { getDeskNote } }));

describe('DeskNoteCard', () => {
  beforeEach(() => getDeskNote.mockReset());

  it('renders the latest note', async () => {
    getDeskNote.mockResolvedValueOnce({ available: true, date: '2026-11-09', markdown: '## Book\n\nUp **$120** on the day.' });
    render(<DeskNoteCard />);
    expect(await screen.findByText('Desk note')).toBeInTheDocument();
    expect(screen.getByText('2026-11-09')).toBeInTheDocument();
    expect(screen.getByText('$120')).toBeInTheDocument();
  });

  it('stays hidden with no note or on error', async () => {
    getDeskNote.mockResolvedValueOnce({ available: false });
    const { container, unmount } = render(<DeskNoteCard />);
    await waitFor(() => expect(getDeskNote).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    unmount();
    getDeskNote.mockRejectedValueOnce(new Error('down'));
    const second = render(<DeskNoteCard />);
    await waitFor(() => expect(getDeskNote).toHaveBeenCalledTimes(2));
    expect(second.container).toBeEmptyDOMElement();
  });
});
