<script>
	import { onMount } from 'svelte';
	import { productsApi, lotsApi } from '$lib/api.js';
	import { auth } from '$lib/stores.js';

	let products = [];
	let loading = true;
	let error = '';

	// Role helpers
	$: role = $auth.user?.role ?? 'user';
	$: canSeeCost = role === 'admin' || role === 'supervisor';
	$: canCorrectStock = role === 'admin' || role === 'supervisor';

	// Modal state
	let showNewProduct = false;
	let showAddLot = false;
	let showEditProduct = false;
	let showStockCorrection = false;
	let selectedProduct = null;

	// Forms
	let newProd = { name: '', description: '', unit: 'siringa', price_eur: '', cost_price: '', low_stock_threshold: 5 };
	let newLot  = { lot_number: '', quantity: 1, expiry_date: '' };
	let editProd = {};
	let corrForm = { delta: 0, reason: '' };
	let formLoading = false;
	let formError = '';
	let formSuccess = '';

	onMount(load);

	async function load() {
		loading = true; error = '';
		try { products = await productsApi.list(); }
		catch (e) { error = e.message; }
		finally { loading = false; }
	}

	function stockBadge(p) {
		const s = p.stock_qty;
		const min = p.min_stock_alert ?? 0;
		if (s === 0) return 'badge-danger';
		if (s <= min) return 'badge-warn';
		return 'badge-ok';
	}
	function stockLabel(p) {
		if (p.stock_qty === 0) return 'Esaurito';
		if (p.stock_qty <= (p.min_stock_alert ?? 0)) return 'Basso';
		return 'OK';
	}

	async function submitNewProduct() {
		formLoading = true; formError = '';
		try {
			await productsApi.create({
				name: newProd.name,
				description: newProd.description || null,
				unit: newProd.unit,
				price_eur: newProd.price_eur ? Number(newProd.price_eur) : null,
				cost_price: newProd.cost_price ? Number(newProd.cost_price) : null,
				low_stock_threshold: Number(newProd.low_stock_threshold) || 5,
			});
			formSuccess = 'Prodotto creato.';
			newProd = { name: '', description: '', unit: 'siringa', price_eur: '', cost_price: '', low_stock_threshold: 5 };
			showNewProduct = false;
			await load();
		} catch (e) { formError = e.message; }
		finally { formLoading = false; }
	}

	function openAddLot(p) {
		selectedProduct = p;
		newLot = { lot_number: '', quantity: 1, expiry_date: '' };
		formError = '';
		showAddLot = true;
	}

	async function submitAddLot() {
		formLoading = true; formError = '';
		try {
			const payload = {
				quantity: Number(newLot.quantity),
				lot_number: newLot.lot_number || null,
				expiry_date: newLot.expiry_date || null,
			};
			await lotsApi.addLot(selectedProduct.id, payload);
			showAddLot = false;
			await load();
		} catch (e) { formError = e.message; }
		finally { formLoading = false; }
	}

	function openEdit(p) {
		selectedProduct = p;
		editProd = {
			name: p.name,
			description: p.description ?? '',
			unit: p.unit,
			price_eur: p.price_eur != null ? String(p.price_eur) : '',
			cost_price: p.cost_price != null ? String(p.cost_price) : '',
			low_stock_threshold: p.low_stock_threshold ?? 0,
		};
		formError = '';
		showEditProduct = true;
	}

	async function submitEdit() {
		formLoading = true; formError = '';
		try {
			await productsApi.update(selectedProduct.id, {
				name: editProd.name,
				description: editProd.description || null,
				unit: editProd.unit,
				price_eur: editProd.price_eur ? Number(editProd.price_eur) : null,
				cost_price: editProd.cost_price ? Number(editProd.cost_price) : null,
				low_stock_threshold: Number(editProd.low_stock_threshold) || 0,
			});
			showEditProduct = false;
			await load();
		} catch (e) { formError = e.message; }
		finally { formLoading = false; }
	}

	function openStockCorrection(p) {
		selectedProduct = p;
		corrForm = { delta: 0, reason: '' };
		formError = '';
		showStockCorrection = true;
	}

	async function submitStockCorrection() {
		formLoading = true; formError = '';
		try {
			await productsApi.stockCorrection(selectedProduct.id, {
				delta: Number(corrForm.delta),
				reason: corrForm.reason || null,
			});
			showStockCorrection = false;
			await load();
		} catch (e) { formError = e.message; }
		finally { formLoading = false; }
	}

	// ── Delete con doppia conferma ────────────────────────────────────────────────
	let showDeleteConfirm1 = false;
	let showDeleteConfirm2 = false;
	let deleteConfirmName = '';
	let productToDelete = null;

	function openDelete(p) {
		productToDelete = p;
		deleteConfirmName = '';
		showDeleteConfirm1 = true;
	}

	function proceedToStep2() {
		showDeleteConfirm1 = false;
		showDeleteConfirm2 = true;
	}

	async function confirmDelete() {
		if (deleteConfirmName.trim().toLowerCase() !== productToDelete.name.trim().toLowerCase()) {
			formError = 'Il nome inserito non corrisponde.';
			return;
		}
		formLoading = true; formError = '';
		try {
			await productsApi.delete(productToDelete.id);
			showDeleteConfirm2 = false;
			productToDelete = null;
			formSuccess = 'Prodotto eliminato.';
			await load();
		} catch (e) { formError = e.message; }
		finally { formLoading = false; }
	}
