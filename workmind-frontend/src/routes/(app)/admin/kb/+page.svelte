<script>
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/api.js';
	import { auth } from '$lib/stores.js';
	import { get } from 'svelte/store';

	let activeTab = 'documents';
	let error = '';

	// Tab 1 — Documents
	let stats = null;
	let documents = [];
	let docsLoading = false;
	let filterStatus = '';
	let fileInput;
	let uploading = false;
	let uploadError = '';
	let uploadSuccess = '';

	// Tab 2 — Watch Paths
	let watchPaths = [];
	let pathsLoading = false;
	let pathError = '';
	let addForm = { path: '', type: 'local', enabled: true };
	let addingPath = false;
	let scanningIds = new Set();

	// Tab 3 — Search
	let searchQuery = '';
	let searchResults = [];
	let searching = false;
	let searchError = '';

	const statusColors = {
		indexed:    'badge-ok',
		processing: 'badge-warn',
		failed:     'badge-danger',
		pending:    'badge-muted',
	};

	function statusLabel(s) {
		const map = { indexed: 'Indicizzato', processing: 'In corso', failed: 'Errore', pending: 'In attesa' };
		return map[s] || s;
	}

	function formatDate(d) {
		if (!d) return '—';
		return new Date(d).toLocaleDateString('it-IT', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' });
	}

	function formatBytes(b) {
		if (!b) return '—';
		if (b >= 1048576) return (b/1048576).toFixed(1) + ' MB';
		if (b >= 1024) return (b/1024).toFixed(0) + ' KB';
		return b + ' B';
	}

	async function loadDocuments() {
		docsLoading = true; error = '';
		try {
			const params = { limit: 100 };
			if (filterStatus) params.status = filterStatus;
			[stats, documents] = await Promise.all([
				adminApi.getKbStats(),
				adminApi.listKbDocuments(params).then(r => r.documents || r.items || r || [])
			]);
		} catch (e) {
			error = e.message;
		} finally {
			docsLoading = false;
		}
	}

	async function deleteDocument(id, filename) {
		if (!confirm(`Eliminare "${filename}"?`)) return;
		try {
			await adminApi.deleteKbDocument(id);
			documents = documents.filter(d => d.id !== id);
			if (stats) stats.total_documents = (stats.total_documents || 1) - 1;
		} catch (e) {
			error = e.message;
		}
	}

	async function uploadFile(e) {
		const file = e.target.files?.[0];
		if (!file) return;
		uploading = true; uploadError = ''; uploadSuccess = '';
		try {
			const fd = new FormData();
			fd.append('file', file);
			const $auth = get(auth);
			const res = await fetch('/api/kb/documents/upload', {
				method: 'POST',
				headers: { Authorization: 'Bearer ' + $auth.accessToken },
				body: fd
			});
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail || `Errore ${res.status}`);
			}
			uploadSuccess = `File "${file.name}" caricato con successo`;
			await loadDocuments();
		} catch (e) {
			uploadError = e.message;
		} finally {
			uploading = false;
			if (fileInput) fileInput.value = '';
		}
	}

	async function loadWatchPaths() {
		pathsLoading = true; pathError = '';
		try {
			watchPaths = await adminApi.getKbWatchPaths().then(r => r.paths || r || []);
		} catch (e) {
			pathError = e.message;
		} finally {
			pathsLoading = false;
		}
	}

	async function addWatchPath() {
		if (!addForm.path.trim()) return;
		addingPath = true; pathError = '';
		try {
			const created = await adminApi.addKbWatchPath({ ...addForm });
			watchPaths = [...watchPaths, created];
			addForm = { path: '', type: 'local', enabled: true };
		} catch (e) {
			pathError = e.message;
		} finally {
			addingPath = false;
		}
	}

	async function toggleWatchPath(wp) {
		try {
			const updated = await adminApi.updateKbWatchPath(wp.id, { enabled: !wp.enabled });
			watchPaths = watchPaths.map(p => p.id === wp.id ? { ...p, ...updated } : p);
		} catch (e) {
			pathError = e.message;
		}
	}

	async function deleteWatchPath(id) {
		if (!confirm('Eliminare questo percorso?')) return;
		try {
			await adminApi.deleteKbWatchPath(id);
			watchPaths = watchPaths.filter(p => p.id !== id);
		} catch (e) {
			pathError = e.message;
		}
	}

	async function scanWatchPath(id) {
		scanningIds = new Set([...scanningIds, id]);
		try {
			await adminApi.scanKbWatchPath(id);
			const updated = await adminApi.getKbWatchPaths().then(r => r.paths || r || []);
			watchPaths = updated;
		} catch (e) {
			pathError = e.message;
		} finally {
			scanningIds.delete(id);
			scanningIds = new Set(scanningIds);
		}
	}

	async function doSearch() {
		if (!searchQuery.trim()) return;
		searching = true; searchError = '';
		try {
			const res = await adminApi.searchKb(searchQuery, 10);
			searchResults = res.results || res || [];
		} catch (e) {
			searchError = e.message;
		} finally {
			searching = false;
		}
	}

	function scoreColor(score) {
		if (score >= 0.7) return 'var(--c-ok)';
		if (score >= 0.4) return 'var(--c-warn)';
		return 'var(--c-danger)';
	}

	function switchTab(tab) {
		activeTab = tab;
		error = '';
		if (tab === 'documents' && !documents.length && !docsLoading) loadDocuments();
		if (tab === 'paths' && !watchPaths.length && !pathsLoading) loadWatchPaths();
	}

	onMount(() => {
		loadDocuments();
	});
