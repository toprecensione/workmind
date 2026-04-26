<script>
	import { onMount } from 'svelte';
	import { statsApi, productsApi } from '$lib/api.js';

	let stats = null;       // { totals: {sales_count, units_sold, revenue_eur}, by_product: [] }
	let products = [];      // for active product count
	let alerts = [];
	let loading = true;
	let error = '';

	onMount(async () => {
		try {
			const [s, p, a] = await Promise.all([
				statsApi.overview().catch(() => null),
				productsApi.list().catch(() => []),
				productsApi.alerts().catch(() => []),
			]);
			stats    = s;
			products = Array.isArray(p) ? p : [];
			alerts   = Array.isArray(a) ? a : [];
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	});

	function fmtEur(n) {
		return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(n ?? 0);
	}

	$: totalSales    = stats?.totals?.units_sold ?? 0;
	$: totalRevenue  = stats?.totals?.revenue_eur ?? 0;
	$: totalProducts = Array.isArray(products) ? products.length : 0;
	$: topProducts   = (stats?.by_product ?? []).slice(0, 5);
</script>

<svelte:head><title>Dashboard — MEDIC</title></svelte:head>

<div class="page-header">
	<h1 class="page-title">Dashboard</h1>
</div>

{#if loading}
	<div style="display:flex;gap:.75rem;align-items:center;color:var(--c-muted)">
		<span class="spinner"></span> Caricamento...
	</div>
{:else if error}
	<div class="alert alert-error">{error}</div>
{:else}
	<!-- KPI cards -->
	<div class="kpi-grid">
		<div class="card">
			<div class="card-title">Vendite totali</div>
			<div class="card-value">{totalSales}</div>
			<div class="kpi-sub">unità vendute</div>
		</div>
		<div class="card">
			<div class="card-title">Fatturato</div>
			<div class="card-value">{fmtEur(totalRevenue)}</div>
			<div class="kpi-sub">totale</div>
		</div>
		<div class="card">
			<div class="card-title">Prodotti attivi</div>
			<div class="card-value">{totalProducts}</div>
			<div class="kpi-sub">a catalogo</div>
		</div>
		<div class="card" class:alert-card={alerts.length > 0}>
			<div class="card-title">Alert stock</div>
			<div class="card-value" style="color:{alerts.length > 0 ? 'var(--c-danger)' : 'var(--c-ok)'}">
				{alerts.length}
			</div>
			<div class="kpi-sub">prodotti sotto soglia</div>
		</div>
	</div>

	<!-- Stock alerts -->
	{#if alerts.length > 0}
		<div class="section-title">⚠️ Stock da ricaricare</div>
		<div class="card">
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Prodotto</th>
							<th>Stock attuale</th>
							<th>Soglia minima</th>
							<th>Stato</th>
						</tr>
					</thead>
					<tbody>
						{#each alerts as p}
							<tr>
								<td><strong>{p.name}</strong></td>
								<td>{p.stock_qty} {p.unit}</td>
								<td>{p.min_stock_alert ?? 0}</td>
								<td>
									{#if p.stock_qty === 0}
										<span class="badge badge-danger">Esaurito</span>
									{:else}
										<span class="badge badge-warn">Basso</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<!-- Top products -->
	{#if topProducts.length}
		<div class="section-title">Top prodotti (per unità vendute)</div>
		<div class="card">
			<div class="table-wrap">
				<table>
					<thead>
						<tr><th>Prodotto</th><th>Unità vendute</th><th>Fatturato</th></tr>
					</thead>
					<tbody>
						{#each topProducts as p}
							<tr>
								<td>{p.product_name}</td>
								<td>{p.total_units}</td>
								<td>{fmtEur(p.total_revenue_eur)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
{/if}

<style>
.kpi-grid {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
	gap: 1rem;
	margin-bottom: 2rem;
}
.kpi-sub { font-size: .75rem; color: var(--c-muted); margin-top: .2rem; }
.alert-card { border-left: 3px solid var(--c-danger); }
.section-title { font-size: .8rem; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--c-muted); margin: 1.5rem 0 .75rem; }
</style>