</script>

<svelte:head><title>Prodotti — MEDIC</title></svelte:head>

<div class="page-header">
	<h1 class="page-title">Prodotti & Magazzino</h1>
	<button class="btn btn-primary" on:click={() => { showNewProduct = true; formError = ''; }}>
		+ Nuovo prodotto
	</button>
</div>

{#if loading}
	<div style="color:var(--c-muted);display:flex;gap:.5rem;align-items:center"><span class="spinner"></span> Caricamento...</div>
{:else if error}
	<div class="alert alert-error">{error}</div>
{:else if products.length === 0}
	<div class="empty-state">Nessun prodotto ancora.</div>
{:else}
	<div class="card">
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>Prodotto</th>
						<th>Unità</th>
						<th>Prezzo</th>
						{#if canSeeCost}<th>Costo acq.</th>{/if}
						<th>Stock</th>
						<th>Stato</th>
						<th>Azioni</th>
					</tr>
				</thead>
				<tbody>
					{#each products as p}
						<tr>
							<td>
								<strong>{p.name}</strong>
								{#if p.description}<div style="font-size:.78rem;color:var(--c-muted);margin-top:.1rem">{p.description}</div>{/if}
							</td>
							<td>{p.unit}</td>
							<td>{p.price_eur != null ? '€' + Number(p.price_eur).toFixed(2) : '—'}</td>
							{#if canSeeCost}<td>{p.cost_price != null ? '€' + Number(p.cost_price).toFixed(2) : '—'}</td>{/if}
							<td><strong style="font-size:1.05rem">{p.stock_qty}</strong></td>
							<td><span class="badge {stockBadge(p)}">{stockLabel(p)}</span></td>
							<td>
								<div style="display:flex;gap:.4rem;flex-wrap:wrap">
									<button class="btn btn-outline btn-sm" on:click={() => openAddLot(p)}>+ Carico</button>
									{#if canCorrectStock}
										<button class="btn btn-outline btn-sm" on:click={() => openStockCorrection(p)}>± Storno</button>
									{/if}
									<button class="btn btn-outline btn-sm" on:click={() => openEdit(p)}>Modifica</button>
									<button class="btn btn-delete-outline btn-sm" on:click={() => openDelete(p)} title="Elimina prodotto">
										<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
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

<!-- ── Modal: Nuovo prodotto ── -->
{#if showNewProduct}
	<div class="modal-backdrop" on:click|self={() => showNewProduct = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Nuovo prodotto</h3>
			{#if formError}<div class="alert alert-error">{formError}</div>{/if}
			<form on:submit|preventDefault={submitNewProduct}>
				<div class="form-group">
					<label class="form-label">Nome *</label>
					<input class="form-input" bind:value={newProd.name} required />
				</div>
				<div class="form-group">
					<label class="form-label">Descrizione</label>
					<input class="form-input" bind:value={newProd.description} />
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Prezzo vendita (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={newProd.price_eur} placeholder="0.00" />
					</div>
					{#if canSeeCost}
					<div class="form-group">
						<label class="form-label">Costo acquisto (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={newProd.cost_price} placeholder="0.00" />
					</div>
					{/if}
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Unità</label>
						<select class="form-input" bind:value={newProd.unit}>
							{#each ['siringa','flacone','tubo','pezzo','confezione'] as u}<option>{u}</option>{/each}
						</select>
					</div>
					<div class="form-group">
						<label class="form-label">Alert soglia</label>
						<input class="form-input" type="number" min="0" bind:value={newProd.low_stock_threshold} />
					</div>
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showNewProduct = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={formLoading}>
						{formLoading ? 'Salvataggio...' : 'Crea prodotto'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<!-- ── Modal: Aggiungi lotto ── -->
{#if showAddLot && selectedProduct}
	<div class="modal-backdrop" on:click|self={() => showAddLot = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Carico magazzino — {selectedProduct.name}</h3>
			<p style="font-size:.875rem;color:var(--c-muted);margin-bottom:1rem">Stock attuale: <strong>{selectedProduct.stock_qty} {selectedProduct.unit}</strong></p>
			{#if formError}<div class="alert alert-error">{formError}</div>{/if}
			<form on:submit|preventDefault={submitAddLot}>
				<div class="form-group">
					<label class="form-label">Quantità *</label>
					<input class="form-input" type="number" min="1" bind:value={newLot.quantity} required />
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Numero lotto</label>
						<input class="form-input" bind:value={newLot.lot_number} placeholder="es. LOT-2024-001" />
					</div>
					<div class="form-group">
						<label class="form-label">Data scadenza</label>
						<input class="form-input" type="date" bind:value={newLot.expiry_date} />
					</div>
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showAddLot = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={formLoading}>
						{formLoading ? 'Salvataggio...' : 'Registra carico'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<!-- ── Modal: Modifica prodotto ── -->
{#if showEditProduct && selectedProduct}
	<div class="modal-backdrop" on:click|self={() => showEditProduct = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Modifica — {selectedProduct.name}</h3>
			{#if formError}<div class="alert alert-error">{formError}</div>{/if}
			<form on:submit|preventDefault={submitEdit}>
				<div class="form-group">
					<label class="form-label">Nome *</label>
					<input class="form-input" bind:value={editProd.name} required />
				</div>
				<div class="form-group">
					<label class="form-label">Descrizione</label>
					<input class="form-input" bind:value={editProd.description} />
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Prezzo vendita (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={editProd.price_eur} placeholder="0.00" />
					</div>
					{#if canSeeCost}
					<div class="form-group">
						<label class="form-label">Costo acquisto (€)</label>
						<input class="form-input" type="number" min="0" step="0.01" bind:value={editProd.cost_price} placeholder="0.00" />
					</div>
					{/if}
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Unità</label>
						<select class="form-input" bind:value={editProd.unit}>
							{#each ['siringa','flacone','tubo','pezzo','confezione'] as u}<option>{u}</option>{/each}
						</select>
					</div>
					<div class="form-group">
						<label class="form-label">Alert soglia</label>
						<input class="form-input" type="number" min="0" bind:value={editProd.low_stock_threshold} />
					</div>
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showEditProduct = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={formLoading}>
						{formLoading ? 'Salvataggio...' : 'Salva modifiche'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<!-- ── Modal DELETE step 1: prima conferma ── -->
{#if showDeleteConfirm1 && productToDelete}
	<div class="modal-backdrop" on:click|self={() => showDeleteConfirm1 = false} role="dialog" aria-modal="true">
		<div class="modal modal-danger">
			<div class="delete-icon">
			<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--c-danger)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
				<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/>
			</svg>
		</div>
			<h3 class="modal-title">Elimina prodotto</h3>
			<p style="margin-bottom:.5rem">Stai per eliminare:</p>
			<div class="delete-product-name">{productToDelete.name}</div>
			<ul class="delete-warn-list">
				<li>Il prodotto verrà disattivato dal catalogo</li>
				<li>Lo storico vendite rimarrà intatto</li>
				<li>Il magazzino residuo (<strong>{productToDelete.stock_qty} {productToDelete.unit}</strong>) sarà azzerato</li>
			</ul>
			<p style="font-size:.85rem;color:var(--c-danger);font-weight:600;margin-top:1rem">
				⚠️ Questa operazione è irreversibile.
			</p>
			<div class="modal-actions">
				<button class="btn btn-outline" on:click={() => showDeleteConfirm1 = false}>Annulla</button>
				<button class="btn btn-danger" on:click={proceedToStep2}>Continua →</button>
			</div>
		</div>
	</div>
{/if}

<!-- ── Modal DELETE step 2: conferma con nome ── -->
{#if showDeleteConfirm2 && productToDelete}
	<div class="modal-backdrop" role="dialog" aria-modal="true">
		<div class="modal modal-danger">
			<h3 class="modal-title">Conferma eliminazione definitiva</h3>
			<p style="margin-bottom:1rem;font-size:.875rem">
				Scrivi il nome del prodotto per confermare:
				<br/><strong style="font-size:1rem">{productToDelete.name}</strong>
			</p>
			{#if formError}<div class="alert alert-error">{formError}</div>{/if}
			<input
				class="form-input"
				bind:value={deleteConfirmName}
				placeholder="Nome del prodotto..."
				autocomplete="off"
			/>
			<div class="modal-actions" style="margin-top:1rem">
				<button class="btn btn-outline" on:click={() => { showDeleteConfirm2 = false; showDeleteConfirm1 = true; }}>← Indietro</button>
				<button
					class="btn btn-danger"
					disabled={formLoading || deleteConfirmName.trim().toLowerCase() !== productToDelete.name.trim().toLowerCase()}
					on:click={confirmDelete}
				>
					{formLoading ? 'Eliminazione...' : 'Elimina definitivamente'}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- ── Modal: Rettifica stock ── -->
{#if showStockCorrection && selectedProduct}
	<div class="modal-backdrop" on:click|self={() => showStockCorrection = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Rettifica stock — {selectedProduct.name}</h3>
			<p style="font-size:.875rem;color:var(--c-muted);margin-bottom:1rem">
				Stock attuale: <strong>{selectedProduct.stock_qty} {selectedProduct.unit}</strong>
			</p>
			{#if formError}<div class="alert alert-error">{formError}</div>{/if}
			<form on:submit|preventDefault={submitStockCorrection}>
				<div class="form-group">
					<label class="form-label">Delta (+ carico, − scarico) *</label>
					<input class="form-input" type="number" bind:value={corrForm.delta} required
						placeholder="es. -5 per stornare 5 pezzi" />
					{#if corrForm.delta != 0}
						<div style="font-size:.8rem;margin-top:.3rem;color:var(--c-muted)">
							Nuovo stock: <strong style="color:{selectedProduct.stock_qty + Number(corrForm.delta) < 0 ? 'var(--c-danger)' : 'var(--c-text)'}">
								{selectedProduct.stock_qty + Number(corrForm.delta)}
							</strong>
						</div>
					{/if}
				</div>
				<div class="form-group">
					<label class="form-label">Motivazione</label>
					<input class="form-input" bind:value={corrForm.reason} placeholder="es. prodotto scaduto, danneggiato..." />
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showStockCorrection = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={formLoading || corrForm.delta == 0}>
						{formLoading ? 'Salvataggio...' : 'Applica rettifica'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
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
.modal-title { font-size: 1.05rem; font-weight: 700; margin-bottom: 1.25rem; }
.modal-actions { display: flex; gap: .75rem; justify-content: flex-end; margin-top: 1.5rem; }
.modal-danger { border-top: 4px solid var(--c-danger); }
.delete-icon { text-align: center; margin-bottom: .75rem; line-height: 1; }
.btn-delete-outline {
	background: #fff; color: var(--c-danger);
	border: 1.5px solid var(--c-danger);
	display: inline-flex; align-items: center; justify-content: center;
	padding: .3rem .45rem;
}
.btn-delete-outline:hover:not(:disabled) { background: rgba(239,68,68,.08); }
.delete-product-name {
	background: rgba(239,68,68,.08); border: 1px solid rgba(239,68,68,.25);
	border-radius: 8px; padding: .6rem 1rem; font-weight: 700; font-size: 1rem;
	margin-bottom: 1rem;
}
.delete-warn-list { padding-left: 1.2rem; font-size: .85rem; color: var(--c-muted); line-height: 1.8; margin: 0; }
.btn-danger {
	background: var(--c-danger); color: #fff; border-color: var(--c-danger);
	font-weight: 600;
}
.btn-danger:hover:not(:disabled) { opacity: .85; }
.btn-danger:disabled { opacity: .4; cursor: not-allowed; }
</style>