</script>

<div class="page-header">
	<h1 class="page-title">Knowledge Base</h1>
</div>

{#if error}
	<div class="alert alert-error">{error}</div>
{/if}

<div class="tab-bar">
	<button class="tab" class:active={activeTab === 'documents'} on:click={() => switchTab('documents')}>Documenti</button>
	<button class="tab" class:active={activeTab === 'paths'} on:click={() => switchTab('paths')}>Percorsi</button>
	<button class="tab" class:active={activeTab === 'search'} on:click={() => switchTab('search')}>Cerca</button>
</div>

<!-- TAB 1: Documenti -->
{#if activeTab === 'documents'}
	{#if stats}
		<div class="stats-row">
			<div class="stat-chip">
				<span class="stat-val">{stats.total_documents ?? 0}</span>
				<span class="stat-label">Documenti</span>
			</div>
			<div class="stat-chip">
				<span class="stat-val">{stats.total_chunks ?? 0}</span>
				<span class="stat-label">Chunk</span>
			</div>
			<div class="stat-chip">
				<span class="stat-val">{stats.indexed ?? 0}</span>
				<span class="stat-label">Indicizzati</span>
			</div>
			{#if stats.failed > 0}
				<div class="stat-chip stat-chip-error">
					<span class="stat-val">{stats.failed}</span>
					<span class="stat-label">Errori</span>
				</div>
			{/if}
		</div>
	{/if}

	<div class="doc-toolbar">
		<div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
			<select class="form-input" style="width:auto;padding:.4rem .7rem;font-size:.83rem" bind:value={filterStatus} on:change={loadDocuments}>
				<option value="">Tutti</option>
				<option value="indexed">Indicizzati</option>
				<option value="processing">In corso</option>
				<option value="failed">Errori</option>
				<option value="pending">In attesa</option>
			</select>
			<button class="btn btn-outline btn-sm" on:click={loadDocuments} disabled={docsLoading}>
				{#if docsLoading}<span class="spinner"></span>{/if}
				Aggiorna
			</button>
		</div>
		<div>
			{#if uploadError}<span class="upload-msg upload-err">{uploadError}</span>{/if}
			{#if uploadSuccess}<span class="upload-msg upload-ok">{uploadSuccess}</span>{/if}
			<label class="btn btn-primary btn-sm" style="cursor:pointer">
				{#if uploading}<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px"></span>{/if}
				Carica file
				<input type="file" bind:this={fileInput} on:change={uploadFile} style="display:none" disabled={uploading} />
			</label>
		</div>
	</div>

	{#if docsLoading && !documents.length}
		<div class="empty-state"><span class="spinner"></span></div>
	{:else if documents.length === 0}
		<div class="empty-state">Nessun documento trovato</div>
	{:else}
		<div class="card" style="padding:0;overflow:hidden">
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>File</th>
							<th>Stato</th>
							<th>Chunk</th>
							<th>Dimensione</th>
							<th>Caricato</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each documents as doc}
							<tr>
								<td data-label="File"><span class="doc-name">{doc.filename || doc.title || doc.id}</span></td>
								<td data-label="Stato">
									<span class="badge {statusColors[doc.status] || 'badge-muted'}">{statusLabel(doc.status)}</span>
								</td>
								<td data-label="Chunk">{doc.chunk_count ?? doc.chunks ?? '—'}</td>
								<td data-label="Dimensione">{formatBytes(doc.size_bytes || doc.size)}</td>
								<td data-label="Caricato">{formatDate(doc.created_at)}</td>
								<td>
									<button class="btn btn-danger btn-sm" on:click={() => deleteDocument(doc.id, doc.filename || doc.title)}>Elimina</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
{/if}

<!-- TAB 2: Percorsi Monitorati -->
{#if activeTab === 'paths'}
	{#if pathError}
		<div class="alert alert-error">{pathError}</div>
	{/if}

	<div class="card" style="margin-bottom:1rem">
		<div class="card-title" style="margin-bottom:.75rem">Aggiungi percorso</div>
		<form on:submit|preventDefault={addWatchPath} style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:flex-end">
			<div class="form-group" style="margin:0;flex:1;min-width:200px">
				<label class="form-label" for="path-input">Percorso</label>
				<input id="path-input" class="form-input" bind:value={addForm.path} placeholder="/data/documenti" required />
			</div>
			<div class="form-group" style="margin:0">
				<label class="form-label" for="path-type">Tipo</label>
				<select id="path-type" class="form-input" bind:value={addForm.type} style="padding:.6rem .85rem">
					<option value="local">Local</option>
					<option value="smb">SMB</option>
				</select>
			</div>
			<div class="form-group" style="margin:0;display:flex;align-items:center;gap:.4rem;padding-bottom:.1rem">
				<input type="checkbox" id="path-enabled" bind:checked={addForm.enabled} />
				<label for="path-enabled" style="font-size:.83rem;cursor:pointer">Abilitato</label>
			</div>
			<button type="submit" class="btn btn-primary btn-sm" disabled={addingPath}>
				{#if addingPath}<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px"></span>{/if}
				Aggiungi
			</button>
		</form>
	</div>

	{#if pathsLoading && !watchPaths.length}
		<div class="empty-state"><span class="spinner"></span></div>
	{:else if watchPaths.length === 0}
		<div class="empty-state">Nessun percorso configurato</div>
	{:else}
		<div class="paths-list">
			{#each watchPaths as wp}
				<div class="path-card">
					<div class="path-main">
						<code class="path-code">{wp.path}</code>
						<div class="path-meta">
							<span class="badge badge-muted">{wp.type || 'local'}</span>
							{#if wp.last_scan_at}
								<span class="path-scan-time">Scansionato: {formatDate(wp.last_scan_at)}</span>
							{/if}
						</div>
					</div>
					<div class="path-actions">
						<label class="toggle-switch">
							<input type="checkbox" checked={wp.enabled} on:change={() => toggleWatchPath(wp)} />
							<span class="toggle-slider"></span>
						</label>
						<button class="btn btn-outline btn-sm" on:click={() => scanWatchPath(wp.id)} disabled={scanningIds.has(wp.id)}>
							{#if scanningIds.has(wp.id)}<span class="spinner" style="width:.85rem;height:.85rem;border-width:2px"></span>{/if}
							Scansiona ora
						</button>
						<button class="btn btn-danger btn-sm" on:click={() => deleteWatchPath(wp.id)}>Elimina</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
{/if}

<!-- TAB 3: Cerca -->
{#if activeTab === 'search'}
	<div class="search-bar">
		<input
			class="form-input"
			style="flex:1"
			placeholder="Cerca nella knowledge base..."
			bind:value={searchQuery}
			on:keydown={e => e.key === 'Enter' && doSearch()}
		/>
		<button class="btn btn-primary" on:click={doSearch} disabled={searching || !searchQuery.trim()}>
			{#if searching}<span class="spinner" style="width:1rem;height:1rem;border-width:2px"></span>{/if}
			Cerca
		</button>
	</div>

	{#if searchError}
		<div class="alert alert-error">{searchError}</div>
	{/if}

	{#if searchResults.length === 0 && !searching}
		{#if searchQuery}
			<div class="empty-state">Nessun risultato</div>
		{/if}
	{:else}
		<div class="search-results">
			{#each searchResults as result}
				<div class="result-card">
					<div class="result-header">
						<span class="result-file">{result.filename || result.source || '—'}</span>
						<div class="score-wrap">
							<div class="score-bar-track">
								<div class="score-bar-fill" style="width:{Math.round((result.score || 0)*100)}%;background:{scoreColor(result.score || 0)}"></div>
							</div>
							<span class="score-pct" style="color:{scoreColor(result.score || 0)}">{Math.round((result.score || 0)*100)}%</span>
						</div>
					</div>
					<p class="result-content">{(result.content || result.text || '').slice(0, 200)}{(result.content || result.text || '').length > 200 ? '…' : ''}</p>
				</div>
			{/each}
		</div>
	{/if}
{/if}

<style>
.tab-bar { display:flex; gap:.25rem; border-bottom:2px solid var(--c-border); margin-bottom:1.25rem; }
.tab { background:none; border:none; padding:.5rem .85rem; font-size:.88rem; color:var(--c-muted); cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-2px; }
.tab.active { color:var(--c-text); border-bottom-color:var(--c-gold); font-weight:600; }

.stats-row { display:flex; gap:.6rem; flex-wrap:wrap; margin-bottom:1rem; }
.stat-chip { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--radius); padding:.5rem .85rem; display:flex; flex-direction:column; align-items:center; min-width:80px; }
.stat-chip-error { border-color:var(--c-danger); }
.stat-val { font-size:1.35rem; font-weight:700; color:var(--c-gold); line-height:1.1; }
.stat-chip-error .stat-val { color:var(--c-danger); }
.stat-label { font-size:.7rem; color:var(--c-muted); margin-top:.15rem; }

.doc-toolbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:.75rem; flex-wrap:wrap; gap:.5rem; }
.upload-msg { font-size:.8rem; margin-right:.5rem; }
.upload-err { color:var(--c-danger); }
.upload-ok { color:var(--c-ok); }
.doc-name { font-size:.85rem; max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:block; }

.paths-list { display:flex; flex-direction:column; gap:.6rem; }
.path-card { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--radius); padding:.85rem 1rem; display:flex; align-items:center; gap:1rem; flex-wrap:wrap; }
.path-main { flex:1; min-width:200px; }
.path-code { font-size:.82rem; background:var(--c-bg); padding:.2rem .45rem; border-radius:4px; word-break:break-all; display:block; margin-bottom:.35rem; }
.path-meta { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; }
.path-scan-time { font-size:.75rem; color:var(--c-muted); }
.path-actions { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; }

.search-bar { display:flex; gap:.5rem; margin-bottom:1rem; }
.search-results { display:flex; flex-direction:column; gap:.6rem; }
.result-card { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--radius); padding:.85rem; }
.result-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:.4rem; gap:.5rem; flex-wrap:wrap; }
.result-file { font-size:.8rem; font-weight:600; color:var(--c-muted); }
.score-wrap { display:flex; align-items:center; gap:.4rem; }
.score-bar-track { width:80px; height:6px; background:var(--c-border); border-radius:3px; overflow:hidden; }
.score-bar-fill { height:100%; border-radius:3px; }
.score-pct { font-size:.78rem; font-weight:700; min-width:2.5rem; text-align:right; }
.result-content { font-size:.83rem; color:var(--c-text); line-height:1.5; }
</style>
