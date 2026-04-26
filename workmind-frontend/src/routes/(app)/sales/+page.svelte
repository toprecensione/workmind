<script>
	import { onMount } from 'svelte';
	import { salesApi, productsApi } from '$lib/api.js';
	import { auth } from '$lib/stores.js';

	let sales = [];
	let products = [];
	let loading = true;
	let error = '';

	$: role = $auth.user?.role ?? 'user';
	$: canSeeCost = role === 'admin' || role === 'supervisor';

	// Filters
	let filterFrom = '';
	let filterTo = '';

	// New sale modal
	let showNewSale = false;
	let newSale = { product_id: '', quantity: 1, unit_price: '', shipping_cost: '', sale_date: today(), notes: '' };
	let formLoading = false;
	let formError = '';

	// Edit modal
	let showEdit = false;
	let editSale = null;
	let editForm = {};
	let editLoading = false;
	let editError = '';

	// Delete confirm
	let showDeleteConfirm = false;
	let saleToDelete = null;
	let deleteLoading = false;
	let deleteError = '';

	function today() {
		return new Date().toISOString().slice(0, 10);
	}

	onMount(async () => {
		try {
			[sales, products] = await Promise.all([salesApi.list(), productsApi.list()]);
		} catch (e) { error = e.message; }
		finally { loading = false; }
	});

	async function applyFilters() {
		loading = true; error = '';
		try {
			sales = await salesApi.list({
				from_date: filterFrom || null,
				to_date: filterTo || null,
			});
		} catch (e) { error = e.message; }
		finally { loading = false; }
	}

	// ── Selected product for preview ──────────────────────────────────────────
	$: selectedProduct = products.find(p => p.id === newSale.product_id) ?? null;

	$: newSaleTotal = newSale.unit_price && newSale.quantity
		? Number(newSale.unit_price) * Number(newSale.quantity)
		: null;

	$: newSaleProfit = (canSeeCost && newSaleTotal != null && selectedProduct?.cost_price != null)
		? newSaleTotal - selectedProduct.cost_price * Number(newSale.quantity) - (Number(newSale.shipping_cost) || 0)
		: null;

	$: noStock = selectedProduct != null && Number(newSale.quantity) > selectedProduct.stock_qty;

	// Auto-fill unit price from product
	function onProductChange() {
		if (selectedProduct?.price_eur != null && !newSale.unit_price) {
			newSale.unit_price = String(selectedProduct.price_eur);
		}
	}

	async function submitNewSale() {
		if (noStock) { formError = 'Stock insufficiente per questo prodotto.'; return; }
		formLoading = true; formError = '';
		try {
			await salesApi.create({
				product_id:   newSale.product_id,
				quantity:     Number(newSale.quantity),
				unit_price_eur: newSale.unit_price ? Number(newSale.unit_price) : null,
				shipping_cost:  newSale.shipping_cost ? Number(newSale.shipping_cost) : null,
				sale_date:    newSale.sale_date || null,
				notes:        newSale.notes || null,
			});
			showNewSale = false;
			newSale = { product_id: '', quantity: 1, unit_price: '', shipping_cost: '', sale_date: today(), notes: '' };
			sales = await salesApi.list();
			products = await productsApi.list();   // refresh stock
		} catch (e) { formError = e.message; }
		finally { formLoading = false; }
	}

	// ── Edit ─────────────────────────────────────────────────────────────────────
	function openEdit(s) {
		editSale = s;
		editForm = {
			quantity:      s.quantity,
			unit_price:    s.unit_price_eur != null ? String(s.unit_price_eur) : '',
			shipping_cost: s.shipping_cost != null ? String(s.shipping_cost) : '',
			sale_date:     s.sale_date,
			notes:         s.notes ?? '',
		};
		editError = '';
		showEdit = true;
	}

	async function submitEdit() {
		editLoading = true; editError = '';
		try {
			const hasPrice = editForm.unit_price !== '';
			await salesApi.update(editSale.id, {
				quantity:      Number(editForm.quantity),
				unit_price_eur: hasPrice ? Number(editForm.unit_price) : null,
				shipping_cost:  editForm.shipping_cost ? Number(editForm.shipping_cost) : null,
				clear_price:   !hasPrice,
				sale_date:     editForm.sale_date || null,
				notes:         editForm.notes || null,
			});
			showEdit = false;
			sales = await salesApi.list();
		} catch (e) { editError = e.message; }
		finally { editLoading = false; }
	}

	// ── Delete ────────────────────────────────────────────────────────────────────
	function openDelete(s) {
		saleToDelete = s;
		deleteError = '';
		showDeleteConfirm = true;
	}

	async function confirmDelete() {
		deleteLoading = true; deleteError = '';
		try {
			await salesApi.delete(saleToDelete.id);
			showDeleteConfirm = false;
			saleToDelete = null;
			sales = await salesApi.list();
		} catch (e) { deleteError = e.message; }
		finally { deleteLoading = false; }
	}

	// ── Formatting ───────────────────────────────────────────────────────────────
	function fmtDate(d) {
		if (!d) return '—';
		return new Date(d).toLocaleDateString('it-IT');
	}
	function fmtEur(n) {
		if (n == null) return '—';
		return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(n);
	}
	function productName(id) {
		return products.find(p => p.id === id)?.name ?? id;
	}
	function profitClass(profit) {
		if (profit == null) return '';
		return profit >= 0 ? 'profit-pos' : 'profit-neg';
	}
