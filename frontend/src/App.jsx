import React, { useState, useEffect, useRef } from 'react';
import { formatCitation, formatCitationShort, copyCitation } from './citation';
import { 
  Dna, 
  Upload, 
  Download, 
  CheckCircle2, 
  AlertCircle, 
  Clock, 
  Filter, 
  Check, 
  Copy, 
  BookOpen, 
  HelpCircle,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  Tooltip, 
  ResponsiveContainer, 
  PieChart, 
  Pie, 
  Cell 
} from 'recharts';

// ---------------------------------------------------------------------------
// Scientific report rendering (Task 14.3)
//
// The backend returns structured `warnings`, `chromosome_normalization` and
// `feature_filter` from the shared execution service. These helpers surface
// them with the existing visual vocabulary (amber alerts, slate captions,
// mono identifier text). Identifiers are rendered verbatim.
// ---------------------------------------------------------------------------

const ID_DETAIL_LIMIT = 20;

function namingLabel(meta, key) {
  const option = meta?.naming_options?.find(n => n.key === key);
  return option?.label || key;
}

function assemblyLabel(meta, id) {
  const match = meta?.assemblies?.find(a => a.id === id);
  return match?.display_label || id;
}

function identifierList(entries) {
  const shown = entries.slice(0, ID_DETAIL_LIMIT)
    .map(([name, count]) => `${name} (${Number(count).toLocaleString()} rows)`);
  if (entries.length > ID_DETAIL_LIMIT) {
    shown.push(`... and ${(entries.length - ID_DETAIL_LIMIT).toLocaleString()} more`);
  }
  return shown.join(', ');
}

function IdentifierDetails({ label, data, naming, source }) {
  if (!data) return null;
  const renames = Object.entries(data.renames || {});
  const unknown = Object.entries(data.unknown || {});
  const noAlias = Object.entries(data.no_alias_for_target || {});
  const collapses = Object.entries(data.collapses || {});
  if (!renames.length && !unknown.length && !noAlias.length && !collapses.length) {
    return null;
  }
  return (
    <div className="text-[11px] text-slate-600 flex flex-col gap-0.5">
      <span className="font-bold text-slate-700">{label}</span>
      {renames.length > 0 && (
        <div>
          <span>Normalized: </span>
          <code className="font-mono">
            {renames.slice(0, ID_DETAIL_LIMIT).map(([from, to]) => `${from} \u2192 ${to}`).join(', ')}
            {renames.length > ID_DETAIL_LIMIT ? ` ... and ${renames.length - ID_DETAIL_LIMIT} more` : ''}
          </code>
        </div>
      )}
      {unknown.length > 0 && (
        <div>
          <span>Not recognized in {source}: </span>
          <code className="font-mono">{identifierList(unknown)}</code>
        </div>
      )}
      {noAlias.length > 0 && (
        <div>
          <span>Recognized, but no verified name is available in {naming}: </span>
          <code className="font-mono">{identifierList(noAlias)}</code>
        </div>
      )}
      {collapses.length > 0 && (
        <div>
          <span>Multiple input names normalized to the same output name: </span>
          <code className="font-mono">
            {collapses.map(([output, sources]) => `${sources.join(', ')} \u2192 ${output}`).join('; ')}
          </code>
        </div>
      )}
    </div>
  );
}

