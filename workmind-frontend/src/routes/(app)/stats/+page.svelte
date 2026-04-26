<script>
	import { onMount } from 'svelte';
	import { medicApi } from '$lib/api.js';

	let summary = null;
	let byAgent = [];
	let byProduct = [];
	let loading = true;
	let error = '';
	let tab = 'overview'; // overview | agents | products

	onMount(async () => {
		try {
			[summary, byAgent, byProduct] = await Promise.all([
				medicApi.get('/medic/stats/summary'),
				medicApi.get('/medic/stats/by-agent'),
				medicApi.get('/medic/stats/by-product'),
			]);
		} catch (e) { error = e.message; }
		finally { loading = false; }
	});

	function eur(n) {
		if (n == null) return '—';
		return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(n);
	}

	function pct(part, total) {
		if (!total) return 0;
		return Math.round((part / total) * 100);
	}

	$: totalUnits = summary?.totals?.units_sold ?? 0;
	$: totalRevenue = summary?.totals?.revenue_eur ?? 0;
	$: totalSales = summary?.totals?.sales_count ?? 0;
</script>

<svelte:head><title>Statistiche — MEDIC</title></svelte:head>

<div class="page-header">
	<h1 class="page-title">Statistiche</h1>
	<div class="filter-tabs">
		<button class="tab" class:active={tab==='overview'} on:click={() => tab='overview'}>Riepilogo</button>
		<button class="tab" class:active={tab==='agents'}   on:click={() => tab='agents'}>Operatori</button>
		<button class="tab" class:active={tab==='products'} on:click={() => tab='products'}>Prodotti</button>
	</div>
</div>

{#if loading}
	<div class="empty-state"><span class="spinner"></span></div>
{:else if error}
	<div class="alert alert-error">{error}</div>
{:else}

	<!-- ── OVERVIEW ── -->
	{#if tab === 'overview'}
		<div class="kpi-grid">
			<div class="card">
				<div class="card-title">Vendite totali</div>
				<div class="card-value">{totalSales}</div>
				<div class="kpi-sub">transazioni</div>
			</div>
			<div class="card">
				<div class="card-title">Unità vendute</div>
				<div class="card-value">{totalUnits}</div>
				<div class="kpi-sub">pezzi / siringhe</div>
			</div>
			<div class="card">
				<div class="card-title">Fatturato</div>
				<div class="card-value">{eur(totalRevenue)}</div>
				<div class="kpi-sub">vendite con prezzo</div>
			</div>
		</div>

		{#if summary?.by_product?.length}
			<div class="card" style="margin-top:1.25rem">
				<div class="card-title" style="margin-bottom:.75rem">Top prodotti</div>
				{#each summary.by_product.slice(0,5) as p}
					<div class="bar-row">
						<span class="bar-label">{p.product_name}</span>
						<div class="bar-track">
							<div class="bar-fill" style="width:{pct(p.total_units, totalUnits)}%"></div>
						</div>
						<span class="bar-val">{p.total_units} pz</span>
					</div>
				{/each}
			</div>
		{/if}
	{/if}

	<!-- ── AGENTS ── -->
	{#if tab === 'agents'}
		{#if byAgent.length === 0}
			<div class="empty-state">Nessuna vendita registrata.</div>
		{:else}
			<div class="agents-grid">
				{#each byAgent as agent}
					<div class="card agent-card">
						<div class="agent-name">{agent.agent_name}</div>
						<div class="agent-kpis">
							<div class="agent-kpi">
								<div class="agent-kpi-val">{agent.sale_count}</div>
								<div class="agent-kpi-label">vendite</div>
							</div>
							<div class="agent-kpi">
								<div class="agent-kpi-val">{agent.total_units}</div>
								<div class="agent-kpi-label">unità</div>
							</div>
							<div class="agent-kpi">
								<div class="agent-kpi-val">{eur(agent.total_revenue_eur)}</div>
								<div class="agent-kpi-label">fatturato</div>
							</div>
						</div>
						{#if totalUnits > 0}
							<div style="margin-top:.75rem">
								<div class="bar-track">
									<div class="bar-fill" style="width:{pct(agent.total_units, totalUnits)}%"></div>
								</div>
								<div style="font-size:.72rem;color:var(--c-muted);margin-top:.2rem">{pct(agent.total_units, totalUnits)}% del totale</div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{/if}

	<!-- ── PRODUCTS ── -->
	{#if tab === 'products'}
		{#if byProduct.length === 0}
			<div class="empty-state">Nessuna vendita registrata.</div>
		{:else}
			<div class="card" style="padding:0;overflow:hidden">
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th>Prodotto</th>
								<th>Vendite</th>
								<th>Unità</th>
								<th>Fatturato</th>
								<th>Stock</th>
							</tr>
						</thead>
						<tbody>
							{#each byProduct as p}
								<tr>
									<td data-label="Prodotto"><strong>{p.product_name}</strong></td>
									<td data-label="Vendite">{p.sale_count}</td>
									<td data-label="Unità">{p.total_units_sold}</td>
									<td data-label="Fatturato">{eur(p.total_revenue_eur)}</td>
									<td data-label="Stock">
										<span class="badge {p.current_stock <= 5 ? 'badge-danger' : 'badge-ok'}">{p.current_stock}</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
	{/if}
{/if}

<style>
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; }
.kpi-sub { font-size: .75rem; color: var(--c-muted); margin-top: .2rem; }

.bar-row { display: flex; align-items: center; gap: .6rem; margin-bottom: .5rem; }
.bar-label { width: 90px; font-size: .8rem; font-weight: 600; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; height: 8px; background: var(--c-bg); border-radius: 99px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--c-gold); border-radius: 99px; transition: width .4s; }
.bar-val { width: 52px; text-align: right; font-size: .78rem; color: var(--c-muted); flex-shrink: 0; }

.agents-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }
.agent-name { font-size: 1rem; font-weight: 700; margin-bottom: .75rem; }
.agent-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; }
.agent-kpi { text-align: center; }
.agent-kpi-val { font-size: 1.3rem; font-weight: 700; }
.agent-kpi-label { font-size: .7rem; color: var(--c-muted); text-transform: uppercase; letter-spacing: .04em; }

.filter-tabs { display: flex; gap: .4rem; flex-wrap: wrap; }
.tab {
	padding: .4rem .9rem; border-radius: 99px; font-size: .8rem; font-weight: 600;
	border: 1.5px solid var(--c-border); background: transparent; color: var(--c-muted);
	cursor: pointer; transition: all .15s;
}
.tab.active { background: var(--c-gold); border-color: var(--c-gold); color: #111; }

@media (max-width: 640px) {
	.agents-grid { grid-template-columns: 1fr; }
	.kpi-grid { grid-template-columns: repeat(3, 1fr); gap: .6rem; }
}
</style>
