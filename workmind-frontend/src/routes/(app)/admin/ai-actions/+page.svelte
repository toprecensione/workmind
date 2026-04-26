<script>
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/api.js';

	let actions = [];
	let users = [];
	let loading = true;
	let loadError = '';

	// Category metadata
	const CATEGORIES = {
		read:    { label: 'Lettura',          icon: '📖', desc: 'Operazioni di sola lettura — il bot consulta i dati senza modificarli.' },
		write:   { label: 'Scrittura',        icon: '✏️', desc: 'Operazioni che modificano dati: vendite, stock, annulli. Richiedono conferma utente.' },
		catalog: { label: 'Gestione catalogo', icon: '📦', desc: 'Operazioni sul catalogo prodotti. Solo per amministratori.' },
	};

	const RISK_LABELS = { low: 'Basso', medium: 'Medio', high: 'Alto' };
	const ALL_ROLES = [
		{ value: 'admin',      label: 'Admin' },
		{ value: 'supervisor', label: 'Supervisor' },
		{ value: 'agent',      label: 'Agente' },
		{ value: 'user',       label: 'Utente' },
	];

	// Per-card UI state
	let expanding = {};    // action_key → bool (show detail panel)
	let saving = {};       // action_key → bool
	let saveMsg = {};      // action_key → string
	// Local editable copies (so we can edit without immediately hitting server)
	let local = {};        // action_key → {enabled, allowed_roles, allowed_user_ids, requires_confirmation, rolesAll, usersAll}

	$: grouped = groupByCategory(actions);

	function groupByCategory(list) {
		const g = {};
		for (const a of list) {
			if (!g[a.category]) g[a.category] = [];
			g[a.category].push(a);
		}
		return g;
	}

	function initLocal(action) {
		local[action.key] = {
			enabled:               action.enabled,
			requires_confirmation: action.requires_confirmation,
			rolesAll:              !action.allowed_roles || action.allowed_roles.length === 0,
			selectedRoles:         action.allowed_roles ? [...action.allowed_roles] : [],
			usersAll:              !action.allowed_user_ids || action.allowed_user_ids.length === 0,
			selectedUsers:         action.allowed_user_ids ? [...action.allowed_user_ids] : [],
		};
	}

	onMount(async () => {
		try {
			[actions, users] = await Promise.all([
				adminApi.listAiActions(),
				adminApi.listAiUsers().catch(() => []),
			]);
			for (const a of actions) initLocal(a);
		} catch (e) {
			loadError = e.message || 'Errore caricamento';
		} finally {
			loading = false;
		}
	});

	function toggleExpand(key) {
		expanding[key] = !expanding[key];
		expanding = expanding;
	}

	function toggleRole(key, val) {
		const l = local[key];
		if (l.selectedRoles.includes(val)) {
			l.selectedRoles = l.selectedRoles.filter(r => r !== val);
		} else {
			l.selectedRoles = [...l.selectedRoles, val];
		}
		local = local;
	}

	function toggleUser(key, uid) {
		const l = local[key];
		if (l.selectedUsers.includes(uid)) {
			l.selectedUsers = l.selectedUsers.filter(u => u !== uid);
		} else {
			l.selectedUsers = [...l.selectedUsers, uid];
		}
		local = local;
	}

	async function saveAction(key) {
		saving[key] = true; saving = saving;
		saveMsg[key] = ''; saveMsg = saveMsg;
		const l = local[key];
		try {
			const payload = {
				enabled:               l.enabled,
				requires_confirmation: l.requires_confirmation,
				clear_roles:           l.rolesAll,
				clear_users:           l.usersAll,
			};
			if (!l.rolesAll) payload.allowed_roles = l.selectedRoles;
			if (!l.usersAll) payload.allowed_user_ids = l.selectedUsers;

			const updated = await adminApi.updateAiAction(key, payload);
			// update actions list
			actions = actions.map(a => a.key === key ? updated : a);
			initLocal(updated);
			saveMsg[key] = '✓ Salvato';
		} catch (e) {
			saveMsg[key] = e.message || 'Errore';
		} finally {
			saving[key] = false; saving = saving;
			saveMsg = saveMsg;
		}
	}

	// Quick toggle enabled without opening panel
	async function quickToggle(key) {
		if (!local[key]) return;
		local[key].enabled = !local[key].enabled;
		local = local;
		await saveAction(key);
	}
</script>

<div class="page-header">
	<div>
		<h1 class="page-title">Permessi AI</h1>
		<p class="page-subtitle">Configura quali operazioni può eseguire il chatbot e per quali ruoli o utenti.</p>
	</div>
</div>

