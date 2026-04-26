<script>
	import { onMount } from 'svelte';
	import { agentWarehouseApi, productsApi, adminApi } from '$lib/api.js';
	import { auth } from '$lib/stores.js';

	$: role = $auth.user?.role ?? 'user';
	$: isAgent = role === 'agent';
	$: isSupervisor = role === 'admin' || role === 'supervisor';

	let allAllocations = [];  // full list (supervisor)
	let movements = [];
	let products = [];
	let agents = [];
	let loading = true;
	let error = '';

	// Agent filter (supervisor/admin only)
	let selectedAgentId = '';   // '' = all agents

	// Tab
	let activeTab = 'stock';  // 'stock' | 'movements'

	// Allocate modal
	let showAllocate = false;
	let allocForm = { agent_id: '', product_id: '', quantity: 1, notes: '' };
	let allocLoading = false;
	let allocError = '';

	// Return modal
	let showReturn = false;
	let retForm = { agent_id: '', product_id: '', quantity: 1, notes: '' };
	let retLoading = false;
	let retError = '';

	onMount(load);

	async function load() {
		loading = true; error = '';
		try {
			if (isAgent) {
				allAllocations = await agentWarehouseApi.myStock();
			} else {
				[allAllocations, movements, products] = await Promise.all([
					agentWarehouseApi.allocations(),
					agentWarehouseApi.movements(),
					productsApi.list(),
				]);
				try {
					const users = await adminApi.listUsers({});
					agents = users.filter(u => u.role === 'agent' && u.is_active);
				} catch {}
			}
		} catch (e) { error = e.message; }
		finally { loading = false; }
	}

	// ── Filtered views ────────────────────────────────────────────────────────
	$: filteredAllocations = (isSupervisor && selectedAgentId)
		? allAllocations.filter(a => a.agent_id === selectedAgentId)
		: allAllocations;

	$: filteredMovements = (isSupervisor && selectedAgentId)
		? movements.filter(m => m.agent_id === selectedAgentId)
		: movements;

	$: selectedAgentName = agents.find(a => a.id === selectedAgentId)?.display_name
		|| agents.find(a => a.id === selectedAgentId)?.email
		|| '';

	// ── Allocate ──────────────────────────────────────────────────────────────
	async function submitAllocate() {
		allocLoading = true; allocError = '';
		try {
			await agentWarehouseApi.allocate({
				agent_id:   allocForm.agent_id,
				product_id: allocForm.product_id,
				quantity:   Number(allocForm.quantity),
				notes:      allocForm.notes || null,
			});
			showAllocate = false;
			allocForm = { agent_id: '', product_id: '', quantity: 1, notes: '' };
			await load();
		} catch (e) { allocError = e.message; }
		finally { allocLoading = false; }
	}

	// ── Return ────────────────────────────────────────────────────────────────
	async function submitReturn() {
		retLoading = true; retError = '';
		try {
			await agentWarehouseApi.return_({
				agent_id:   retForm.agent_id,
				product_id: retForm.product_id,
				quantity:   Number(retForm.quantity),
				notes:      retForm.notes || null,
			});
			showReturn = false;
			retForm = { agent_id: '', product_id: '', quantity: 1, notes: '' };
			await load();
		} catch (e) { retError = e.message; }
		finally { retLoading = false; }
	}

	// ── Formatting ────────────────────────────────────────────────────────────
	function fmtDate(d) {
		if (!d) return '—';
		return new Date(d).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
	}
	function movTypeLabel(t) {
		return { allocate: '↓ Allocazione', return: '↑ Reso', sale: '→ Vendita', correction: '~ Rettifica' }[t] ?? t;
	}
	function movTypeClass(t) {
		return { allocate: 'mov-in', return: 'mov-out', sale: 'mov-sale', correction: 'mov-corr' }[t] ?? '';
	}
</script>

<svelte:head><title>Magazzino Agenti — MEDIC</title></svelte:head>

