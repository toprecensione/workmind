<script>
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/api.js';

	// ── State ─────────────────────────────────────────────────────────────────────
	let users = [];
	let org = { name: '', sector: '' };
	let loading = true;
	let error = '';
	let success = '';

	// Filters
	let filterRole = '';
	let filterStatus = '';
	let filterSearch = '';

	// Drawer
	let drawerOpen = false;
	let drawerMode = 'create'; // 'create' | 'edit'
	let drawerUser = { email: '', display_name: '', role: 'user', password: '' };
	let drawerError = '';
	let drawerLoading = false;

	// Reset password modal
	let resetModalOpen = false;
	let resetPassword = '';
	let resetCopied = false;

	// Org section
	let orgOpen = false;
	let orgLoading = false;
	let orgError = '';
	let orgSuccess = '';

	// Current user id (from JWT)
	let currentUserId = null;

	// ── JWT decode ────────────────────────────────────────────────────────────────
	function getJwtPayload(token) {
		try {
			const parts = token.split('.');
			if (parts.length !== 3) return null;
			const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
			const padded = payload + '=='.slice(0, (4 - payload.length % 4) % 4);
			return JSON.parse(atob(padded));
		} catch {
			return null;
		}
	}

	// ── Helpers ───────────────────────────────────────────────────────────────────
	function formatDate(iso) {
		if (!iso) return '—';
		try {
			return new Intl.DateTimeFormat('it-IT', {
				day: '2-digit', month: '2-digit', year: 'numeric',
				hour: '2-digit', minute: '2-digit'
			}).format(new Date(iso));
		} catch {
			return iso;
		}
	}

	function getInitials(user) {
		if (user.display_name) {
			return user.display_name.split(' ').map(p => p[0]).join('').toUpperCase().slice(0, 2);
		}
		if (user.email) return user.email[0].toUpperCase();
		return '?';
	}

	function roleBadgeClass(role) {
		return {
			admin: 'role-badge-admin',
			supervisor: 'role-badge-supervisor',
			agent: 'role-badge-agent',
			user: 'role-badge-user',
		}[role] ?? 'role-badge-user';
	}

	function roleLabel(role) {
		return {
			admin: 'Admin',
			supervisor: 'Supervisor',
			agent: 'Agente',
			user: 'Utente',
		}[role] ?? role;
	}

	function clearMessages() {
		error = '';
		success = '';
	}

	// ── Load data ─────────────────────────────────────────────────────────────────
	async function loadUsers() {
		loading = true;
		error = '';
		try {
			const params = {};
			if (filterRole) params.role = filterRole;
			if (filterStatus === 'active') params.is_active = 'true';
			if (filterStatus === 'inactive') params.is_active = 'false';
			if (filterSearch) params.search = filterSearch;
			users = await adminApi.listUsers(params);
		} catch (e) {
			error = e.message || 'Errore nel caricamento utenti';
		} finally {
			loading = false;
		}
	}

	async function loadOrg() {
		try {
			const data = await adminApi.getOrg();
			org = { name: data.name ?? '', sector: data.sector ?? '' };
		} catch {
			// non-fatal
		}
	}

	let _debounce;
	function onFilterChange() {
		clearTimeout(_debounce);
		_debounce = setTimeout(() => loadUsers(), 350);
	}

	onMount(async () => {
		const token = localStorage.getItem('wm_access');
		if (token) {
			const payload = getJwtPayload(token);
			currentUserId = payload?.sub ?? payload?.user_id ?? null;
		}
		await Promise.all([loadUsers(), loadOrg()]);
	});

	// ── Drawer actions ────────────────────────────────────────────────────────────
	function openCreateDrawer() {
		drawerMode = 'create';
		drawerUser = { email: '', display_name: '', role: 'user', password: '' };
		drawerError = '';
		drawerOpen = true;
	}

	function openEditDrawer(user) {
		drawerMode = 'edit';
		drawerUser = {
			id: user.id,
			email: user.email,
			display_name: user.display_name ?? '',
			role: user.role ?? 'user',
			password: ''
		};
		drawerError = '';
		drawerOpen = true;
	}

	function closeDrawer() {
		drawerOpen = false;
	}

	async function saveUser() {
		drawerLoading = true;
		drawerError = '';
		try {
			if (drawerMode === 'create') {
				const payload = {
					email: drawerUser.email,
					display_name: drawerUser.display_name,
					role: drawerUser.role,
				};
				if (drawerUser.password) payload.password = drawerUser.password;
				await adminApi.createUser(payload);
				success = 'Utente creato con successo.';
			} else {
				const payload = {
					display_name: drawerUser.display_name,
					role: drawerUser.role,
				};
				await adminApi.updateUser(drawerUser.id, payload);
				success = 'Utente aggiornato.';
			}
			drawerOpen = false;
			await loadUsers();
		} catch (e) {
			drawerError = e.message || 'Errore nel salvataggio';
		} finally {
			drawerLoading = false;
		}
	}

	// ── Reset password ────────────────────────────────────────────────────────────
	async function handleResetPassword(user) {
		clearMessages();
		try {
			const res = await adminApi.resetPassword(user.id);
			resetPassword = res.new_password ?? res.password ?? '';
			resetCopied = false;
			resetModalOpen = true;
		} catch (e) {
			error = e.message || 'Errore nel reset password';
		}
	}

	async function copyResetPassword() {
		try {
			await navigator.clipboard.writeText(resetPassword);
			resetCopied = true;
			setTimeout(() => { resetCopied = false; }, 2000);
		} catch {
			resetCopied = false;
		}
	}

	function closeResetModal() {
		resetModalOpen = false;
		resetPassword = '';
	}

	// ── Activate / Deactivate ─────────────────────────────────────────────────────
	async function toggleActive(user) {
		clearMessages();
		try {
			if (user.is_active) {
				await adminApi.deactivateUser(user.id);
				success = `${user.display_name || user.email} disattivato.`;
			} else {
				await adminApi.activateUser(user.id);
				success = `${user.display_name || user.email} attivato.`;
			}
			await loadUsers();
		} catch (e) {
			error = e.message || 'Errore nel cambio stato';
		}
	}

	// ── Delete ────────────────────────────────────────────────────────────────────
	async function deleteUser(user) {
		const name = user.display_name || user.email;
		if (!confirm(`Sei sicuro di voler eliminare ${name}?`)) return;
		clearMessages();
		try {
			await adminApi.deleteUser(user.id);
			success = `${name} eliminato.`;
			await loadUsers();
		} catch (e) {
			error = e.message || 'Errore nell\'eliminazione';
		}
	}

	// ── Org save ──────────────────────────────────────────────────────────────────
	async function saveOrg() {
		orgLoading = true;
		orgError = '';
		orgSuccess = '';
		try {
			await adminApi.updateOrg({ name: org.name, sector: org.sector });
			orgSuccess = 'Impostazioni salvate.';
		} catch (e) {
			orgError = e.message || 'Errore nel salvataggio';
		} finally {
			orgLoading = false;
		}
	}