function ChromosomeNormalizationReport({ report, meta }) {
  if (!report) return null;
  const naming = namingLabel(meta, report.target);
  const assembly = report.assembly ? assemblyLabel(meta, report.assembly) : null;
  const source = assembly || report.registry_name;
  const tables = [
    { label: 'Query', data: report.coord_report },
    { label: 'Annotation', data: report.annot_report },
  ];
  const unresolved = tables.some(t => t.data?.unresolved_identifiers > 0);
  const merged = tables.some(t => Object.keys(t.data?.collapses || {}).length > 0);
  const hasDetails = tables.some(t =>
    Object.keys(t.data?.renames || {}).length ||
    Object.keys(t.data?.unknown || {}).length ||
    Object.keys(t.data?.no_alias_for_target || {}).length ||
    Object.keys(t.data?.collapses || {}).length);

  return (
    <div className="border border-slate-200 rounded-lg p-3.5 bg-slate-50/30 flex flex-col gap-2">
      <span className="text-xs font-bold text-slate-700">Chromosome normalization</span>
      <p className="text-[11px] text-slate-500">
        Chromosome naming: <strong>{naming}</strong>
        {assembly
          ? <> · Genome assembly: <strong>{assembly}</strong></>
          : <> · <strong>{report.registry_name}</strong></>}. Coordinates are unchanged.
      </p>
      {tables.map(t => (
        <p key={t.label} className="text-[11px] text-slate-600">
          <strong>{t.label}</strong>: {t.data?.resolved_changed_identifiers ?? 0} names normalized, {t.data?.resolved_unchanged_identifiers ?? 0} already in this naming, {t.data?.unresolved_identifiers ?? 0} not normalized.
        </p>
      ))}
      {unresolved && (
        <p className="text-[11px] text-amber-800 font-medium">
          Some chromosome names could not be normalized and were left as provided.
        </p>
      )}
      {merged && (
        <p className="text-[11px] text-[#006FB7] font-medium">
          Some input chromosome names were normalized to the same output name.
        </p>
      )}
      {hasDetails && (
        <div className="flex flex-col gap-2 pt-2 border-t border-slate-200">
          {tables.map(t => (
            <IdentifierDetails
              key={t.label}
              label={t.label}
              data={t.data}
              naming={naming}
              source={source}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Sentinel end-column choice for single-position inputs (old Streamlit
// behaviour: a custom mapped file may have no end column; then each interval
// is a 1-length position). It maps to a null end_col at the API boundary.
const NO_END_COLUMN = 'None (single positions)';

export default function App() {
  // App Metadata & Engines
  const [meta, setMeta] = useState(null);
  
  // File states
  const [queryData, setQueryData] = useState(null);
  const [annotData, setAnnotData] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  // Review finding N2: bumping a side's upload key remounts its file input,
  // so the browser's file picker cannot silently reuse the invalidated file
  // on re-upload.
  const [queryUploadKey, setQueryUploadKey] = useState(0);
  const [annotUploadKey, setAnnotUploadKey] = useState(0);

  // Configuration Parameters matching original Streamlit app exactly
  const [engine, setEngine] = useState('bedtools');
  const [mode, setMode] = useState('overlap');
  const [join, setJoin] = useState('left');
  
  // Input Options
  const [coordSystem, setCoordSystem] = useState('Auto-detect');
  const [annotSystem, setAnnotSystem] = useState('Auto-detect');
  const [genomeAssembly, setGenomeAssembly] = useState('Auto-detect');
  // Must be one of meta.naming_options values ('Keep original names' means
  // no normalization, matching the Streamlit default). Sending the label
  // ('Ensembl names') with no assembly would be rejected by the backend.
  const [chrHandling, setChrHandling] = useState('Keep original names');
  
  // Advanced options (collapsed accordion)
  const [showAdvanced, setShowAdvanced] = useState(false);
  const selectedAssemblyInfo = meta?.assemblies?.find(a => a.id === genomeAssembly);
  const [useStrand, setUseStrand] = useState(false);
  const [minOverlap, setMinOverlap] = useState(0.0);
  const [selectedFeatures, setSelectedFeatures] = useState(['gene']);

  // Execution & Results
  const [isExecuting, setIsExecuting] = useState(false);
  // Review finding N3: every invalidating event (and each run start) bumps
  // this generation; an /api/execute response only lands if its generation
  // still matches, so a stale run can never resurrect results for a newer
  // configuration. activeExecGeneration tracks the newest run started, so a
  // superseded run clearing isExecuting cannot re-enable the button while a
  // newer run is still in flight.
  const runGeneration = useRef(0);
  const activeExecGeneration = useRef(0);
  const [execResult, setExecResult] = useState(null);
  const [resultFilter, setResultFilter] = useState('all'); // 'all', 'matched', 'unmatched'
  const [statusMessage, setStatusMessage] = useState(null);
  const [citationStatus, setCitationStatus] = useState('idle'); // 'idle' | 'copied' | 'error'
  const [geneCopyStatus, setGeneCopyStatus] = useState('idle'); // 'idle' | 'copied' | 'error'

  // Custom column mapping modal
  const [mappingRequired, setMappingRequired] = useState(false);
  const [chrCol, setChrCol] = useState('');
  const [startCol, setStartCol] = useState('');
  const [endCol, setEndCol] = useState('');

  // Review finding F5: a new upload or any configuration change invalidates
  // the currently displayed results, so a stale table can never appear to
  // belong to the new configuration.
  const clearResults = () => {
    runGeneration.current += 1;
    setExecResult(null);
    setResultFilter('all');
  };

  // Review finding N2: the declared coordinate system is baked into the
  // parsed table at upload time (known formats) or at mapping time (custom
  // tables). Changing the declaration afterwards therefore invalidates the
  // stored dataset for that side, locally and on the server, and forces a
  // re-upload under the new declaration instead of silently re-running the
  // stale, already-normalized table.
  const invalidateDataset = (role) => {
    const loaded = role === 'query' ? queryData : annotData;
    if (!loaded) return;
    if (role === 'query') {
      setQueryData(null);
      setMappingRequired(false);
      setQueryUploadKey((k) => k + 1);
    } else {
      setAnnotData(null);
      setAnnotUploadKey((k) => k + 1);
    }
    setStatusMessage({
      type: 'info',
      text: `Coordinate system changed. Re-upload the ${role} file so it is parsed under the new declaration.`,
    });
    fetch('/api/dataset/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    }).catch(() => {});
  };

  // Initial loading
  useEffect(() => {
    fetch('/api/meta')
      .then(res => res.json())
      .then(data => {
        setMeta(data);
        if (data.default_engine) setEngine(data.default_engine);
      })
      .catch(err => console.error("Could not fetch metadata:", err));
  }, []);

  // Handle Sample Loading
  const handleLoadSample = async () => {
    setIsUploading(true);
    clearResults();
    setStatusMessage({ type: 'info', text: 'Loading bundled genomic sample datasets...' });
    try {
      const formData = new FormData();
      formData.append('sample_id', 'gene_overlap');
      const res = await fetch('/api/load-sample', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        setQueryData(data.query);
        setAnnotData(data.annot);
        setMappingRequired(false);
        setStatusMessage({ type: 'success', text: `Sample dataset loaded successfully (${data.query.filename} & ${data.annot.filename})` });
      } else {
        setStatusMessage({ type: 'error', text: data.detail || 'Failed to load sample dataset' });
      }
    } catch {
      setStatusMessage({ type: 'error', text: 'Network error loading sample' });
    } finally {
      setIsUploading(false);
    }
  };

  // Handle File Upload
  const handleFileUpload = async (event, role) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    clearResults();
    setStatusMessage({ type: 'info', text: `Uploading and parsing ${file.name}...` });
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('role', role);
      formData.append('coord_system', role === 'query' ? coordSystem : annotSystem);

      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        if (role === 'query') {
          setQueryData(data);
          if (data.needs_mapping) {
            setMappingRequired(true);
            setChrCol(data.columns.find(c => /chr|chrom/i.test(c)) || data.columns[0]);
            setStartCol(data.columns.find(c => /start|pos/i.test(c)) || data.columns[1]);
            setEndCol(data.columns.find(c => /end|stop/i.test(c)) || NO_END_COLUMN);
          } else {
            setMappingRequired(false);
          }
        } else {
          setAnnotData(data);
        }
        setStatusMessage({ type: 'success', text: `Parsed ${file.name} as ${data.format.toUpperCase()} (${data.total_rows.toLocaleString()} records)` });
      } else {
        setStatusMessage({ type: 'error', text: data.detail || 'Upload parsing error' });
      }
    } catch {
      setStatusMessage({ type: 'error', text: 'Network error uploading file' });
    } finally {
      setIsUploading(false);
    }
  };

  // Handle Applying Column Mapping
  const handleApplyMapping = async () => {
    try {
      const res = await fetch('/api/apply-mapping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chr_col: chrCol,
          start_col: startCol,
          end_col: endCol === NO_END_COLUMN ? null : endCol,
          coord_system: coordSystem,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setQueryData(prev => ({
          ...prev,
          total_rows: data.total_rows,
          columns: data.columns,
          preview: data.preview,
          needs_mapping: false,
        }));
        setMappingRequired(false);
        clearResults();
        setStatusMessage({ type: 'success', text: 'Column mapping applied successfully.' });
      } else {
        setStatusMessage({ type: 'error', text: data.detail || 'Mapping failed' });
      }
    } catch {
      setStatusMessage({ type: 'error', text: 'Failed to apply column mapping' });
    }
  };

  // Execute Pipeline
  const handleExecute = async () => {
    if (!queryData || !annotData) return;
    const generation = ++runGeneration.current;
    activeExecGeneration.current = generation;
    setIsExecuting(true);
    setStatusMessage({ type: 'info', text: 'Executing high-throughput annotation pipeline...' });
    try {
      const res = await fetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          engine,
          mode,
          join,
          feature_types: selectedFeatures,
          use_strand: useStrand,
          min_overlap: minOverlap,
          assembly: genomeAssembly && genomeAssembly !== 'Auto-detect' ? genomeAssembly : null,
          chr_naming: chrHandling && chrHandling !== 'Keep original names' ? chrHandling : null,
        }),
      });
      const data = await res.json();
      // Review finding N3: if an invalidating event (or a newer run) happened
      // after this run started, its response is stale and must not land.
      if (runGeneration.current !== generation) return;
      if (res.ok) {
        setExecResult(data);
        setStatusMessage({ 
          type: 'success', 
          text: `Analysis complete in ${data.stats.elapsed_seconds}s! ${data.stats.matched_query_count.toLocaleString()} of ${data.stats.query_count.toLocaleString()} regions matched.` 
        });
      } else {
        clearResults();
        setStatusMessage({ type: 'error', text: data.detail || 'Execution failed' });
      }
    } catch {
      if (runGeneration.current !== generation) return;
      clearResults();
      setStatusMessage({ type: 'error', text: 'Network execution error' });
    } finally {
      if (activeExecGeneration.current === generation) setIsExecuting(false);
    }
  };

  // Toggle Feature selection
  const toggleFeature = (ft) => {
    setSelectedFeatures(prev => 
      prev.includes(ft) ? prev.filter(f => f !== ft) : [...prev, ft]
    );
    clearResults();
  };

  // Copy Citation
  const copyCitationText = async () => {
    const ok = await copyCitation(formatCitation());
    setCitationStatus(ok ? 'copied' : 'error');
    setTimeout(() => setCitationStatus('idle'), 2500);
  };

  // Gene-list export (restored from the original Streamlit app: one name per
  // line for .txt, comma-separated for .csv, ready to paste into external
  // enrichment tools).
  const geneList = execResult?.gene_list;
  const hasGeneList = Boolean(geneList?.gene_column) && (geneList?.genes?.length || 0) > 0;

  const downloadGeneList = (kind) => {
    const genes = geneList?.genes || [];
    if (!genes.length) return;
    const text = kind === 'csv' ? genes.join(', ') : genes.join('\n');
    const mime = kind === 'csv' ? 'text/csv' : 'text/plain';
    const url = URL.createObjectURL(new Blob([text], { type: mime }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `gene_list.${kind}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  const copyGeneListText = async () => {
    const genes = geneList?.genes || [];
    if (!genes.length) return;
    const ok = await copyCitation(genes.join(', '));
    setGeneCopyStatus(ok ? 'copied' : 'error');
    setTimeout(() => setGeneCopyStatus('idle'), 2500);
  };

  // Results display filtering
  const displayedRows = execResult?.preview?.filter(row => {
    if (resultFilter === 'matched') return row.has_overlap === true;
    if (resultFilter === 'unmatched') return row.has_overlap === false;
    return true;
  }) || [];

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans text-slate-800">
      {/* Header Bar */}
      <header className="border-b border-slate-200 bg-white/95 backdrop-blur-sm sticky top-0 z-30 shadow-xs">
        <div className="w-[94%] mx-auto py-3.5 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-linear-to-tr from-[#004e92] to-[#00AEEF] flex items-center justify-center text-white shadow-md">
              <Dna className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-extrabold text-[#004e92] tracking-tight">AnnotateR</h1>
                <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-50 text-[#006FB7] border border-blue-200">
                  v{meta?.version || '0.1.0'}
                </span>
              </div>
              <p className="text-xs text-slate-500 font-medium">
                Genomic Coordinate Annotation & High-Throughput Interval Overlap Engine
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button 
              onClick={handleLoadSample}
              disabled={isUploading || isExecuting}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors cursor-pointer"
              title="Load example genomic variants and gene annotations"
            >
              Load Sample Data
            </button>
            <a 
              href="https://pyrevo.github.io/annotater/" 
              target="_blank" 
              rel="noreferrer"
              className="p-1.5 text-slate-600 hover:text-[#004e92] hover:bg-slate-100 rounded-lg transition-colors flex items-center justify-center"
              title="Documentation (pyrevo.github.io/annotater)"
              aria-label="Documentation"
            >
              <BookOpen className="w-4 h-4" />
            </a>
            <a 
              href="https://github.com/pyrevo/annotater" 
              target="_blank" 
              rel="noreferrer"
              className="p-1.5 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors flex items-center justify-center"
              title="GitHub Repository (pyrevo/annotater)"
              aria-label="GitHub Repository"
            >
              <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
              </svg>
            </a>
          </div>
        </div>
      </header>

      {/* Global Status Banner */}
      {statusMessage && (
        <div className={`px-4 py-2.5 text-xs flex items-center justify-between transition-all ${
          statusMessage.type === 'error' ? 'bg-rose-50 text-rose-800 border-b border-rose-200' :
          statusMessage.type === 'success' ? 'bg-emerald-50 text-emerald-800 border-b border-emerald-200' :
          'bg-blue-50 text-blue-800 border-b border-blue-200'
        }`}>
          <div className="w-[94%] mx-auto flex items-center gap-2">
            {statusMessage.type === 'error' ? <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" /> :
             statusMessage.type === 'success' ? <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" /> :
             <Clock className="w-4 h-4 text-blue-600 shrink-0 animate-spin" />}
            <span className="font-medium">{statusMessage.text}</span>
          </div>
        </div>
      )}

      {/* Main Workspace Layout (Edge-to-Edge: 94% Width) */}
      <div className="w-[94%] mx-auto py-6 flex-1 grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* Left Sticky Sidebar: Controls & Filters (3 Columns) - MATCHES SCREENSHOT */}
        <aside className="lg:col-span-4 xl:col-span-3 flex flex-col gap-5 sticky top-20">
          <div className="bg-white rounded-xl border border-slate-200 shadow-xs p-5 flex flex-col gap-4 text-xs">
            
            {/* Annotation Engine (Radio Buttons) */}
            <div className="flex flex-col gap-1.5">
              <label className="font-semibold text-slate-800 flex items-center gap-1">
                Annotation engine <HelpCircle className="w-3 h-3 text-slate-400" />
              </label>
              <div className="flex flex-col gap-1.5 mt-0.5">
                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                  <input
                    type="radio"
                    name="engine"
                    value="bedtools"
                    checked={engine === 'bedtools'}
                    disabled={isExecuting}
                    onChange={() => { setEngine('bedtools'); clearResults(); }}
                    className="accent-red-600 w-3.5 h-3.5"
                  />
                  <span>Bedtools</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                  <input
                    type="radio"
                    name="engine"
                    value="polars-bio"
                    checked={engine === 'polars-bio'}
                    disabled={isExecuting}
                    onChange={() => { setEngine('polars-bio'); clearResults(); }}
                    className="accent-red-600 w-3.5 h-3.5"
                  />
                  <span>Polars-Bio</span>
                </label>
              </div>
              <p className="text-[11px] text-slate-500 leading-normal mt-1">
                <strong>Bedtools</strong> — established command-line backend. <strong>Polars-Bio</strong> — dataframe-based backend.
              </p>
            </div>

            {/* Operation Mode */}
            <div className="flex flex-col gap-1.5 pt-2 border-t border-slate-100">
              <label className="font-semibold text-slate-800 flex items-center gap-1">
                Operation <HelpCircle className="w-3 h-3 text-slate-400" />
              </label>
              <select
                value={mode}
                disabled={isExecuting}
                onChange={(e) => { setMode(e.target.value); clearResults(); }}
                className="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 font-medium text-slate-700 focus:outline-hidden focus:ring-1 focus:ring-blue-500 capitalize disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <option value="overlap">Overlap</option>
                <option value="contains">Contains</option>
                <option value="within">Within</option>
                <option value="closest">Closest</option>
              </select>
              <p className="text-[11px] text-slate-500 leading-normal">
                {mode === 'overlap' && "Return annotation intervals that overlap each query interval"}
                {mode === 'contains' && "Return annotations fully contained within each query interval"}
                {mode === 'within' && "Return annotations that fully contain each query interval"}
                {mode === 'closest' && "Return the nearest annotation interval(s); all equally nearest ties are retained"}
              </p>
            </div>

            {/* Join Behavior (Radio Buttons) */}
            <div className="flex flex-col gap-1.5 pt-2 border-t border-slate-100">
              <label className="font-semibold text-slate-800 flex items-center gap-1">
                Join behavior <HelpCircle className="w-3 h-3 text-slate-400" />
              </label>
              <div className="flex flex-col gap-1.5 mt-0.5">
                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                  <input
                    type="radio"
                    name="join"
                    value="left"
                    checked={join === 'left'}
                    disabled={isExecuting}
                    onChange={() => { setJoin('left'); clearResults(); }}
                    className="accent-red-600 w-3.5 h-3.5"
                  />
                  <span>Keep all query rows (left join)</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                  <input
                    type="radio"
                    name="join"
                    value="inner"
                    checked={join === 'inner'}
                    disabled={isExecuting}
                    onChange={() => { setJoin('inner'); clearResults(); }}
                    className="accent-red-600 w-3.5 h-3.5"
                  />
                  <span>Matched rows only (inner join)</span>
                </label>
              </div>
            </div>

            {/* Section: Input Options */}
            <div className="flex flex-col gap-3 pt-3 border-t border-slate-100">
              <h3 className="text-xs font-bold text-slate-900 tracking-tight">Input options</h3>

              <div>
                <label className="font-semibold text-slate-800 flex items-center gap-1 mb-1">
                  Query coordinates <HelpCircle className="w-3 h-3 text-slate-400" />
                </label>
                <select
                  value={coordSystem}
                  disabled={isExecuting}
                  onChange={(e) => { setCoordSystem(e.target.value); clearResults(); invalidateDataset('query'); }}
                  className="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 font-medium text-slate-700 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <option value="Auto-detect">Auto-detect</option>
                  <option value="0-based (BED)">0-based (BED)</option>
                  <option value="1-based (GFF/GTF/VCF)">1-based (GFF/GTF/VCF)</option>
                </select>
              </div>

              <div>
                <label className="font-semibold text-slate-800 flex items-center gap-1 mb-1">
                  Annotation coordinates <HelpCircle className="w-3 h-3 text-slate-400" />
                </label>
                <select
                  value={annotSystem}
                  disabled={isExecuting}
                  onChange={(e) => { setAnnotSystem(e.target.value); clearResults(); invalidateDataset('annot'); }}
                  className="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 font-medium text-slate-700 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <option value="Auto-detect">Auto-detect</option>
                  <option value="0-based (BED)">0-based (BED)</option>
                  <option value="1-based (GFF/GTF/VCF)">1-based (GFF/GTF/VCF)</option>
                </select>
              </div>

              <div>
                <label className="font-semibold text-slate-800 flex items-center justify-between mb-1">
                  <span className="flex items-center gap-1">Genome assembly <HelpCircle className="w-3 h-3 text-slate-400" /></span>
                  <span className="text-[10px] text-slate-400">{meta?.assemblies?.length || 64} species catalog</span>
                </label>
                <select
                  value={genomeAssembly}
                  disabled={isExecuting}
                  onChange={(e) => { setGenomeAssembly(e.target.value); clearResults(); }}
                  className="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 font-medium text-slate-700 text-xs disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <option value="Auto-detect">Select genome assembly (Auto-detect)</option>
                  {meta?.assemblies?.map(a => (
                    <option key={a.id} value={a.id}>
                      {a.display_label}
                    </option>
                  ))}
                </select>
                {selectedAssemblyInfo && (
                  <span className="text-[10px] text-[#006FB7] font-medium block mt-1">
                    {selectedAssemblyInfo.scientific_name} · UCSC {selectedAssemblyInfo.ucsc_db}
                  </span>
                )}
              </div>

              <div>
                <label className="font-semibold text-slate-800 flex items-center gap-1 mb-1">
                  Chromosome naming <HelpCircle className="w-3 h-3 text-slate-400" />
                </label>
                <select
                  value={chrHandling}
                  disabled={isExecuting}
                  onChange={(e) => { setChrHandling(e.target.value); clearResults(); }}
                  className="w-full bg-white border border-slate-300 rounded-lg px-2.5 py-1.5 font-medium text-slate-700 text-xs disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {meta?.naming_options?.map(n => (
                    <option key={String(n.key)} value={n.key || 'Keep original names'}>
                      {n.label}
                    </option>
                  ))}
                </select>
                <span className="text-[10px] text-slate-400 block mt-1">
                  Changes sequence identifiers according to assembly registry.
                </span>
              </div>
            </div>

            {/* Section: Advanced Options Accordion */}
            <div className="border border-slate-200 rounded-lg overflow-hidden bg-slate-50/50">
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="w-full p-2.5 text-left font-semibold text-slate-800 flex items-center justify-between hover:bg-slate-100 transition-colors cursor-pointer"
              >
                <span>Advanced options</span>
                {showAdvanced ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
              </button>

              {showAdvanced && (
                <div className="p-3 bg-white border-t border-slate-200 flex flex-col gap-3">
                  <label className="flex items-start gap-2 cursor-pointer text-slate-700 leading-tight">
                    <input
                      type="checkbox"
                      checked={useStrand}
                      disabled={isExecuting}
                      onChange={(e) => { setUseStrand(e.target.checked); clearResults(); }}
                      className="rounded text-red-600 focus:ring-red-500 w-3.5 h-3.5 mt-0.5 cursor-pointer"
                    />
                    <span>Require query and annotation to have the same explicit strand</span>
                  </label>

                  {mode === 'overlap' && (
                    <div className="flex flex-col gap-1 pt-1">
                      <div className="flex justify-between items-center text-slate-700 font-semibold">
                        <span>Minimum overlap fraction</span>
                        <span className="text-red-600 font-mono text-[11px] font-bold">{minOverlap.toFixed(2)}</span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={minOverlap}
                        disabled={isExecuting}
                        onChange={(e) => { setMinOverlap(parseFloat(e.target.value)); clearResults(); }}
                        className="w-full accent-red-600 cursor-pointer disabled:cursor-not-allowed"
                      />
                    </div>
                  )}

                  <div className="flex flex-col gap-1.5 pt-1">
                    <label className="font-semibold text-slate-800">Filter by feature type (GFF/GTF)</label>
                    <div className="flex flex-wrap gap-1">
                      {['gene', 'transcript', 'exon', 'CDS', "5' UTR", "3' UTR"].map(ft => (
                        <button
                          key={ft}
                          type="button"
                          disabled={isExecuting}
                          onClick={() => toggleFeature(ft)}
                          className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed ${
                            selectedFeatures.includes(ft)
                              ? 'bg-blue-100/80 border-blue-400 text-[#004e92] font-semibold'
                              : 'bg-white border-slate-200 text-slate-600'
                          }`}
                        >
                          {ft}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* Right Main Area: Multi-Card Layout (9 Columns) */}
        <main className="lg:col-span-8 xl:col-span-9 flex flex-col gap-6">

          {/* CARD 1: Upload (Matching Screenshot 1. Upload) */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-xs p-6 flex flex-col gap-4">
            <div className="border-b border-slate-100 pb-2">
              <h2 className="text-xl font-bold text-slate-900 tracking-tight">1. Upload</h2>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Query File Card */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-bold text-slate-800">Query coordinates</span>
                <span className="text-xs text-slate-500">Choose coordinate file</span>
                <label className="border-2 border-dashed border-slate-200 hover:border-slate-300 rounded-xl p-6 flex flex-col items-center justify-center cursor-pointer transition-colors bg-slate-50/60 hover:bg-slate-100/50">
                  <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white border border-slate-200 text-xs font-semibold text-slate-700 shadow-2xs mb-2">
                    <Upload className="w-3.5 h-3.5 text-slate-500" />
                    Upload
                  </div>
                  <span className="text-xs text-slate-600 font-semibold">
                    {queryData ? queryData.filename : '100MB per file • BED, TXT, TSV, CSV, VCF'}
                  </span>
                  {queryData && (
                    <span className="text-[11px] text-emerald-600 font-medium mt-0.5">
                      ✓ {queryData.format?.toUpperCase()} ({queryData.total_rows?.toLocaleString()} rows)
                    </span>
                  )}
                  <input
                    key={`query-upload-${queryUploadKey}`}
                    type="file"
                    className="hidden"
                    disabled={isUploading || isExecuting}
                    onChange={(e) => handleFileUpload(e, 'query')}
                    accept=".bed,.vcf,.csv,.tsv,.txt"
                  />
                </label>
              </div>

              {/* Annotation File Card */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-bold text-slate-800">Annotation features</span>
                <span className="text-xs text-slate-500">Choose annotation file</span>
                <label className="border-2 border-dashed border-slate-200 hover:border-slate-300 rounded-xl p-6 flex flex-col items-center justify-center cursor-pointer transition-colors bg-slate-50/60 hover:bg-slate-100/50">
                  <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white border border-slate-200 text-xs font-semibold text-slate-700 shadow-2xs mb-2">
                    <Upload className="w-3.5 h-3.5 text-slate-500" />
                    Upload
                  </div>
                  <span className="text-xs text-slate-600 font-semibold">
                    {annotData ? annotData.filename : '100MB per file • GTF, GFF, GFF3, BED, TXT, TSV, CSV'}
                  </span>
                  {annotData && (
                    <span className="text-[11px] text-emerald-600 font-medium mt-0.5">
                      ✓ {annotData.format?.toUpperCase()} ({annotData.total_rows?.toLocaleString()} rows)
                    </span>
                  )}
                  <input
                    key={`annot-upload-${annotUploadKey}`}
                    type="file"
                    className="hidden"
                    disabled={isUploading || isExecuting}
                    onChange={(e) => handleFileUpload(e, 'annot')}
                    accept=".gff,.gff3,.gtf,.bed,.csv,.tsv,.txt"
                  />
                </label>
              </div>
            </div>

            {/* Custom Delimited mapping alert if needed */}
            {mappingRequired && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-xs flex flex-col gap-3 mt-2">
                <div className="flex items-center gap-2 text-amber-900 font-bold">
                  <AlertCircle className="w-4 h-4 text-amber-600" />
                  Custom Delimited File: Column Mapping Required
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
                  <div>
                    <label className="font-semibold block mb-1">Chromosome</label>
                    <select
                      value={chrCol}
                      disabled={isExecuting}
                      onChange={(e) => setChrCol(e.target.value)}
                      className="w-full bg-white border border-amber-300 rounded-md p-1.5 text-xs disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      {queryData?.columns?.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="font-semibold block mb-1">Start Position</label>
                    <select
                      value={startCol}
                      disabled={isExecuting}
                      onChange={(e) => setStartCol(e.target.value)}
                      className="w-full bg-white border border-amber-300 rounded-md p-1.5 text-xs disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      {queryData?.columns?.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="font-semibold block mb-1">End Position</label>
                    <select
                      value={endCol}
                      disabled={isExecuting}
                      onChange={(e) => setEndCol(e.target.value)}
                      className="w-full bg-white border border-amber-300 rounded-md p-1.5 text-xs disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      <option value={NO_END_COLUMN}>{NO_END_COLUMN}</option>
                      {queryData?.columns?.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={handleApplyMapping}
                      disabled={isExecuting}
                      className="w-full bg-amber-600 hover:bg-amber-700 text-white font-bold p-1.5 rounded-md cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      Apply Mapping
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>

          {/* CARD 2: Run Annotation (Matching Screenshot 2. Run annotation) */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-xs p-6 flex flex-col gap-3">
            <div className="border-b border-slate-100 pb-2">
              <h2 className="text-xl font-bold text-slate-900 tracking-tight">2. Run annotation</h2>
            </div>
            <div>
              <button
                onClick={handleExecute}
                disabled={!queryData || !annotData || isExecuting}
                className={`py-2 px-5 rounded-lg font-semibold text-xs transition-all cursor-pointer ${
                  !queryData || !annotData || isExecuting
                    ? 'bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed'
                    : 'bg-[#004e92] hover:bg-[#003768] text-white shadow-xs'
                }`}
              >
                {isExecuting ? 'Running annotation...' : 'Run annotation'}
              </button>
              <p className="text-xs text-slate-500 mt-2">
                {!queryData || !annotData 
                  ? 'Upload both a query file and an annotation file to enable the annotation run.' 
                  : 'Files ready. Click Run annotation to execute the relational interval match.'}
              </p>
            </div>
          </section>

          {/* CARD 3: Results (Matching Screenshot 3. Results) */}
          <section className="bg-white rounded-xl border border-slate-200 shadow-xs p-6 flex flex-col gap-4">
            <div className="border-b border-slate-100 pb-2 flex items-center justify-between">
              <h2 className="text-xl font-bold text-slate-900 tracking-tight">3. Results</h2>
              {execResult && (
                <>
                  <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                    Executed in {execResult.stats.elapsed_seconds}s via {execResult.stats.engine.toUpperCase()}
                  </span>
                  {/* Review finding N3: the results header states the exact
                      operation and join the run used, so a stale or
                      mis-attributed table is visible at a glance. */}
                  <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200 capitalize">
                    {execResult.stats.mode} / {execResult.stats.join}
                  </span>
                </>
              )}
            </div>

            {execResult ? (
              <div className="flex flex-col gap-5">
                {/* Non-fatal scientific notes (e.g. no shared identifiers) */}
                {execResult.warnings?.length > 0 && (
                  <div className="flex flex-col gap-2">
                    {execResult.warnings.map((warning, idx) => (
                      <div
                        key={idx}
                        className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-900 flex items-start gap-2"
                      >
                        <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                        <span className="font-medium">{warning.message}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Feature-filter provenance (only when it applied) */}
                {execResult.feature_filter?.applied && (
                  <p className="text-[11px] text-slate-500">
                    Using {execResult.feature_filter.used_rows.toLocaleString()} of {execResult.feature_filter.total_rows.toLocaleString()} annotation features (feature filter).
                  </p>
                )}

                {/* 4 KPI Summary Cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="bg-slate-50 border border-slate-200/80 rounded-xl p-3.5">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Query Intervals</span>
                    <span className="text-2xl font-black text-[#004e92]">{execResult.stats.query_count.toLocaleString()}</span>
                    <span className="text-[10px] text-slate-500 block mt-0.5">Input regions</span>
                  </div>
                  <div className="bg-slate-50 border border-slate-200/80 rounded-xl p-3.5">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Result Rows</span>
                    <span className="text-2xl font-black text-[#006FB7]">{execResult.stats.result_count.toLocaleString()}</span>
                    <span className="text-[10px] text-slate-500 block mt-0.5">{execResult.stats.join.toUpperCase()} join</span>
                  </div>
                  <div className="bg-slate-50 border border-slate-200/80 rounded-xl p-3.5">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Matched Coverage</span>
                    <span className="text-2xl font-black text-emerald-600">{execResult.stats.match_rate}%</span>
                    <span className="text-[10px] text-slate-500 block mt-0.5">{execResult.stats.matched_query_count.toLocaleString()} of {execResult.stats.query_count.toLocaleString()} regions</span>
                  </div>
                  <div className="bg-slate-50 border border-slate-200/80 rounded-xl p-3.5">
                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Unmatched Loci</span>
                    <span className="text-2xl font-black text-slate-500">{execResult.stats.unmatched_query_count.toLocaleString()}</span>
                    <span className="text-[10px] text-slate-500 block mt-0.5">No overlap</span>
                  </div>
                </div>

                {/* Chromosome normalization report (only when names changed) */}
                <ChromosomeNormalizationReport
                  report={execResult.chromosome_normalization}
                  meta={meta}
                />

                {/* Filterable Table */}
                <div className="border border-slate-200 rounded-lg p-3 bg-white flex flex-col gap-3">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-100 pb-2">
                    <div className="flex items-center gap-1.5">
                      <Filter className="w-4 h-4 text-slate-400" />
                      <span className="text-xs font-bold text-slate-700">Display Filter:</span>
                      <div className="flex items-center gap-1 bg-slate-100 p-0.5 rounded-lg">
                        {['all', 'matched', 'unmatched'].map(f => (
                          <button
                            key={f}
                            onClick={() => setResultFilter(f)}
                            className={`text-[11px] px-2.5 py-1 rounded-md font-medium capitalize transition-all cursor-pointer ${
                              resultFilter === f ? 'bg-white shadow-xs text-[#004e92] font-bold' : 'text-slate-600 hover:text-slate-900'
                            }`}
                          >
                            {f}
                          </button>
                        ))}
                      </div>
                    </div>
                    <span className="text-xs text-slate-500">
                      Showing <strong>{displayedRows.length.toLocaleString()}</strong> rows preview
                    </span>
                  </div>

                  <div className="overflow-x-auto max-h-96 border border-slate-100 rounded-lg">
                    <table className="w-full text-xs text-left">
                      <thead className="bg-slate-50 text-slate-700 font-bold sticky top-0 border-b border-slate-200">
                        <tr>
                          {execResult.columns.map(c => (
                            <th key={c} className="p-2.5 whitespace-nowrap">{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 text-slate-600 font-mono text-[11px]">
                        {displayedRows.map((row, idx) => (
                          <tr key={idx} className="hover:bg-blue-50/40">
                            {execResult.columns.map(c => {
                              const val = row[c];
                              const isOverlapCol = c === 'has_overlap';
                              return (
                                <td key={c} className="p-2.5 whitespace-nowrap">
                                  {isOverlapCol ? (
                                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                      val ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'
                                    }`}>
                                      {val ? 'TRUE' : 'FALSE'}
                                    </span>
                                  ) : (
                                    String(val ?? '-')
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Genomic Distribution Plots */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                  <div className="border border-slate-100 rounded-lg p-3.5 bg-slate-50/30 flex flex-col gap-2">
                    <span className="text-xs font-bold text-slate-700">Intervals Across Chromosomes</span>
                    <div className="h-60 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={execResult.charts.chromosome_distribution}>
                          <XAxis dataKey="chromosome" textAnchor="end" tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 10 }} />
                          <Tooltip />
                          <Bar dataKey="intervals" fill="#004e92" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div className="border border-slate-100 rounded-lg p-3.5 bg-slate-50/30 flex flex-col gap-2">
                    <span className="text-xs font-bold text-slate-700">Annotation Match Ratio</span>
                    <div className="h-60 w-full flex items-center justify-center">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie 
                            data={execResult.charts.match_ratio} 
                            dataKey="value" 
                            nameKey="name" 
                            innerRadius={50} 
                            outerRadius={75} 
                            paddingAngle={4}
                          >
                            <Cell fill="#004e92" />
                            <Cell fill="#cbd5e1" />
                          </Pie>
                          <Tooltip />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>

                {/* Gene list & top-10 chart (restored from the original Streamlit app) */}
                <div className="pt-2 border-t border-slate-100 flex flex-col gap-3">
                  {!hasGeneList ? (
                    <p className="text-[11px] text-slate-500">
                      No gene/feature name column found in the results.
                    </p>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="border border-slate-100 rounded-lg p-3.5 bg-slate-50/30 flex flex-col gap-2">
                        <span className="text-xs font-bold text-slate-700">Top 10 genes (by annotation count)</span>
                        <div className="h-64 w-full">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={geneList.top10} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
                              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} />
                              <YAxis type="category" dataKey="gene" width={110} tick={{ fontSize: 10 }} />
                              <Tooltip />
                              <Bar dataKey="count" fill="#004e92" radius={[0, 4, 4, 0]} />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </div>

                      <div className="border border-slate-100 rounded-lg p-3.5 bg-slate-50/30 flex flex-col gap-2.5">
                        <span className="text-xs font-bold text-slate-700">
                          Gene list ({geneList.genes.length.toLocaleString()})
                        </span>
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            onClick={() => downloadGeneList('txt')}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-[#004e92] hover:bg-blue-50/40 text-xs font-semibold text-slate-700 cursor-pointer"
                          >
                            <Download className="w-3.5 h-3.5 text-[#004e92]" /> gene_list.txt
                          </button>
                          <button
                            onClick={() => downloadGeneList('csv')}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-[#004e92] hover:bg-blue-50/40 text-xs font-semibold text-slate-700 cursor-pointer"
                          >
                            <Download className="w-3.5 h-3.5 text-[#006FB7]" /> gene_list.csv
                          </button>
                          <button
                            onClick={copyGeneListText}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-[#004e92] hover:bg-blue-50/40 text-xs font-semibold text-slate-700 cursor-pointer"
                          >
                            {geneCopyStatus === 'copied'
                              ? <Check className="w-3.5 h-3.5 text-emerald-600" />
                              : <Copy className="w-3.5 h-3.5" />}
                            {geneCopyStatus === 'copied' ? 'Copied' : geneCopyStatus === 'error' ? 'Copy failed' : 'Copy (comma-separated)'}
                          </button>
                        </div>
                        <div className="max-h-44 overflow-y-auto border border-slate-100 rounded-lg bg-white p-2 font-mono text-[11px] text-slate-600">
                          {geneList.genes.map(g => <div key={g}>{g}</div>)}
                        </div>
                        <p className="text-[11px] text-slate-500 leading-normal">
                          One gene per line in the .txt, comma-separated in the .csv. Paste into{' '}
                          <a href="https://biit.cs.ut.ee/gprofiler" target="_blank" rel="noreferrer" className="text-[#004e92] hover:underline font-medium">g:Profiler</a>,{' '}
                          <a href="https://maayanlab.cloud/Enrichr" target="_blank" rel="noreferrer" className="text-[#004e92] hover:underline font-medium">Enrichr</a>,{' '}
                          <a href="https://davidbioinformatics.nih.gov/tools.jsp" target="_blank" rel="noreferrer" className="text-[#004e92] hover:underline font-medium">DAVID</a> or{' '}
                          <a href="https://string-db.org" target="_blank" rel="noreferrer" className="text-[#004e92] hover:underline font-medium">STRING</a>.
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Export Buttons */}
                <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-slate-100">
                  <span className="text-xs font-bold text-slate-700">Download Results:</span>
                  <a
                    href={`/api/export/csv?filter_type=${resultFilter}`}
                    download
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-[#004e92] hover:bg-blue-50/40 text-xs font-semibold text-slate-700"
                  >
                    <Download className="w-3.5 h-3.5 text-[#004e92]" /> CSV
                  </a>
                  <a
                    href={`/api/export/tsv?filter_type=${resultFilter}`}
                    download
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-[#004e92] hover:bg-blue-50/40 text-xs font-semibold text-slate-700"
                  >
                    <Download className="w-3.5 h-3.5 text-[#006FB7]" /> TSV
                  </a>
                  <a
                    href={`/api/export/xlsx?filter_type=${resultFilter}`}
                    download
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-[#004e92] hover:bg-blue-50/40 text-xs font-semibold text-slate-700"
                  >
                    <Download className="w-3.5 h-3.5 text-emerald-600" /> Excel
                  </a>
                  {queryData?.format?.toLowerCase() === 'vcf' && (
                    <a
                      href={`/api/export/vcf?filter_type=${resultFilter}`}
                      download
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-[#004e92] hover:bg-blue-50/40 text-xs font-semibold text-slate-700"
                    >
                      <Download className="w-3.5 h-3.5 text-purple-600" /> VCF
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-4 rounded-lg bg-blue-50/60 border border-blue-100 text-xs text-blue-900 font-medium">
                No results yet. Upload both files, configure the operation, and run the annotation.
              </div>
            )}
          </section>

        </main>
      </div>

      {/* Prominent Clean 3-Column Footer (No Box on Cite AnnotateR) */}
      <footer className="border-t border-slate-200 bg-white py-8 mt-auto shadow-xs">
        <div className="w-[94%] mx-auto grid grid-cols-1 md:grid-cols-3 gap-6 items-center text-xs text-slate-600">
          
          {/* Column 1: Authorship & Email */}
          <div className="flex flex-col gap-1">
            <p className="font-medium text-slate-800">
              Developed by <strong>Jyotirmoy Das, Ph.D.</strong> & <strong>Massimiliano Volpe, Ph.D.</strong>
            </p>
            <p className="text-[11px] text-slate-500">
              <a href="mailto:jyotirmoy.das@liu.se" className="text-[#004e92] hover:underline font-medium">
              jyotirmoy.das@liu.se |  
            </a>
            <a href="mailto:massimiliano.volpe@scilifelab.se" className="text-[#004e92] hover:underline font-medium">
              | massimiliano.volpe@scilifelab.se
            </a>
            </p>
          </div>

          {/* Column 2: Direct Contact Emails */}
          <div className="flex flex-col sm:flex-row md:justify-center items-start md:items-center gap-2 sm:gap-4 text-slate-600">
            <div className="flex items-center gap-2 text-[10px] text-slate-400">
              <span>Version {meta?.version || '0.1.0'}</span>
              <span>•</span>
              <span>License: BSD-3-Clause</span>
              <span>•</span>
              <span>Bedtools & Polars-Bio</span>
            </div>
          </div>

          {/* Column 3: Cite AnnotateR (Clean without border/card box) */}
          <div className="flex flex-col md:items-end gap-1.5">
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-800">Cite AnnotateR</span>
              <button
                onClick={copyCitationText}
                className="text-[10px] flex items-center gap-1 font-semibold text-[#004e92] hover:text-[#003768] transition-colors cursor-pointer"
              >
                {citationStatus === 'copied' ? <Check className="w-3 h-3 text-emerald-600" /> : citationStatus === 'error' ? <AlertCircle className="w-3 h-3 text-rose-600" /> : <Copy className="w-3 h-3" />}
                {citationStatus === 'copied' ? 'Copied' : citationStatus === 'error' ? 'Copy failed' : 'Copy'}
              </button>
            </div>
            <p className="text-[11px] text-slate-500 leading-normal md:text-right font-mono">
              {formatCitationShort()}
            </p>          
          </div>

        </div>
      </footer>
    </div>
  );
}
