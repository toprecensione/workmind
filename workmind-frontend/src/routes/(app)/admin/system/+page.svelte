<script>
	import { onMount, onDestroy } from 'svelte';
	import { adminApi } from '$lib/api.js';

	let activeTab = 'status';
	let error = '';

	// Tab 1 — Status
	let status = null;
	let statusLoading = false;
	let statusInterval = null;

	// Tab 2 — Metrics
	let metrics = null;
	let metricsLoading = false;
	let metricsInterval = null;

	// Tab 3 — Overview
	let overview = null;
	let overviewLoading = false;
	let org = null;
	let orgEditing = false;
	let orgForm = { name: '', sector: '', slug: '' };
	let orgSaving = false;
	let orgError = '';
	let orgSuccess = '';

	function formatUptime(sec) {
		const d = Math.floor(sec / 86400);
		const h = Math.floor((sec % 86400) / 3600);
		const m = Math.floor((sec % 3600) / 60);
		if (d > 0) return `${d}g ${h}h`;
		if (h > 0) return `${h}h ${m}m`;
		return `${m}m`;
	}

	function metricColor(val) {
		return val > 80 ? 'var(--c-danger)' : val > 60 ? 'var(--c-warn)' : 'var(--c-gold)';
	}

	function serviceIcon(key) {
		const icons = { api: '🌐', postgresql: '🗄️', postgres: '🗄️', redis: '⚡', ollama: '🤖', disk: '💾' };
		return icons[key] || '🔧';
	}

	function serviceName(key) {
		const names = { api: 'API Server', postgresql: 'PostgreSQL', postgres: 'PostgreSQL', redis: 'Redis', ollama: 'Ollama AI', disk: 'Disco' };
		return names[key] || key;
	}

	async function loadStatus() {
		statusLoading = true;
		error = '';
		try {
			status = await adminApi.getSystemStatus();
		} catch (e) {
			error = e.message;
		} finally {
			statusLoading = false;
		}
	}

	async function loadMetrics() {
		metricsLoading = true;
		try {
			metrics = await adminApi.getSystemMetrics();
		} catch (e) {
			// silent on background refresh
		} finally {
			metricsLoading = false;
		}
	}

	async function loadOverview() {
		overviewLoading = true;
		error = '';
		try {
			[overview, org] = await Promise.all([
				adminApi.getSystemOverview(),
				adminApi.getOrg()
			]);
			orgForm = { name: org.name || '', sector: org.sector || '', slug: org.slug || '' };
		} catch (e) {
			error = e.message;
		} finally {
			overviewLoading = false;
		}
	}

	async function saveOrg() {
		orgSaving = true; orgError = ''; orgSuccess = '';
		try {
			org = await adminApi.updateOrg(orgForm);
			orgSuccess = 'Salvato con successo';
			orgEditing = false;
		} catch (e) {
			orgError = e.message;
		} finally {
			orgSaving = false;
		}
	}

	function switchTab(tab) {
		activeTab = tab;
		error = '';
		if (tab === 'status' && !status) loadStatus();
		if (tab === 'metrics' && !metrics) loadMetrics();
		if (tab === 'overview' && !overview && !overviewLoading) loadOverview();
	}

	onMount(async () => {
		await loadStatus();
		statusInterval = setInterval(loadStatus, 30000);
		metricsInterval = setInterval(() => {
			if (activeTab === 'metrics') loadMetrics();
		}, 10000);
	});

	onDestroy(() => {
		clearInterval(statusInterval);
		clearInterval(metricsInterval);
	});
</script>

<div class="page-header">
	<h1 class="page-title">Sistema</h1>
</div>