</script>

<svelte:head><title>Vendite — MEDIC</title></svelte:head>

<div class="page-header">
	<h1 class="page-title">Vendite</h1>
	<button class="btn btn-primary" on:click={() => { showNewSale = true; formError = ''; newSale.product_id = products[0]?.id ?? ''; }}>
		+ Registra vendita
	</button>
</div>

<!-- Filters -->
<div class="filters card" style="margin-bottom:1.25rem">
	<div class="filters-row">
		<div class="form-group" style="margin:0">
			<label class="form-label">Dal</label>
			<input class="form-input" type="date" bind:value={filterFrom} />
		</div>
		<div class="form-group" style="margin:0">
			<label class="form-label">Al</label>
			<input class="form-input" type="date" bind:value={filterTo} />
		</div>
		<button class="btn btn-outline" style="align-self:flex-end" on:click={applyFilters}>Filtra</button>
		<button class="btn btn-outline" style="align-self:flex-end" on:click={() => { filterFrom=''; filterTo=''; applyFilters(); }}>Reset</button>
	</div>
</div>

{#if loading}
	<div style="color:var(--c-muted);display:flex;gap:.5rem;align-items:center"><span class="spinner"></span> Caricamento...</div>
{:else if error}
	<div class="alert alert-error">{error}</div>
{:else if sales.length === 0}
	<div class="empty-state">Nessuna vendita registrata.</div>
{:else}
	<div class="card">
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>Data</th>
						<th>Prodotto</th>
						<th>Agente</th>
						<th>Qtà</th>
						<th>Prezzo unit.</th>
						<th>Totale</th>
						{#if canSeeCost}<th>Profitto</th>{/if}
						<th>Note</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each sales as s}
						<tr>
							<td data-label="Data">{fmtDate(s.sale_date ?? s.created_at)}</td>
							<td data-label="Prodotto"><strong>{s.product_name ?? productName(s.product_id)}</strong></td>
							<td data-label="Agente" style="font-size:.82rem;color:var(--c-muted)">{s.agent_name ?? '—'}</td>
							<td data-label="Qtà">{s.quantity}</td>
							<td data-label="Prezzo unit.">{fmtEur(s.unit_price_eur ?? s.unit_price)}</td>
							<td data-label="Totale">{s.total_eur != null ? fmtEur(s.total_eur) : '—'}</td>
							{#if canSeeCost}
								<td data-label="Profitto" class={profitClass(s.profit)}>
									{s.profit != null ? fmtEur(s.profit) : '—'}
								</td>
							{/if}
							<td data-label="Note" style="color:var(--c-muted);font-size:.8rem">{s.notes ?? ''}</td>
							<td class="actions-cell">
								<div style="display:flex;gap:.35rem;justify-content:flex-end">
									<button class="btn btn-outline btn-sm" title="Modifica" on:click={() => openEdit(s)}>✏️</button>
									<button class="btn btn-delete-outline btn-sm" title="Storna" on:click={() => openDelete(s)}>
										<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
											<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/>
										</svg>
									</button>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{/if}

<!-- ── Modal: Nuova vendita ── -->
{#if showNewSale}
	<div class="modal-backdrop" on:click|self={() => showNewSale = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Registra vendita</h3>
			{#if formError}<div class="alert alert-error">{formError}</div>{/if}
			<form on:submit|preventDefault={submitNewSale}>
				<div class="form-group">
					<label class="form-label">Prodotto *</label>
					<select class="form-input" bind:value={newSale.product_id} on:change={onProductChange} required>
						<option value="">— seleziona —</option>
						{#each products as p}
							<option value={p.id} disabled={p.stock_qty <= 0}>
								{p.name} — stock: {p.stock_qty} {p.unit}{p.stock_qty <= 0 ? ' (ESAURITO)' : ''}
							</option>
						{/each}
					</select>
				</div>

				{#if noStock}
					<div class="alert alert-error" style="margin-bottom:.75rem">
						⚠️ Stock insufficiente: disponibili {selectedProduct?.stock_qty ?? 0}, richiesti {newSale.quantity}
					</div>
				{/if}

				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Quantità *</label>
						<input class="form-input" type="number" min="1" bind:value={newSale.quantity} required />
					</div>
					<div class="form-group">
						<label class="form-label">Prezzo unitario (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={newSale.unit_price} placeholder="es. 120.00" />
					</div>
				</div>

				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Spese spedizione (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={newSale.shipping_cost} placeholder="0.00" />
					</div>
					<div class="form-group">
						<label class="form-label">Data vendita</label>
						<input class="form-input" type="date" bind:value={newSale.sale_date} />
					</div>
				</div>

				{#if canSeeCost && selectedProduct && newSaleTotal != null}
					<div class="profit-preview">
						<div class="profit-row"><span>Totale ricavo</span><strong>{fmtEur(newSaleTotal)}</strong></div>
						{#if selectedProduct.cost_price != null}
							<div class="profit-row"><span>Costo prodotto</span><span>− {fmtEur(selectedProduct.cost_price * Number(newSale.quantity))}</span></div>
						{/if}
						{#if newSale.shipping_cost}
							<div class="profit-row"><span>Spedizione</span><span>− {fmtEur(Number(newSale.shipping_cost))}</span></div>
						{/if}
						{#if newSaleProfit != null}
							<div class="profit-row profit-total"><span>Margine stimato</span><strong class={newSaleProfit >= 0 ? 'profit-pos' : 'profit-neg'}>{fmtEur(newSaleProfit)}</strong></div>
						{/if}
					</div>
				{/if}

				<div class="form-group">
					<label class="form-label">Note</label>
					<input class="form-input" bind:value={newSale.notes} placeholder="opzionale" />
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showNewSale = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={formLoading || !newSale.product_id || noStock}>
						{formLoading ? 'Salvataggio...' : 'Registra'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<!-- ── Modal: Modifica vendita ── -->
{#if showEdit && editSale}
	<div class="modal-backdrop" on:click|self={() => showEdit = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Modifica vendita</h3>
			<p style="font-size:.83rem;color:var(--c-muted);margin-top:-.75rem;margin-bottom:1rem">
				{editSale.product_name ?? productName(editSale.product_id)} — {fmtDate(editSale.sale_date)}
			</p>
			{#if editError}<div class="alert alert-error">{editError}</div>{/if}
			<form on:submit|preventDefault={submitEdit}>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Quantità *</label>
						<input class="form-input" type="number" min="1" bind:value={editForm.quantity} required />
					</div>
					<div class="form-group">
						<label class="form-label">Prezzo unitario (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={editForm.unit_price} placeholder="es. 120.00" />
					</div>
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Spese spedizione (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={editForm.shipping_cost} placeholder="0.00" />
					</div>
					<div class="form-group">
						<label class="form-label">Data vendita</label>
						<input class="form-input" type="date" bind:value={editForm.sale_date} />
					</div>
				</div>
				<div class="form-group">
					<label class="form-label">Note</label>
					<input class="form-input" bind:value={editForm.notes} placeholder="opzionale" />
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showEdit = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={editLoading}>
						{editLoading ? 'Salvataggio...' : 'Salva modifiche'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<!-- ── Modal: Conferma eliminazione ── -->
{#if showDeleteConfirm && saleToDelete}
	<div class="modal-backdrop" on:click|self={() => showDeleteConfirm = false} role="dialog" aria-modal="true">
		<div class="modal modal-danger-border">
			<div class="delete-icon-sale">
				<svg xmlns="http://www.w3.org/2000/svg" width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="var(--c-danger)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/>
				</svg>
			</div>
			<h3 class="modal-title">Storna vendita</h3>
			<p style="font-size:.88rem;margin-bottom:.5rem">Stai per eliminare la vendita:</p>
			<div class="sale-info-box">
				<strong>{saleToDelete.product_name ?? productName(saleToDelete.product_id)}</strong>
				<span>× {saleToDelete.quantity}</span>
				<span>{fmtDate(saleToDelete.sale_date)}</span>
				{#if saleToDelete.total_eur != null}
					<span>{fmtEur(saleToDelete.total_eur)}</span>
				{/if}
			</div>
			<p style="font-size:.82rem;color:var(--c-muted);margin-top:.75rem">
				⚠️ Lo stock del prodotto verrà ripristinato automaticamente.
			</p>
			{#if deleteError}<div class="alert alert-error" style="margin-top:.5rem">{deleteError}</div>{/if}
			<div class="modal-actions">
				<button class="btn btn-outline" on:click={() => showDeleteConfirm = false}>Annulla</button>
				<button class="btn btn-danger" disabled={deleteLoading} on:click={confirmDelete}>
					{#if deleteLoading}<span class="spinner" style="width:.85rem;height:.85rem;border-width:2px"></span>{/if}
					Storna e elimina
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
.filters-row { display: flex; gap: .75rem; align-items: flex-end; flex-wrap: wrap; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
.actions-cell { white-space: nowrap; width: 1%; }
.profit-pos { color: #16a34a; font-weight: 600; }
.profit-neg { color: var(--c-danger); font-weight: 600; }
.profit-preview {
	background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.09);
	border-radius: 8px; padding: .75rem 1rem; margin-bottom: 1rem; font-size: .875rem;
}
.profit-row { display: flex; justify-content: space-between; align-items: center; padding: .2rem 0; color: var(--c-muted); }
.profit-total { border-top: 1px solid rgba(255,255,255,.1); margin-top: .3rem; padding-top: .4rem; color: var(--c-text); font-weight: 600; }

.modal-backdrop {
	position: fixed; inset: 0;
	background: rgba(0,0,0,.45);
	display: flex; align-items: center; justify-content: center;
	z-index: 100; padding: 1rem;
}
.modal {
	background: var(--c-surface);
	border-radius: 12px;
	padding: 1.75rem;
	width: 100%; max-width: 460px;
	box-shadow: 0 20px 60px rgba(0,0,0,.25);
}
.modal-danger-border { border-top: 4px solid var(--c-danger); }
.modal-title { font-size: 1.05rem; font-weight: 700; margin-bottom: 1.25rem; }
.modal-actions { display: flex; gap: .75rem; justify-content: flex-end; margin-top: 1.5rem; }

.delete-icon-sale { text-align: center; margin-bottom: .75rem; }

.sale-info-box {
	display: flex; flex-wrap: wrap; gap: .5rem; align-items: center;
	background: rgba(239,68,68,.07);
	border: 1px solid rgba(239,68,68,.2);
	border-radius: 8px; padding: .6rem 1rem;
	font-size: .9rem;
}

.btn-delete-outline {
	background: #fff; color: var(--c-danger);
	border: 1.5px solid var(--c-danger);
	display: inline-flex; align-items: center; justify-content: center;
	padding: .3rem .45rem;
}
.btn-delete-outline:hover { background: rgba(239,68,68,.08); }
.btn-danger {
	background: var(--c-danger); color: #fff; border-color: var(--c-danger);
	font-weight: 600; display: inline-flex; align-items: center; gap: .4rem;
}
.btn-danger:hover:not(:disabled) { opacity: .85; }
.btn-danger:disabled { opacity: .4; cursor: not-allowed; }
</style>