</script>

<!-- ── Reset Password Modal ───────────────────────────────────────────────────── -->
{#if resetModalOpen}
	<div class="modal-overlay" on:click|self={closeResetModal} role="dialog" aria-modal="true">
		<div class="modal">
			<div class="modal-header">
				<span>Password reimpostata</span>
				<button class="drawer-close" on:click={closeResetModal} aria-label="Chiudi">✕</button>
			</div>
			<div class="modal-body">
				<p class="modal-warning">
					⚠️ Comunicare questa password all'utente. Non verrà mostrata di nuovo.
				</p>
				<div class="form-group" style="margin-bottom:.5rem">
					<label class="form-label">Nuova password</label>
					<div class="copy-input-wrapper">
						<input class="form-input" type="text" readonly value={resetPassword} style="flex:1;font-family:monospace" />
						<button class="btn btn-outline btn-sm" on:click={copyResetPassword}>
							{resetCopied ? '✓ Copiato' : 'Copia'}
						</button>
					</div>
				</div>
			</div>
			<div class="modal-footer">
				<button class="btn btn-primary" on:click={closeResetModal}>Fatto</button>
			</div>
		</div>
	</div>
{/if}

<!-- ── Drawer crea/modifica utente ───────────────────────────────────────────── -->
{#if drawerOpen}
	<div class="drawer-overlay" on:click={closeDrawer} role="presentation"></div>
	<aside class="drawer" role="dialog" aria-modal="true" aria-label={drawerMode === 'create' ? 'Nuovo utente' : 'Modifica utente'}>
		<div class="drawer-header">
			<span>{drawerMode === 'create' ? 'Nuovo Utente' : 'Modifica Utente'}</span>
			<button class="drawer-close" on:click={closeDrawer} aria-label="Chiudi">✕</button>
		</div>

		{#if drawerError}
			<div class="alert alert-error">{drawerError}</div>
		{/if}

		<div class="form-group">
			<label class="form-label" for="d-email">Email *</label>
			<input
				id="d-email"
				class="form-input"
				type="email"
				bind:value={drawerUser.email}
				readonly={drawerMode === 'edit'}
				required
				placeholder="utente@esempio.com"
			/>
		</div>

		<div class="form-group">
			<label class="form-label" for="d-name">Nome visualizzato</label>
			<input
				id="d-name"
				class="form-input"
				type="text"
				bind:value={drawerUser.display_name}
				placeholder="Nome Cognome"
			/>
		</div>

		<div class="form-group">
			<label class="form-label" for="d-role">Ruolo</label>
			<select id="d-role" class="form-input" bind:value={drawerUser.role}>
				<option value="user">Utente</option>
				<option value="agent">Agente</option>
				<option value="supervisor">Supervisor</option>
				<option value="admin">Admin</option>
			</select>
		</div>

		{#if drawerMode === 'create'}
			<div class="form-group">
				<label class="form-label" for="d-password">Password</label>
				<input
					id="d-password"
					class="form-input"
					type="password"
					bind:value={drawerUser.password}
					placeholder="Lascia vuoto per generare automaticamente"
					autocomplete="new-password"
				/>
				<span style="font-size:.75rem;color:var(--c-muted)">Lascia vuoto per generare automaticamente</span>
			</div>
		{/if}

		<div style="display:flex;gap:.75rem;margin-top:.5rem">
			<button class="btn btn-primary" on:click={saveUser} disabled={drawerLoading}>
				{#if drawerLoading}<span class="spinner"></span>{/if}
				{drawerMode === 'create' ? 'Crea Utente' : 'Salva'}
			</button>
			<button class="btn btn-outline" on:click={closeDrawer} disabled={drawerLoading}>Annulla</button>
		</div>
	</aside>
{/if}

<!-- ── Main page ──────────────────────────────────────────────────────────────── -->
<div class="page-header">
	<div>
		<h1 class="page-title">Gestione Utenti</h1>
		<p class="page-subtitle" style="color:var(--c-muted);font-size:.85rem;margin-top:.2rem">
			Gestisci gli utenti e i permessi dell'organizzazione
		</p>
	</div>
	<button class="btn btn-primary" on:click={openCreateDrawer}>
		<svg viewBox="0 0 20 20" fill="currentColor" style="width:1rem;height:1rem"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
		Nuovo Utente
	</button>
</div>

{#if error}
	<div class="alert alert-error">{error}</div>
{/if}
{#if success}
	<div class="alert alert-success">{success}</div>
{/if}

<!-- Filters -->
<div class="users-filters card" style="margin-bottom:1rem">
	<div class="users-filters-inner">
		<input
			class="form-input"
			type="search"
			placeholder="Cerca per nome o email…"
			bind:value={filterSearch}
			on:input={onFilterChange}
			style="min-width:200px;flex:1"
		/>
		<select class="form-input" bind:value={filterRole} on:change={onFilterChange} style="min-width:140px">
			<option value="">Tutti i ruoli</option>
			<option value="admin">Admin</option>
			<option value="supervisor">Supervisor</option>
			<option value="agent">Agente</option>
			<option value="user">Utente</option>
		</select>
		<select class="form-input" bind:value={filterStatus} on:change={onFilterChange} style="min-width:130px">
			<option value="">Tutti gli stati</option>
			<option value="active">Attivi</option>
			<option value="inactive">Inattivi</option>
		</select>
	</div>
</div>

<!-- Users table -->
<div class="card" style="padding:0;overflow:hidden">
	{#if loading}
		<div class="empty-state">
			<span class="spinner" style="width:2rem;height:2rem"></span>
			<p style="margin-top:.75rem">Caricamento utenti…</p>
		</div>
	{:else if users.length === 0}
		<div class="empty-state">
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
				<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"/>
			</svg>
			<p>Nessun utente trovato</p>
		</div>
	{:else}
		<div class="table-wrap">
			<table class="users-table">
				<thead>
					<tr>
						<th>Utente</th>
						<th>Email</th>
						<th>Ruolo</th>
						<th>Stato</th>
						<th>Ultimo accesso</th>
						<th>Azioni</th>
					</tr>
				</thead>
				<tbody>
					{#each users as user (user.id)}
						<tr>
							<td data-label="Utente">
								<div class="user-cell">
									<div class="user-avatar">{getInitials(user)}</div>
									<span class="user-name">{user.display_name || '—'}</span>
								</div>
							</td>
							<td data-label="Email">
								<span style="color:var(--c-muted);font-size:.85rem">{user.email}</span>
							</td>
							<td data-label="Ruolo">
								<span class="badge {roleBadgeClass(user.role)}">{roleLabel(user.role)}</span>
							</td>
							<td data-label="Stato">
								{#if user.is_active}
									<span class="badge badge-ok">🟢 Attivo</span>
								{:else}
									<span class="badge badge-danger">⛔ Disattivato</span>
								{/if}
							</td>
							<td data-label="Ultimo accesso">
								<span style="font-size:.82rem;color:var(--c-muted)">{formatDate(user.last_login)}</span>
							</td>
							<td data-label="Azioni">
								<div class="user-actions">
									<!-- Edit -->
									<button
										class="btn btn-outline btn-sm"
										title="Modifica"
										on:click={() => openEditDrawer(user)}
									>
										<svg viewBox="0 0 20 20" fill="currentColor" style="width:.85rem;height:.85rem"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
									</button>
									<!-- Reset password -->
									<button
										class="btn btn-outline btn-sm"
										title="Reset password"
										on:click={() => handleResetPassword(user)}
									>
										🔑
									</button>
									<!-- Toggle active -->
									<label class="toggle-switch" title={user.is_active ? 'Disattiva' : 'Attiva'}>
										<input
											type="checkbox"
											checked={user.is_active}
											on:change={() => toggleActive(user)}
										/>
										<span class="toggle-slider"></span>
									</label>
									<!-- Delete (disabled for self) -->
									{#if String(user.id) !== String(currentUserId)}
										<button
											class="btn btn-danger btn-sm"
											title="Elimina"
											on:click={() => deleteUser(user)}
										>
											🗑️
										</button>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<!-- ── Org settings card (collapsible) ───────────────────────────────────────── -->
<div class="org-card" style="margin-top:1.5rem">
	<button class="org-card-toggle" on:click={() => { orgOpen = !orgOpen; orgError=''; orgSuccess=''; }}>
		<div style="display:flex;align-items:center;gap:.6rem">
			<svg viewBox="0 0 20 20" fill="currentColor" style="width:1.1rem;height:1.1rem;color:var(--c-gold)">
				<path fill-rule="evenodd" d="M4 4a2 2 0 012-2h8a2 2 0 012 2v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4zm3 1h2v2H7V5zm2 4H7v2h2V9zm2-4h2v2h-2V5zm2 4h-2v2h2V9z" clip-rule="evenodd"/>
			</svg>
			<span style="font-weight:600">Impostazioni Organizzazione</span>
		</div>
		<svg viewBox="0 0 20 20" fill="currentColor" style="width:1rem;height:1rem;transition:transform .2s;transform:rotate({orgOpen ? 180 : 0}deg)">
			<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
		</svg>
	</button>

	{#if orgOpen}
		<div class="org-card-body">
			{#if orgError}
				<div class="alert alert-error">{orgError}</div>
			{/if}
			{#if orgSuccess}
				<div class="alert alert-success">{orgSuccess}</div>
			{/if}

			<div class="form-group">
				<label class="form-label" for="org-name">Nome organizzazione</label>
				<input id="org-name" class="form-input" type="text" bind:value={org.name} placeholder="Es. Studio Medic" />
			</div>

			<div class="form-group">
				<label class="form-label" for="org-sector">Settore</label>
				<input id="org-sector" class="form-input" type="text" bind:value={org.sector} placeholder="Es. Medicina Estetica" />
			</div>

			<button class="btn btn-primary" on:click={saveOrg} disabled={orgLoading}>
				{#if orgLoading}<span class="spinner"></span>{/if}
				Salva impostazioni
			</button>
		</div>
	{/if}
</div>

<style>
/* Filters bar */
.users-filters { padding: .75rem 1rem; }
.users-filters-inner {
	display: flex;
	gap: .6rem;
	flex-wrap: wrap;
	align-items: center;
}

/* User cell */
.user-cell { display: flex; align-items: center; gap: .65rem; }
.user-name { font-weight: 500; }

/* Actions */
.user-actions {
	display: flex;
	align-items: center;
	gap: .4rem;
	flex-wrap: wrap;
}

/* Modal */
.modal-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	font-weight: 600;
	font-size: 1.05rem;
	margin-bottom: 1rem;
}
.modal-body { margin-bottom: 1rem; }
.modal-footer { display: flex; justify-content: flex-end; }
.modal-warning {
	font-size: .85rem;
	background: var(--c-warn-bg);
	color: var(--c-warn);
	padding: .6rem .85rem;
	border-radius: var(--radius);
	margin-bottom: 1rem;
}

/* Org card */
.org-card-toggle {
	display: flex;
	align-items: center;
	justify-content: space-between;
	width: 100%;
	background: none;
	border: none;
	cursor: pointer;
	padding: 0;
	color: var(--c-text);
}
.org-card-body {
	margin-top: 1rem;
	padding-top: 1rem;
	border-top: 1px solid var(--c-border);
}

@media (max-width: 640px) {
	.users-filters-inner { flex-direction: column; align-items: stretch; }
	.user-actions { gap: .25rem; }
}
</style>