<div class="page-header">
	<h1 class="page-title">
		{#if isAgent}
			Il mio magazzino
		{:else if selectedAgentId && selectedAgentName}
			Mag. {selectedAgentName}
		{:else}
			Magazzino Agenti
		{/if}
	</h1>
	{#if isSupervisor}
		<div style="display:flex;gap:.5rem">
			<button class="btn btn-primary" on:click={() => { showAllocate = true; allocError = ''; }}>
				+ Alloca
			</button>
			<button class="btn btn-outline" on:click={() => { showReturn = true; retError = ''; }}>
				↑ Reso
			</button>
		</div>
	{/if}
</div>

{#if isSupervisor}
	<!-- Agent selector + tabs in one bar -->
	<div class="control-bar">
		<div class="agent-selector-wrap">
			<label class="selector-label">Agente</label>
			<select class="form-input selector-select" bind:value={selectedAgentId}>
				<option value="">— Tutti gli agenti —</option>
				{#each agents as a}
					<option value={a.id}>{a.display_name || a.email}</option>
				{/each}
			</select>
		</div>
		<div class="tabs">
			<button class="tab-btn" class:active={activeTab==='stock'}     on:click={() => activeTab='stock'}>Stock</button>
			<button class="tab-btn" class:active={activeTab==='movements'} on:click={() => activeTab='movements'}>Movimenti</button>
		</div>
	</div>
{/if}

{#if loading}
	<div style="color:var(--c-muted);display:flex;gap:.5rem;align-items:center"><span class="spinner"></span> Caricamento...</div>
{:else if error}
	<div class="alert alert-error">{error}</div>
{:else if activeTab === 'stock' || isAgent}

	{#if filteredAllocations.length === 0}
		<div class="empty-state">
			{selectedAgentId ? 'Nessun prodotto allocato a questo agente.' : 'Nessuna allocazione registrata.'}
		</div>
	{:else}
		<div class="card">
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							{#if isSupervisor && !selectedAgentId}<th>Agente</th>{/if}
							<th>Prodotto</th>
							<th>Qtà disponibile</th>
							<th>Aggiornato</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredAllocations as a}
							<tr class:low-stock={a.quantity <= 2}>
								{#if isSupervisor && !selectedAgentId}<td>{a.agent_name}</td>{/if}
								<td>
									<strong>{a.product_name}</strong>
									{#if a.unit}<span style="color:var(--c-muted);font-size:.8rem"> {a.unit}</span>{/if}
								</td>
								<td><strong style="font-size:1.05rem">{a.quantity}</strong></td>
								<td style="color:var(--c-muted);font-size:.82rem">{fmtDate(a.updated_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

{:else}
	<!-- Movements tab -->
	{#if filteredMovements.length === 0}
		<div class="empty-state">
			{selectedAgentId ? 'Nessun movimento per questo agente.' : 'Nessun movimento registrato.'}
		</div>
	{:else}
		<div class="card">
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Data</th>
							{#if !selectedAgentId}<th>Agente</th>{/if}
							<th>Prodotto</th>
							<th>Tipo</th>
							<th>Qtà</th>
							<th>Note</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredMovements as m}
							<tr>
								<td style="font-size:.82rem;color:var(--c-muted)">{fmtDate(m.created_at)}</td>
								{#if !selectedAgentId}<td>{m.agent_name}</td>{/if}
								<td>{m.product_name}</td>
								<td><span class="mov-badge {movTypeClass(m.movement_type)}">{movTypeLabel(m.movement_type)}</span></td>
								<td class={m.quantity > 0 ? 'qty-pos' : 'qty-neg'}>{m.quantity > 0 ? '+' : ''}{m.quantity}</td>
								<td style="color:var(--c-muted);font-size:.8rem">{m.notes ?? ''}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
{/if}

<!-- ── Modal: Alloca ── -->
{#if showAllocate}
	<div class="modal-backdrop" on:click|self={() => showAllocate = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Alloca prodotti ad agente</h3>
			{#if allocError}<div class="alert alert-error">{allocError}</div>{/if}
			<form on:submit|preventDefault={submitAllocate}>
				<div class="form-group">
					<label class="form-label">Agente *</label>
					<select class="form-input" bind:value={allocForm.agent_id} required>
						<option value="">— seleziona agente —</option>
						{#each agents as a}
							<option value={a.id}>{a.display_name || a.email}</option>
						{/each}
					</select>
				</div>
				<div class="form-group">
					<label class="form-label">Prodotto *</label>
					<select class="form-input" bind:value={allocForm.product_id} required>
						<option value="">— seleziona prodotto —</option>
						{#each products as p}
							<option value={p.id}>{p.name} (stock centrale: {p.stock_qty})</option>
						{/each}
					</select>
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Quantità *</label>
						<input class="form-input" type="number" min="1" bind:value={allocForm.quantity} required />
					</div>
					<div class="form-group">
						<label class="form-label">Note</label>
						<input class="form-input" bind:value={allocForm.notes} placeholder="opzionale" />
					</div>
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showAllocate = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={allocLoading || !allocForm.agent_id || !allocForm.product_id}>
						{allocLoading ? 'Salvataggio...' : 'Alloca'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<!-- ── Modal: Reso ── -->
{#if showReturn}
	<div class="modal-backdrop" on:click|self={() => showReturn = false} role="dialog" aria-modal="true">
		<div class="modal">
			<h3 class="modal-title">Reso da agente al magazzino centrale</h3>
			{#if retError}<div class="alert alert-error">{retError}</div>{/if}
			<form on:submit|preventDefault={submitReturn}>
				<div class="form-group">
					<label class="form-label">Agente *</label>
					<select class="form-input" bind:value={retForm.agent_id} required>
						<option value="">— seleziona agente —</option>
						{#each agents as a}
							<option value={a.id}>{a.display_name || a.email}</option>
						{/each}
					</select>
				</div>
				<div class="form-group">
					<label class="form-label">Prodotto *</label>
					<select class="form-input" bind:value={retForm.product_id} required>
						<option value="">— seleziona prodotto —</option>
						{#each allAllocations.filter(al => al.agent_id === retForm.agent_id) as al}
							<option value={al.product_id}>{al.product_name} (disponibile: {al.quantity})</option>
						{/each}
					</select>
				</div>
				<div class="form-row">
					<div class="form-group">
						<label class="form-label">Quantità *</label>
						<input class="form-input" type="number" min="1" bind:value={retForm.quantity} required />
					</div>
					<div class="form-group">
						<label class="form-label">Note</label>
						<input class="form-input" bind:value={retForm.notes} placeholder="opzionale" />
					</div>
				</div>
				<div class="modal-actions">
					<button type="button" class="btn btn-outline" on:click={() => showReturn = false}>Annulla</button>
					<button type="submit" class="btn btn-primary" disabled={retLoading || !retForm.agent_id || !retForm.product_id}>
						{retLoading ? 'Salvataggio...' : 'Registra reso'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
.control-bar {
	display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
	background: var(--c-surface); border-radius: 10px; padding: .65rem 1rem;
	margin-bottom: 1rem;
}
.agent-selector-wrap { display: flex; align-items: center; gap: .5rem; flex: 1; min-width: 200px; }
.selector-label { font-size: .75rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--c-muted); white-space: nowrap; }
.selector-select { padding: .3rem .65rem; font-size: .875rem; max-width: 260px; }

.tabs { display: flex; gap: .35rem; }
.tab-btn {
	background: none; border: 1.5px solid var(--c-border); color: var(--c-muted);
	padding: .3rem .85rem; border-radius: 99px; cursor: pointer;
	font: inherit; font-size: .82rem; font-weight: 600; transition: all .15s;
}
.tab-btn:hover { color: var(--c-text); border-color: rgba(255,255,255,.25); }
.tab-btn.active { color: var(--c-gold); border-color: var(--c-gold); }

.low-stock td { background: rgba(239,68,68,.05); }
.qty-pos { color: #16a34a; font-weight: 600; }
.qty-neg { color: var(--c-danger); font-weight: 600; }

.mov-badge {
	display: inline-block; padding: .15rem .5rem;
	border-radius: 4px; font-size: .78rem; font-weight: 600;
}
.mov-in   { background: rgba(34,197,94,.15);  color: #16a34a; }
.mov-out  { background: rgba(251,191,36,.15); color: #b45309; }
.mov-sale { background: rgba(99,102,241,.15); color: #6366f1; }
.mov-corr { background: rgba(156,163,175,.15); color: var(--c-muted); }

.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
.modal-backdrop {
	position: fixed; inset: 0; background: rgba(0,0,0,.45);
	display: flex; align-items: center; justify-content: center;
	z-index: 100; padding: 1rem;
}
.modal {
	background: var(--c-surface); border-radius: 12px; padding: 1.75rem;
	width: 100%; max-width: 460px; box-shadow: 0 20px 60px rgba(0,0,0,.25);
}
.modal-title { font-size: 1.05rem; font-weight: 700; margin-bottom: 1.25rem; }
.modal-actions { display: flex; gap: .75rem; justify-content: flex-end; margin-top: 1.5rem; }
</style>
