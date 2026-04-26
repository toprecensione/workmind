<script>
	import { onMount, onDestroy } from 'svelte';
	import { get } from 'svelte/store';
	import { adminApi } from '$lib/api.js';
	import { auth } from '$lib/stores.js';

	let activeTab = 'logs';

	// ── Audit Logs ────────────────────────────────────────────────────────────
	let logs = [];
	let logsLoading = false;
	let logsError = '';
	let fromDate = '';
	let toDate = '';
	let eventTypeFilter = '';
	let logsLimit = 100;
	let exporting = false;

	const EVENT_TYPES = [
		{ value: '', label: 'Tutti i tipi' },
		{ value: 'ai_decision',       label: 'Decisione AI' },
		{ value: 'supervisor_teach',  label: 'Insegnamento' },
		{ value: 'correction',        label: 'Correzione' },
		{ value: 'anomaly',           label: 'Anomalia' },
		{ value: 'report_generated',  label: 'Report generato' },
		{ value: 'feedback',          label: 'Feedback' },
		{ value: 'system',            label: 'Sistema' },
		{ value: 'auth',              label: 'Autenticazione' },
		{ value: 'admin_action',      label: 'Azione admin' },
	];

	const EVENT_COLORS = {
		ai_decision:      'badge-ok',
		supervisor_teach: 'badge-ok',
		correction:       'badge-warn',
		anomaly:          'badge-danger',
		report_generated: 'badge-ok',
		feedback:         'badge-muted',
		system:           'badge-muted',
		auth:             'badge-muted',
		admin_action:     'badge-warn',
	};

	async function loadLogs() {
		logsLoading = true; logsError = '';
		try {
			const params = { limit: logsLimit };
			if (fromDate)       params.from_date = fromDate;
			if (toDate)         params.to_date   = toDate;
			if (eventTypeFilter) params.event_type = eventTypeFilter;
			logs = await adminApi.getAuditLogs(params);
		} catch (e) {
			logsError = e.message || 'Errore caricamento log';
		} finally {
			logsLoading = false;
		}
	}

	async function exportCsv() {
		exporting = true;
		try {
			const $auth = get(auth);
			const params = new URLSearchParams({ limit: 10000 });
			if (fromDate)       params.set('from_date', fromDate);
			if (toDate)         params.set('to_date', toDate);
			if (eventTypeFilter) params.set('event_type', eventTypeFilter);

			const res = await fetch(`/api/admin/audit/logs/export?${params}`, {
				headers: { Authorization: `Bearer ${$auth.accessToken}` },
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `audit_export_${new Date().toISOString().slice(0,10)}.csv`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			logsError = e.message;
		} finally {
			exporting = false;
		}
	}

	function fmtDt(s) {
		if (!s) return '—';
		try { return new Date(s).toLocaleString('it-IT'); }
		catch { return s; }
	}

	// ── Backup ────────────────────────────────────────────────────────────────
	let backups = [];
	let backupsLoading = false;
	let backupsError = '';
	let triggering = false;
	let pollingId = null;

	async function loadBackups() {
		backupsLoading = true; backupsError = '';
		try {
			backups = await adminApi.listBackups();
		} catch (e) {
			backupsError = e.message || 'Errore caricamento backup';
		} finally {
			backupsLoading = false;
		}
	}

	async function triggerBackup() {
		triggering = true; backupsError = '';
		try {
			const res = await adminApi.triggerBackup();
			// Aggiungi subito in testa con status pending
			backups = [{ id: res.backup_id, status: 'running', filename: '…', created_at: new Date().toISOString(), size_bytes: null }, ...backups];
			// Polling ogni 3s finché running
			pollingId = setInterval(async () => {
				try {
					const updated = await adminApi.getBackupStatus(res.backup_id);
					backups = backups.map(b => b.id === res.backup_id ? { ...b, ...updated } : b);
					if (updated.status !== 'running' && updated.status !== 'pending') {
						clearInterval(pollingId);
						pollingId = null;
					}
				} catch {}
			}, 3000);
		} catch (e) {
			backupsError = e.message || 'Errore avvio backup';
		} finally {
			triggering = false;
		}
	}

	function fmtSize(bytes) {
		if (!bytes) return '—';
		if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
		if (bytes >= 1024)        return (bytes / 1024).toFixed(0) + ' KB';
		return bytes + ' B';
	}

	function fmtDuration(s) {
		if (!s && s !== 0) return '—';
		if (s < 60) return `${s}s`;
		return `${Math.floor(s/60)}m ${s%60}s`;
	}

	function switchTab(tab) {
		activeTab = tab;
		if (tab === 'logs' && !logs.length) loadLogs();
		if (tab === 'backup' && !backups.length) loadBackups();
	}

	onMount(() => {
		loadLogs();
	});

	onDestroy(() => {
		if (pollingId) clearInterval(pollingId);
	});
</script>

<div class="page-header">
	<h1 class="page-title">Audit & Backup</h1>
</div>

<div class="tab-bar">
	<button class="tab" class:active={activeTab === 'logs'}   on:click={() => switchTab('logs')}>Log Attività</button>
	<button class="tab" class:active={activeTab === 'backup'} on:click={() => switchTab('backup')}>Backup Database</button>
</div>

<!-- ── TAB 1: Log Attività ──────────────────────────────────────────────────── -->
{#if activeTab === 'logs'}
	<!-- Filtri -->
	<div class="filter-bar">
		<input type="date" class="form-input filter-input" bind:value={fromDate} title="Da"/>
		<input type="date" class="form-input filter-input" bind:value={toDate} title="A"/>
		<select class="form-input filter-input" bind:value={eventTypeFilter}>
			{#each EVENT_TYPES as et}
				<option value={et.value}>{et.label}</option>
			{/each}
		</select>
		<select class="form-input filter-input" bind:value={logsLimit}>
			<option value={50}>50 righe</option>
			<option value={100}>100 righe</option>
			<option value={200}>200 righe</option>
		</select>
		<button class="btn btn-primary btn-sm" on:click={loadLogs} disabled={logsLoading}>
			{#if logsLoading}<span class="spinner" style="width:.8rem;height:.8rem;border-width:2px"></span>{:else}Filtra{/if}
		</button>
		<button class="btn btn-outline btn-sm" on:click={exportCsv} disabled={exporting} title="Esporta CSV">
			{#if exporting}<span class="spinner" style="width:.8rem;height:.8rem;border-width:2px"></span>{:else}↓ CSV{/if}
		</button>
	</div>

	{#if logsError}
		<div class="alert alert-error">{logsError}</div>
	{/if}

	{#if logsLoading && !logs.length}
		<div class="empty-state"><span class="spinner"></span></div>
	{:else if logs.length === 0}
		<div class="empty-state"><p>Nessun evento trovato con i filtri selezionati.</p></div>
	{:else}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>Data / Ora</th>
						<th>Tipo</th>
						<th>Attore</th>
						<th>Descrizione</th>
						<th>IP</th>
					</tr>
				</thead>
				<tbody>
					{#each logs as log}
						<tr>
							<td class="mono nowrap">{fmtDt(log.created_at)}</td>
							<td>
								<span class="badge {EVENT_COLORS[log.event_type] || 'badge-muted'}">
									{EVENT_TYPES.find(e => e.value === log.event_type)?.label || log.event_type}
								</span>
							</td>
							<td class="mono">{log.actor || '—'}</td>
							<td class="summary-cell">{log.summary || '—'}</td>
							<td class="mono">{log.ip_address || '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="record-count">{logs.length} eventi mostrati</p>
	{/if}
{/if}

<!-- ── TAB 2: Backup ─────────────────────────────────────────────────────────── -->
{#if activeTab === 'backup'}
	<div class="backup-header">
		<p class="page-subtitle">Esegui un backup completo del database PostgreSQL (pg_dump). I file vengono salvati sul server.</p>
		<button class="btn btn-primary" on:click={triggerBackup} disabled={triggering}>
			{#if triggering}
				<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px"></span>
				In corso…
			{:else}
				💾 Nuovo Backup
			{/if}
		</button>
	</div>

	{#if backupsError}
		<div class="alert alert-error">{backupsError}</div>
	{/if}

	{#if backupsLoading && !backups.length}
		<div class="empty-state"><span class="spinner"></span></div>
	{:else if backups.length === 0}
		<div class="empty-state"><p>Nessun backup ancora eseguito.</p></div>
	{:else}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>Data</th>
						<th>File</th>
						<th>Stato</th>
						<th style="text-align:right">Dimensione</th>
						<th style="text-align:right">Durata</th>
					</tr>
				</thead>
				<tbody>
					{#each backups as bk}
						<tr>
							<td class="mono nowrap">{fmtDt(bk.created_at)}</td>
							<td class="mono" style="font-size:.78rem;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title={bk.filename}>{bk.filename || '—'}</td>
							<td>
								{#if bk.status === 'success'}
									<span class="badge badge-ok">✓ Completato</span>
								{:else if bk.status === 'running' || bk.status === 'pending'}
									<span class="badge badge-warn">
										<span class="spinner" style="width:.6rem;height:.6rem;border-width:2px;margin-right:.25rem"></span>
										In corso…
									</span>
								{:else if bk.status === 'failed'}
									<span class="badge badge-danger" title={bk.error_msg || ''}>✗ Fallito</span>
								{:else}
									<span class="badge badge-muted">{bk.status}</span>
								{/if}
							</td>
							<td style="text-align:right">{fmtSize(bk.size_bytes)}</td>
							<td style="text-align:right">{fmtDuration(bk.duration_s)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/if}

<style>
.tab-bar { display:flex; gap:.25rem; border-bottom:2px solid var(--c-border); margin-bottom:1.25rem; }
.tab { background:none; border:none; padding:.5rem .85rem; font-size:.88rem; color:var(--c-muted); cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-2px; }
.tab.active { color:var(--c-text); border-bottom-color:var(--c-gold); font-weight:600; }

.filter-bar { display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin-bottom:1rem; }
.filter-input { font-size:.83rem; padding:.3rem .5rem; max-width:180px; }

.mono { font-family: monospace; font-size:.82rem; }
.nowrap { white-space: nowrap; }
.summary-cell { font-size:.83rem; max-width:280px; }
.record-count { font-size:.75rem; color:var(--c-muted); text-align:right; margin-top:.5rem; }

.page-subtitle { font-size:.85rem; color:var(--c-muted); margin-bottom:.75rem; }
.backup-header { display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; flex-wrap:wrap; margin-bottom:1rem; }

.badge-warn { background: #fef3c7; color: #92400e; }
.badge-danger { background: #fee2e2; color: #991b1b; }
</style>
