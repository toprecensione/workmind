<script>
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/api.js';

	let loading = true;
	let error = '';
	let summary = [];
	let dailyData = [];
	let selectedDays = 30;

	// Totali aggregati
	$: totalCost   = summary.reduce((s, r) => s + (r.total_cost_usd || 0), 0);
	$: totalInput  = summary.reduce((s, r) => s + (r.total_input_tokens || 0), 0);
	$: totalOutput = summary.reduce((s, r) => s + (r.total_output_tokens || 0), 0);
	$: totalCalls  = summary.reduce((s, r) => s + (r.total_calls || 0), 0);

	// Prepara barre SVG dal daily breakdown
	$: chartBars = (() => {
		if (!dailyData.length) return [];
		const maxCost = Math.max(...dailyData.map(d => d.total_cost_usd || 0), 0.001);
		return dailyData.map(d => ({
			date: d.date,
			height: Math.max(2, ((d.total_cost_usd || 0) / maxCost) * 52),
			cost: d.total_cost_usd || 0,
		}));
	})();

	function fmtCost(v) {
		return v != null ? '$' + Number(v).toFixed(4) : '—';
	}
	function fmtTokens(v) {
		if (!v) return '0';
		if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
		if (v >= 1000) return (v / 1000).toFixed(1) + 'K';
		return String(v);
	}
	function fmtDate(s) {
		if (!s) return '';
		try { return new Date(s).toLocaleDateString('it-IT', { day:'2-digit', month:'short' }); }
		catch { return s.slice(5, 10); }
	}

	async function load() {
		loading = true; error = '';
		try {
			const [sum, daily] = await Promise.all([
				adminApi.getAiUsage(selectedDays, false),
				adminApi.getAiUsage(selectedDays, true),
			]);
			summary = sum || [];
			// daily può essere array di {date, provider, model_name, total_calls, total_cost_usd, ...}
			// Raggruppa per data sommando tutti i provider
			const byDate = {};
			for (const row of (daily || [])) {
				if (!byDate[row.date]) byDate[row.date] = { date: row.date, total_cost_usd: 0, total_calls: 0 };
				byDate[row.date].total_cost_usd += row.total_cost_usd || 0;
				byDate[row.date].total_calls += row.total_calls || 0;
			}
			dailyData = Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
		} catch (e) {
			error = e.message || 'Errore caricamento';
		} finally {
			loading = false;
		}
	}

	onMount(load);
</script>

<div class="page-header">
	<h1 class="page-title">Utilizzo AI</h1>
	<div style="display:flex;gap:.5rem;align-items:center">
		<select class="form-input" style="width:auto;font-size:.83rem;padding:.3rem .5rem" bind:value={selectedDays} on:change={load}>
			<option value={7}>Ultimi 7 giorni</option>
			<option value={30}>Ultimi 30 giorni</option>
			<option value={90}>Ultimi 90 giorni</option>
		</select>
		<button class="btn btn-outline btn-sm" on:click={load} disabled={loading}>
			{#if loading}<span class="spinner" style="width:.8rem;height:.8rem;border-width:2px"></span>{:else}↻{/if}
		</button>
	</div>
</div>

{#if error}
	<div class="alert alert-error">{error}</div>
{/if}

{#if loading && !summary.length}
	<div class="empty-state"><span class="spinner"></span><p>Caricamento…</p></div>
{:else}
	<!-- KPI Cards -->
	<div class="kpi-grid" style="margin-bottom:1.25rem">
		<div class="kpi-card">
			<div class="kpi-val">{fmtCost(totalCost)}</div>
			<div class="kpi-label">Costo totale</div>
		</div>
		<div class="kpi-card">
			<div class="kpi-val">{fmtTokens(totalInput)}</div>
			<div class="kpi-label">Token input</div>
		</div>
		<div class="kpi-card">
			<div class="kpi-val">{fmtTokens(totalOutput)}</div>
			<div class="kpi-label">Token output</div>
		</div>
		<div class="kpi-card">
			<div class="kpi-val">{totalCalls}</div>
			<div class="kpi-label">Chiamate totali</div>
		</div>
	</div>

	<!-- Grafico giornaliero -->
	{#if chartBars.length > 0}
		<div class="card" style="margin-bottom:1.25rem">
			<div class="card-title" style="margin-bottom:.75rem">Costi giornalieri</div>
			<div class="chart-scroll">
				<svg
					viewBox="0 -{5} {Math.max(chartBars.length * 14, 280)} 75"
					preserveAspectRatio="none"
					class="usage-chart"
					style="width:{Math.max(chartBars.length * 14, 280)}px;height:70px"
				>
					{#each chartBars as bar, i}
						<rect
							x={i * 14}
							y={52 - bar.height}
							width="10"
							height={bar.height}
							fill="var(--c-gold)"
							opacity=".85"
							rx="2"
						/>
						{#if i % 7 === 0}
							<text x={i * 14 + 5} y="68" text-anchor="middle" font-size="5" fill="var(--c-muted)">{fmtDate(bar.date)}</text>
						{/if}
					{/each}
				</svg>
			</div>
		</div>
	{/if}

	<!-- Tabella per provider/modello -->
	{#if summary.length > 0}
		<div class="card">
			<div class="card-title" style="margin-bottom:.75rem">Dettaglio per modello</div>
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Provider</th>
							<th>Modello</th>
							<th style="text-align:right">Chiamate</th>
							<th style="text-align:right">Token In</th>
							<th style="text-align:right">Token Out</th>
							<th style="text-align:right">Costo USD</th>
						</tr>
					</thead>
					<tbody>
						{#each summary as row}
							<tr>
								<td><span class="provider-badge provider-{row.provider}">{row.provider}</span></td>
								<td style="font-family:monospace;font-size:.8rem">{row.model_name}</td>
								<td style="text-align:right">{row.total_calls}</td>
								<td style="text-align:right">{fmtTokens(row.total_input_tokens)}</td>
								<td style="text-align:right">{fmtTokens(row.total_output_tokens)}</td>
								<td style="text-align:right;font-weight:600">{fmtCost(row.total_cost_usd)}</td>
							</tr>
						{/each}
					</tbody>
					<tfoot>
						<tr style="font-weight:700;border-top:2px solid var(--c-border)">
							<td colspan="2">Totale</td>
							<td style="text-align:right">{totalCalls}</td>
							<td style="text-align:right">{fmtTokens(totalInput)}</td>
							<td style="text-align:right">{fmtTokens(totalOutput)}</td>
							<td style="text-align:right">{fmtCost(totalCost)}</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>
	{:else if !loading}
		<div class="empty-state">
			<p>Nessun utilizzo AI registrato negli ultimi {selectedDays} giorni.</p>
		</div>
	{/if}
{/if}

<style>
.kpi-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:.75rem; }
.kpi-card { background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--radius); padding:.85rem; text-align:center; }
.kpi-val { font-size:1.6rem; font-weight:700; color:var(--c-gold); }
.kpi-label { font-size:.75rem; color:var(--c-muted); margin-top:.2rem; }

.card-title { font-size:.88rem; font-weight:700; color:var(--c-text); }

.chart-scroll { overflow-x:auto; }
.usage-chart { display:block; }

.provider-badge {
	display:inline-block; padding:.15rem .45rem;
	border-radius:99px; font-size:.72rem; font-weight:700;
	background:var(--c-border); color:var(--c-muted);
}
.provider-claude { background:#7c3aed22; color:#7c3aed; }
.provider-deepseek { background:#0ea5e922; color:#0ea5e9; }
.provider-ollama { background:#16a34a22; color:#16a34a; }
</style>