{#if error}
	<div class="alert alert-error">{error}</div>
{/if}

<div class="tab-bar">
	<button class="tab" class:active={activeTab === 'status'} on:click={() => switchTab('status')}>Stato Servizi</button>
	<button class="tab" class:active={activeTab === 'metrics'} on:click={() => switchTab('metrics')}>Risorse</button>
	<button class="tab" class:active={activeTab === 'overview'} on:click={() => switchTab('overview')}>Panoramica</button>
</div>

<!-- TAB 1: Stato Servizi -->
{#if activeTab === 'status'}
	<div class="tab-actions">
		<button class="btn btn-outline btn-sm" on:click={loadStatus} disabled={statusLoading}>
			{#if statusLoading}<span class="spinner"></span>{/if}
			Aggiorna
		</button>
	</div>

	{#if statusLoading && !status}
		<div class="empty-state"><span class="spinner"></span></div>
	{:else if status}
		<div class="services-grid">
			{#each [['api', status.api], ['postgres', status.postgres], ['redis', status.redis], ['ollama', status.ollama], ['disk', status.disk]].filter(([,v]) => v != null) as [key, svc]}
				<div class="service-card">
					<div class="service-icon">{serviceIcon(key)}</div>
					<div class="service-info">
						<div class="service-name">{serviceName(key)}</div>
						{#if svc.latency_ms != null}
							<div class="service-detail">{svc.latency_ms}ms</div>
						{:else if svc.uptime_seconds != null}
							<div class="service-detail">Uptime: {formatUptime(svc.uptime_seconds)}</div>
						{:else if svc.model}
							<div class="service-detail">{svc.model}</div>
						{:else if svc.used_pct != null}
							<div class="service-detail">{svc.used_pct}% utilizzato</div>
						{/if}
					</div>
					<span class="badge {svc.status === 'ok' ? 'badge-ok' : 'badge-danger'}">
						{svc.status === 'ok' ? '● Online' : '● Offline'}
					</span>
				</div>
			{/each}
		</div>
		{#if status.last_checked}
			<p class="last-updated">Ultimo aggiornamento: {new Date(status.last_checked).toLocaleTimeString('it-IT')}</p>
		{/if}
	{:else if !statusLoading}
		<div class="empty-state">Nessun dato disponibile</div>
	{/if}
{/if}

<!-- TAB 2: Risorse -->
{#if activeTab === 'metrics'}
	{#if metricsLoading && !metrics}
		<div class="empty-state"><span class="spinner"></span></div>
	{:else}
		{#if !metrics}
			{#await loadMetrics() then _}<!-- loaded -->{/await}
		{/if}
		{#if metrics}
			<div class="card">
				<div class="metric-bar">
					<div class="metric-label">CPU <span class="metric-val">{metrics.cpu_pct ?? 0}%</span></div>
					<div class="progress-track"><div class="progress-fill" style="width:{metrics.cpu_pct ?? 0}%;background:{metricColor(metrics.cpu_pct ?? 0)}"></div></div>
				</div>
				<div class="metric-bar">
					<div class="metric-label">
						RAM <span class="metric-val">{metrics.ram_pct ?? 0}%</span>
						{#if metrics.ram_used_mb && metrics.ram_total_mb}
							<span class="metric-sub">({(metrics.ram_used_mb/1024).toFixed(1)} / {(metrics.ram_total_mb/1024).toFixed(1)} GB)</span>
						{/if}
					</div>
					<div class="progress-track"><div class="progress-fill" style="width:{metrics.ram_pct ?? 0}%;background:{metricColor(metrics.ram_pct ?? 0)}"></div></div>
				</div>
				<div class="metric-bar">
					<div class="metric-label">
						Disco <span class="metric-val">{metrics.disk_pct ?? 0}%</span>
						{#if metrics.disk_used_gb && metrics.disk_total_gb}
							<span class="metric-sub">({metrics.disk_used_gb.toFixed(1)} / {metrics.disk_total_gb.toFixed(1)} GB)</span>
						{/if}
					</div>
					<div class="progress-track"><div class="progress-fill" style="width:{metrics.disk_pct ?? 0}%;background:{metricColor(metrics.disk_pct ?? 0)}"></div></div>
				</div>
				{#if metrics.uptime_seconds != null}
					<div class="uptime-row">Uptime: <strong>{formatUptime(metrics.uptime_seconds)}</strong></div>
				{/if}
			</div>
		{/if}
	{/if}
{/if}

<!-- TAB 3: Panoramica -->
{#if activeTab === 'overview'}
	{#if overviewLoading}
		<div class="empty-state"><span class="spinner"></span></div>
	{:else}
		{#if !overview && !org}
			<div class="empty-state">
				<p>Nessun dato disponibile.</p>
				<button class="btn btn-outline btn-sm" style="margin-top:.5rem" on:click={loadOverview}>Riprova</button>
			</div>
		{/if}
		{#if overview}
			<div class="kpi-grid" style="margin-bottom:1.25rem">
				<div class="kpi-card">
					<div class="kpi-val">{overview.active_users ?? '—'}</div>
					<div class="kpi-label">Utenti attivi</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-val">{overview.total_documents ?? '—'}</div>
					<div class="kpi-label">Documenti KB</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-val">{overview.kb_chunks ?? '—'}</div>
					<div class="kpi-label">Chunk KB</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-val">{overview.conversations_today ?? '—'}</div>
					<div class="kpi-label">Conversazioni oggi</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-val">{overview.messages_today ?? '—'}</div>
					<div class="kpi-label">Messaggi oggi</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-val">{overview.memories ?? '—'}</div>
					<div class="kpi-label">Memorie AI</div>
				</div>
			</div>
		{/if}

		{#if org}
			<div class="card">
				<div class="card-section-header">
					<span class="card-title">Organizzazione</span>
					{#if !orgEditing}
						<button class="btn btn-outline btn-sm" on:click={() => { orgEditing = true; orgSuccess = ''; }}>Modifica</button>
					{/if}
				</div>

				{#if orgError}<div class="alert alert-error">{orgError}</div>{/if}
				{#if orgSuccess}<div class="alert alert-success">{orgSuccess}</div>{/if}

				{#if orgEditing}
					<form on:submit|preventDefault={saveOrg}>
						<div class="form-group">
							<label class="form-label" for="org-name">Nome</label>
							<input id="org-name" class="form-input" bind:value={orgForm.name} required />
						</div>
						<div class="form-group">
							<label class="form-label" for="org-sector">Settore</label>
							<input id="org-sector" class="form-input" bind:value={orgForm.sector} />
						</div>
						<div class="form-group">
							<label class="form-label" for="org-slug">Slug</label>
							<input id="org-slug" class="form-input" bind:value={orgForm.slug} />
						</div>
						<div style="display:flex;gap:.5rem">
							<button type="submit" class="btn btn-primary btn-sm" disabled={orgSaving}>
								{#if orgSaving}<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px"></span>{/if}
								Salva
							</button>
							<button type="button" class="btn btn-outline btn-sm" on:click={() => { orgEditing = false; orgError = ''; }}>Annulla</button>
						</div>
					</form>
				{:else}
					<dl class="org-dl">
						<dt>Nome</dt><dd>{org.name || '—'}</dd>
						<dt>Settore</dt><dd>{org.sector || '—'}</dd>
						<dt>Slug</dt><dd>{org.slug || '—'}</dd>
					</dl>
				{/if}
			</div>
		{/if}
	{/if}
{/if}

<style>
.tab-bar { display:flex; gap:.25rem; border-bottom:2px solid var(--c-border); margin-bottom:1.25rem; }
.tab { background:none; border:none; padding:.5rem .85rem; font-size:.88rem; color:var(--c-muted); cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-2px; }
.tab.active { color:var(--c-text); border-bottom-color:var(--c-gold); font-weight:600; }

.tab-actions { display:flex; justify-content:flex-end; margin-bottom:.75rem; }

.services-grid { display:flex; flex-direction:column; gap:.6rem; }
.service-card { display:flex; align-items:center; gap:.75rem; padding:.75rem; background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--radius); }
.service-icon { font-size:1.4rem; width:2rem; text-align:center; flex-shrink:0; }
.service-info { flex:1; }
.service-name { font-weight:600; font-size:.9rem; }
.service-detail { font-size:.78rem; color:var(--c-muted); margin-top:.1rem; }

.last-updated { font-size:.75rem; color:var(--c-muted); margin-top:.75rem; text-align:right; }

.progress-track { height:8px; background:var(--c-border); border-radius:4px; overflow:hidden; }
.progress-fill { height:100%; border-radius:4px; transition:width .5s ease; }
.metric-bar { margin-bottom:1.1rem; }
.metric-label { display:flex; align-items:center; gap:.4rem; font-size:.83rem; margin-bottom:.3rem; font-weight:500; flex-wrap:wrap; }
.metric-val { font-weight:700; color:var(--c-text); }
.metric-sub { font-size:.75rem; color:var(--c-muted); font-weight:400; }
.uptime-row { font-size:.83rem; color:var(--c-muted); margin-top:.5rem; padding-top:.75rem; border-top:1px solid var(--c-border); }

.kpi-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:.75rem; }
.kpi-card { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--radius); padding:.85rem; text-align:center; }
.kpi-val { font-size:1.8rem; font-weight:700; color:var(--c-gold); }
.kpi-label { font-size:.75rem; color:var(--c-muted); margin-top:.2rem; }

.card-section-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:1rem; }

.org-dl { display:grid; grid-template-columns:auto 1fr; gap:.35rem .75rem; font-size:.88rem; }
.org-dl dt { color:var(--c-muted); font-weight:600; }
.org-dl dd { color:var(--c-text); }
</style>
