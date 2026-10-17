import { beforeAll, afterEach, describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, act } from '@testing-library/react';
import App from './App.jsx';

// recharts' ResponsiveContainer relies on ResizeObserver, which jsdom does
// not provide; a no-op observer is enough for rendering assertions.
beforeAll(() => {
  if (!window.ResizeObserver) {
    window.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const jsonResponse = (payload) => ({
  ok: true,
  status: 200,
  json: async () => payload,
});

const META = {
  version: '9.9.9-test',
  default_engine: 'polars-bio',
  assemblies: [],
  naming_options: [
    { key: 'UCSC-style', label: 'UCSC-style (chr1, chrX, chrM)' },
    { key: 'Ensembl-style', label: 'Ensembl-style (1, X, MT)' },
    { key: 'Keep original names', label: 'Keep original names' },
  ],
};

const dataset = (filename, format, totalRows) => ({
  filename,
  format,
  total_rows: totalRows,
  columns: ['chr', 'start', 'end'],
  preview: [{ chr: 'chr1', start: 9, end: 20 }],
  needs_mapping: false,
});

const SAMPLE = {
  query: dataset('sample-query.bed', 'bed', 20),
  annot: dataset('sample-annotation.gff3', 'gff3', 40),
};

const EXEC_RESULT = {
  stats: {
    elapsed_seconds: 0.42,
    engine: 'bedtools',
    mode: 'closest',
    join: 'left',
    matched_query_count: 12,
    query_count: 20,
    result_count: 20,
    unmatched_query_count: 8,
    match_rate: 60,
  },
  warnings: [],
  feature_filter: null,
  gene_list: ['BRCA1', 'TP53'],
  chromosome_normalization: null,
  columns: ['chr', 'start', 'end', 'has_overlap', 'gene_id'],
  preview: [
    { chr: 'chr1', start: 10, end: 20, has_overlap: true, gene_id: 'BRCA1' },
    { chr: 'chr2', start: 100, end: 150, has_overlap: false, gene_id: null },
  ],
  charts: {
    chromosome_distribution: [
      { chromosome: 'chr1', intervals: 12 },
      { chromosome: 'chr2', intervals: 8 },
    ],
    match_ratio: [
      { name: 'Matched', value: 12 },
      { name: 'Unmatched', value: 8 },
    ],
  },
};

// The two coordinate-system selects (query + annotation) are the only
// comboboxes whose first option is the 'Auto-detect' placeholder; DOM order
// puts the query select first.
const coordSelects = () =>
  screen.getAllByRole('combobox').filter(
    (s) => s.options.length === 3 && s.options[0].value === 'Auto-detect',
  );

const loadSample = async () => {
  fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
  await waitFor(() => expect(screen.getByText('sample-query.bed')).toBeTruthy());
  await waitFor(() => expect(screen.getByText('sample-annotation.gff3')).toBeTruthy());
};

describe('N2: the coordinate-system declaration is baked in at upload time', () => {
  it('changing the query coordinate system clears the dataset locally and server-side', async () => {
    const clearBodies = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url, options) => {
        const u = String(url);
        if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
        if (u === '/api/upload') {
          return Promise.resolve(jsonResponse(dataset('q.tsv', 'bed', 2)));
        }
        if (u === '/api/dataset/clear') {
          clearBodies.push(options?.body);
          return Promise.resolve(
            jsonResponse({ status: 'success', cleared: 'query', was_loaded: true }),
          );
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());

    const file = new File(['chr1\t10\t20\nchr2\t100\t150\n'], 'q.tsv', {
      type: 'text/tab-separated-values',
    });
    const fileInputs = document.querySelectorAll('input[type="file"]');
    expect(fileInputs).toHaveLength(2);
    fireEvent.change(fileInputs[0], { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText('q.tsv')).toBeTruthy());

    expect(coordSelects()).toHaveLength(2);
    fireEvent.change(coordSelects()[0], { target: { value: '1-based (GFF/GTF/VCF)' } });

    // The parsed dataset no longer belongs to the new declaration: the local
    // card is cleared and a re-upload is demanded.
    await waitFor(() => expect(screen.queryByText('q.tsv')).toBeNull());
    expect(screen.getByText(/re-upload the query file/i)).toBeTruthy();

    // The server-side copy is invalidated with the right role.
    expect(clearBodies).toEqual([JSON.stringify({ role: 'query' })]);
  });

  it('leaves the annot side untouched when the query declaration changes', async () => {
    const clearBodies = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url, options) => {
        const u = String(url);
        if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
        if (u === '/api/upload') {
          // Alternate responses by the role field in the form body.
          const role = String(options?.body?.get?.('role') ?? '');
          return Promise.resolve(
            jsonResponse(role === 'annot' ? dataset('a.tsv', 'gff3', 3) : dataset('q.tsv', 'bed', 2)),
          );
        }
        if (u === '/api/dataset/clear') {
          clearBodies.push(options?.body);
          return Promise.resolve(jsonResponse({ status: 'success', cleared: 'query', was_loaded: true }));
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());

    const fileInputs = document.querySelectorAll('input[type="file"]');
    fireEvent.change(fileInputs[0], {
      target: { files: [new File(['chr1\t10\t20\n'], 'q.tsv')] },
    });
    fireEvent.change(fileInputs[1], {
      target: { files: [new File(['chr1\t10\t20\tgene\n'], 'a.tsv')] },
    });
    await waitFor(() => expect(screen.getByText('q.tsv')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('a.tsv')).toBeTruthy());

    fireEvent.change(coordSelects()[0], { target: { value: '1-based (GFF/GTF/VCF)' } });

    await waitFor(() => expect(screen.queryByText('q.tsv')).toBeNull());
    // Only the query side was invalidated.
    expect(screen.getByText('a.tsv')).toBeTruthy();
    expect(clearBodies).toEqual([JSON.stringify({ role: 'query' })]);
  });
});

describe('N3: in-flight execute responses and execution locking', () => {
  it('locks inputs while a run is in flight, discards a stale response, and renders the fresh one', async () => {
    const executeResolvers = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        const u = String(url);
        if (u === '/api/meta') return Promise.resolve(jsonResponse(META));
        if (u === '/api/load-sample') return Promise.resolve(jsonResponse(SAMPLE));
        if (u === '/api/execute') {
          return new Promise((resolve) => executeResolvers.push(resolve));
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );

    render(<App />);
    await loadSample();

    const runBtn = screen.getByRole('button', { name: 'Run annotation' });

    // Two clicks land before React re-renders (a fast double-click): both
    // pass the isExecuting guard, so two runs are in flight and the first
    // run's response is stale by the time it arrives.
    await act(async () => {
      runBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      runBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(executeResolvers).toHaveLength(2);

    // While a run is in flight, every input is locked.
    const runningBtn = screen.getByRole('button', { name: 'Running annotation...' });
    expect(runningBtn.disabled).toBe(true);
    expect(screen.getAllByRole('combobox').every((s) => s.disabled)).toBe(true);
    document.querySelectorAll('input[type="file"]').forEach((i) => expect(i.disabled).toBe(true));
    expect(screen.getByRole('button', { name: /load sample data/i }).disabled).toBe(true);

    // The stale (first) response arrives while the newer run is still in
    // flight: it must not render and must not end the in-flight state.
    await act(async () => {
      executeResolvers[0](
        jsonResponse({ ...EXEC_RESULT, stats: { ...EXEC_RESULT.stats, mode: 'overlap', elapsed_seconds: 9.9 } }),
      );
    });
    expect(screen.queryByText(/executed in/i)).toBeNull();
    expect(screen.getByText(/no results yet/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Running annotation...' }).disabled).toBe(true);

    // The fresh (second) response arrives and renders with its own stats.
    await act(async () => {
      executeResolvers[1](jsonResponse(EXEC_RESULT));
    });
    await waitFor(() => expect(screen.getByText(/executed in 0.42s via BEDTOOLS/i)).toBeTruthy());
    expect(screen.getByText('closest / left')).toBeTruthy();
    expect(screen.getByText('12 of 20 regions')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Run annotation' }).disabled).toBe(false);
  });
});