{#if loadError}
	<div class="alert alert-error">{loadError}</div>
{/if}

{#if loading}
	<div class="empty-state"><span class="spinner"></span><p>Caricamento…</p></div>
{:else}
	{#each Object.entries(CATEGORIES) as [catKey, cat]}
		{#if grouped[catKey]?.length}
			<div class="cat-section">
				<div class="cat-header">
					<span class="cat-icon">{cat.icon}</span>
					<div>
						<div class="cat-title">{cat.label}</div>
						<div class="cat-desc">{cat.desc}</div>
					</div>
				</div>

				<div class="action-list">
					{#each grouped[catKey] as action (action.key)}
						{@const l = local[action.key] || {}}
						<div class="action-card" class:action-disabled={!l.enabled}>
							<!-- Card header row -->
							<div class="action-header">
								<div class="action-info">
									<div class="action-name-row">
										<span class="action-name">{action.label}</span>
										<span class="risk-badge risk-{action.risk}">{RISK_LABELS[action.risk]}</span>
										{#if l.requires_confirmation}
											<span class="confirm-badge">⚠️ richiede conferma</span>
										{/if}
									</div>
									<p class="action-desc">{action.description}</p>
									<!-- Roles summary -->
									<div class="roles-summary">
										{#if l.rolesAll}
											<span class="role-chip role-all">Tutti i ruoli</span>
										{:else if l.selectedRoles?.length}
											{#each l.selectedRoles as r}
												<span class="role-chip">{ALL_ROLES.find(x => x.value === r)?.label ?? r}</span>
											{/each}
										{:else}
											<span class="role-chip role-none">Nessun ruolo</span>
										{/if}
										{#if !l.usersAll && l.selectedUsers?.length}
											<span class="role-chip role-user">+{l.selectedUsers.length} utenti specifici</span>
										{/if}
									</div>
								</div>

								<div class="action-controls">
									<!-- Enable/disable toggle -->
									<label class="toggle-switch" title={l.enabled ? 'Disabilita' : 'Abilita'}>
										<input
											type="checkbox"
											checked={l.enabled}
											on:change={() => quickToggle(action.key)}
										/>
										<span class="toggle-slider"></span>
									</label>
									<!-- Expand config button -->
									<button
										class="btn btn-outline btn-sm"
										on:click={() => toggleExpand(action.key)}
									>
										{expanding[action.key] ? '▲ Chiudi' : '⚙️ Configura'}
									</button>
								</div>
							</div>

							<!-- Expandable config panel -->
							{#if expanding[action.key]}
								<div class="action-config">
									<div class="config-grid">
										<!-- Roles column -->
										<div class="config-col">
											<div class="config-col-title">Ruoli abilitati</div>
											<label class="config-check">
												<input
													type="checkbox"
													checked={l.rolesAll}
													on:change={(e) => {
														local[action.key].rolesAll = e.target.checked;
														if (local[action.key].rolesAll) local[action.key].selectedRoles = [];
														local = local;
													}}
												/>
												<strong>Tutti i ruoli</strong>
											</label>
											{#if !l.rolesAll}
												<div class="config-check-group">
													{#each ALL_ROLES as role}
														<label class="config-check">
															<input
																type="checkbox"
																checked={l.selectedRoles?.includes(role.value)}
																on:change={() => toggleRole(action.key, role.value)}
															/>
															{role.label}
														</label>
													{/each}
												</div>
											{/if}
										</div>

										<!-- Users column -->
										<div class="config-col">
											<div class="config-col-title">Utenti specifici <span style="font-weight:400;font-size:.75rem;color:var(--c-muted)">(override aggiuntivo)</span></div>
											<label class="config-check">
												<input
													type="checkbox"
													checked={l.usersAll}
													on:change={(e) => {
														local[action.key].usersAll = e.target.checked;
														if (local[action.key].usersAll) local[action.key].selectedUsers = [];
														local = local;
													}}
												/>
												Nessun override per utente
											</label>
											{#if !l.usersAll && users.length > 0}
												<div class="config-check-group config-users-list">
													{#each users as u}
														<label class="config-check">
															<input
																type="checkbox"
																checked={l.selectedUsers?.includes(u.id)}
																on:change={() => toggleUser(action.key, u.id)}
															/>
															<span>
																{u.display_name}
																<span class="user-role-chip">{u.role}</span>
															</span>
														</label>
													{/each}
												</div>
											{/if}
										</div>

										<!-- Options column -->
										<div class="config-col">
											<div class="config-col-title">Opzioni</div>
											<label class="config-check">
												<input
													type="checkbox"
													checked={l.requires_confirmation}
													on:change={(e) => { local[action.key].requires_confirmation = e.target.checked; local = local; }}
												/>
												<span>
													<strong>Richiedi conferma</strong>
													<br><span style="font-size:.76rem;color:var(--c-muted)">Il bot chiede "Confermi?" prima di eseguire</span>
												</span>
											</label>
										</div>
									</div>

									<div class="config-footer">
										{#if saveMsg[action.key]}
											<span class="save-msg" class:save-ok={saveMsg[action.key].startsWith('✓')}>{saveMsg[action.key]}</span>
										{/if}
										<button
											class="btn btn-primary btn-sm"
											disabled={saving[action.key]}
											on:click={() => saveAction(action.key)}
										>
											{#if saving[action.key]}<span class="spinner" style="width:.8rem;height:.8rem;border-width:2px"></span>{/if}
											Salva modifiche
										</button>
									</div>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{/each}
{/if}

<style>
.page-subtitle { font-size:.85rem; color:var(--c-muted); margin-top:.25rem; }

/* Category sections */
.cat-section { margin-bottom: 2rem; }
.cat-header {
	display: flex; align-items: flex-start; gap: .75rem;
	margin-bottom: .75rem;
}
.cat-icon { font-size: 1.4rem; line-height: 1; margin-top: .1rem; }
.cat-title { font-size: 1rem; font-weight: 700; }
.cat-desc { font-size: .8rem; color: var(--c-muted); margin-top: .1rem; }

/* Action cards */
.action-list { display: flex; flex-direction: column; gap: .65rem; }
.action-card {
	background: var(--c-surface);
	border-radius: var(--radius);
	box-shadow: var(--shadow);
	overflow: hidden;
	border-left: 3px solid transparent;
	transition: opacity .2s;
}
.action-card:not(.action-disabled) { border-left-color: var(--c-gold); }
.action-disabled { opacity: .6; border-left-color: transparent !important; }

.action-header {
	display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem;
	padding: .9rem 1.1rem;
}
.action-info { flex: 1; min-width: 0; }
.action-name-row { display: flex; align-items: center; flex-wrap: wrap; gap: .4rem; margin-bottom: .3rem; }
.action-name { font-weight: 700; font-size: .95rem; }

/* Badges */
.risk-badge {
	font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
	padding: .15rem .45rem; border-radius: 4px;
}
.risk-low    { background: rgba(34,197,94,.15);  color: #16a34a; }
.risk-medium { background: rgba(234,179,8,.15);  color: #b45309; }
.risk-high   { background: rgba(239,68,68,.15);  color: var(--c-danger); }
.confirm-badge { font-size: .7rem; color: #b45309; }

.action-desc { font-size: .82rem; color: var(--c-muted); margin: 0 0 .5rem; line-height: 1.5; }

/* Roles summary chips */
.roles-summary { display: flex; flex-wrap: wrap; gap: .3rem; }
.role-chip {
	font-size: .7rem; font-weight: 600; padding: .15rem .45rem;
	border-radius: 20px; border: 1px solid rgba(255,255,255,.15);
	color: rgba(255,255,255,.7); background: rgba(255,255,255,.07);
}
.role-all  { border-color: var(--c-gold); color: var(--c-gold); }
.role-none { border-color: var(--c-danger); color: var(--c-danger); }
.role-user { border-color: #60a5fa; color: #60a5fa; }

.user-role-chip {
	font-size: .65rem; background: rgba(255,255,255,.1); padding: .1rem .35rem;
	border-radius: 3px; margin-left: .3rem; text-transform: uppercase; letter-spacing: .04em;
}

/* Controls */
.action-controls { display: flex; align-items: center; gap: .5rem; flex-shrink: 0; }

/* Expandable config */
.action-config {
	border-top: 1px solid rgba(255,255,255,.07);
	padding: 1rem 1.1rem;
	background: rgba(0,0,0,.15);
}
.config-grid {
	display: grid;
	grid-template-columns: 1fr 1fr 1fr;
	gap: 1.25rem;
}
@media (max-width: 700px) {
	.config-grid { grid-template-columns: 1fr; }
}
.config-col-title {
	font-size: .72rem; font-weight: 700; text-transform: uppercase;
	letter-spacing: .06em; color: var(--c-muted); margin-bottom: .6rem;
}
.config-check {
	display: flex; align-items: flex-start; gap: .5rem;
	font-size: .85rem; cursor: pointer; padding: .25rem 0;
}
.config-check input[type="checkbox"] { margin-top: .2rem; flex-shrink: 0; }
.config-check-group { padding-left: .25rem; margin-top: .35rem; border-left: 2px solid rgba(255,255,255,.1); padding-left: .75rem; }
.config-users-list { max-height: 150px; overflow-y: auto; }

.config-footer {
	display: flex; align-items: center; justify-content: flex-end; gap: .75rem;
	margin-top: 1rem; padding-top: .75rem;
	border-top: 1px solid rgba(255,255,255,.07);
}
.save-msg { font-size: .82rem; color: var(--c-danger); }
.save-msg.save-ok { color: #22c55e; }
</style>
