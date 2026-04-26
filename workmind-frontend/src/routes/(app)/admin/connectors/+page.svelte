<script>
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/api.js';

	let connectors = [];
	let loading = true;
	let loadError = '';
	let activeCategory = 'all';
	let drawerOpen = false;
	let editingConnector = null;
	let formValues = {};
	let showPassword = {};
	let saving = false;
	let saveMsg = '';
	let saveMsgType = '';
	let testResult = null;
	let testing = false;

	const CATEGORIES = [
		{ id: 'all',       label: 'Tutti' },
		{ id: 'messaging', label: 'Messaggistica' },
		{ id: 'email',     label: 'Email' },
		{ id: 'ai',        label: 'AI' },
		{ id: 'devops',    label: 'DevOps' },
		{ id: 'storage',   label: 'Storage' },
	];

	const ICONS = {
		telegram:   '✈️',
		whatsapp:   '💬',
		smtp:       '📤',
		imap:       '📥',
		github:     '🐙',
		anthropic:  '🤖',
		deepseek:   '⚡',
		ollama:     '🦙',
		backup:     '💾',
		cpu:        '🖥️',
		mail:       '📧',
		inbox:      '📬',
		archive:    '🗄️',
	};

	const CATEGORY_LABELS = {
		messaging: 'Messaggistica',
		email:     'Email',
		ai:        'AI',
		devops:    'DevOps',
		storage:   'Storage',
	};

	$: filteredConnectors = activeCategory === 'all'
		? connectors
		: connectors.filter(c => c.category === activeCategory);

	onMount(async () => {
		try {
			connectors = await adminApi.listConnectors();
		} catch (e) {
			loadError = e.message || 'Errore caricamento connectors';
		} finally {
			loading = false;
		}
	});

	function openDrawer(connector) {
		editingConnector = connector;
		formValues = {};
		showPassword = {};
		for (const field of connector.fields) {
			formValues[field.key] = connector.config?.[field.key] ?? field.default ?? '';
		}
		testResult = null;
		saveMsg = '';
		drawerOpen = true;
	}

	function closeDrawer() {
		drawerOpen = false;
		editingConnector = null;
		testResult = null;
		saveMsg = '';
	}

	async function saveConnector() {
		saving = true;
		saveMsg = '';
		try {
			await adminApi.saveConnector(editingConnector.type, formValues);
			connectors = await adminApi.listConnectors();
			editingConnector = connectors.find(c => c.type === editingConnector.type);
			saveMsg = 'Configurazione salvata con successo.';
			saveMsgType = 'success';
		} catch (e) {
			saveMsg = e.message || 'Errore durante il salvataggio.';
			saveMsgType = 'error';
		} finally {
			saving = false;
		}
	}

	async function toggleConnector(connector) {
		try {
			if (connector.is_enabled) {
				await adminApi.disableConnector(connector.type);
			} else {
				await adminApi.enableConnector(connector.type);
			}
			connectors = await adminApi.listConnectors();
		} catch (e) {
			// silent — could add toast
		}
	}

	async function testConnector() {
		testing = true;
		testResult = null;
		try {
			testResult = await adminApi.testConnector(editingConnector.type);
			connectors = await adminApi.listConnectors();
			editingConnector = connectors.find(c => c.type === editingConnector.type);
		} catch (e) {
			testResult = { ok: false, message: e.message || 'Errore durante il test.' };
		} finally {
			testing = false;
		}
	}

	function isMasked(val) {
		return typeof val === 'string' && /^•+$/.test(val);
	}

	function toggleShowPassword(key) {
		showPassword[key] = !showPassword[key];
		showPassword = showPassword;
	}

	// ── Assegnazione ruoli ────────────────────────────────────────────────────────
	const ALL_ROLES = [
		{ value: 'admin',      label: 'Admin' },
		{ value: 'supervisor', label: 'Supervisor' },
		{ value: 'agent',      label: 'Agente' },
		{ value: 'user',       label: 'Utente' },
	];

	let rolesDrawerOpen = false;
	let rolesEditing = null;   // connector in editing
	let selectedRoles = [];    // [] = tutti; array of strings = selezionati
	let rolesAll = true;       // true = nessuna restrizione
	let rolesSaving = false;
	let rolesMsg = '';

	function openRolesDrawer(connector) {
		rolesEditing = connector;
		rolesAll = !connector.allowed_roles || connector.allowed_roles.length === 0;
		selectedRoles = connector.allowed_roles ? [...connector.allowed_roles] : [];
		rolesMsg = '';
		rolesDrawerOpen = true;
	}

	function toggleRole(val) {
		if (selectedRoles.includes(val)) {
			selectedRoles = selectedRoles.filter(r => r !== val);
		} else {
			selectedRoles = [...selectedRoles, val];
		}
	}

	async function saveRoles() {
		rolesSaving = true; rolesMsg = '';
		try {
			const roles = rolesAll ? null : selectedRoles;
			await adminApi.setConnectorRoles(rolesEditing.type, roles);
			connectors = await adminApi.listConnectors();
			rolesEditing = connectors.find(c => c.type === rolesEditing.type);
			rolesMsg = 'Accesso aggiornato.';
		} catch (e) {
			rolesMsg = e.message || 'Errore';
		} finally {
			rolesSaving = false;
		}
	}
</script>

<div class="page-header">
	<div>
		<h1 class="page-title">Integrazioni</h1>
		<p class="page-subtitle">Configura i connettori esterni: bot di messaggistica, email, AI, DevOps e storage.</p>
	</div>
</div>

{#if loadError}
	<div class="alert alert-error">{loadError}</div>
{/if}

<div class="cat-tabs">
	{#each CATEGORIES as cat}
		<button
			class="cat-tab"
			class:active={activeCategory === cat.id}
			on:click={() => activeCategory = cat.id}
		>
			{cat.label}
		</button>
	{/each}
</div>

{#if loading}
	<div class="empty-state">
		<span class="spinner"></span>
		<p>Caricamento integrazioni…</p>
	</div>
{:else if filteredConnectors.length === 0}
	<div class="empty-state">
		<p>Nessuna integrazione in questa categoria.</p>
	</div>
{:else}
	<div class="connector-grid">
		{#each filteredConnectors as connector (connector.type)}
			<div class="connector-card">
				<div class="connector-card-header">
					<span class="connector-icon">{ICONS[connector.icon] ?? '🔌'}</span>
					<div style="flex:1; min-width:0;">
						<div class="connector-name">{connector.name}</div>
						{#if connector.category && CATEGORY_LABELS[connector.category]}
							<span class="badge badge-muted" style="font-size:.7rem;">{CATEGORY_LABELS[connector.category]}</span>
						{/if}
					</div>
					<!-- Status badge -->
					{#if connector.status === 'ok'}
						<span class="badge status-badge-ok">🟢 Attivo</span>
					{:else if connector.status === 'error'}
						<span class="badge status-badge-error">🔴 Errore</span>
					{:else if connector.status === 'configured'}
						<span class="badge status-badge-configured">🟡 Da testare</span>
					{:else}
						<span class="badge status-badge-unconfigured">⚪ Non configurato</span>
					{/if}
				</div>

				<p class="connector-desc">{connector.description}</p>

				{#if connector.status_msg}
					<p style="font-size:.78rem; color: var(--c-danger);">{connector.status_msg}</p>
				{/if}

				<div class="connector-actions">
					<!-- Toggle -->
					<label
						class="toggle-switch"
						title={connector.status === 'unconfigured' ? 'Configura prima il connettore' : (connector.is_enabled ? 'Disabilita' : 'Abilita')}
					>
						<input
							type="checkbox"
							checked={connector.is_enabled}
							disabled={connector.status === 'unconfigured'}
							on:change={() => toggleConnector(connector)}
						/>

						<span class="toggle-slider"></span>
					</label>

					<div style="flex:1;"></div>

					<button
						class="btn btn-outline btn-sm"
						title="Gestisci accesso per ruolo"
						on:click={() => openRolesDrawer(connector)}
					>
						👥
					</button>

					<button class="btn btn-outline btn-sm" on:click={() => openDrawer(connector)}>
						Configura
					</button>

					{#if connector.status !== 'unconfigured'}
						<button
							class="btn btn-outline btn-sm"
							on:click={() => openDrawer(connector)}
							title="Testa connessione"
						>
							Testa
						</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
{/if}

<!-- Drawer overlay -->
{#if drawerOpen}
	<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
	<div class="drawer-overlay" on:click={closeDrawer}></div>

	<aside class="drawer">
		<div class="drawer-header">
			<span>
				{#if editingConnector}
					{ICONS[editingConnector.icon] ?? '🔌'} {editingConnector.name}
				{:else}
					Configura
				{/if}
			</span>
			<button class="drawer-close" on:click={closeDrawer} title="Chiudi">✕</button>
		</div>

		{#if editingConnector}
			{#if editingConnector.description}
				<p style="font-size:.83rem; color:var(--c-muted); margin-top:-.25rem;">{editingConnector.description}</p>
			{/if}

			<form on:submit|preventDefault={saveConnector} style="display:flex; flex-direction:column; gap:.1rem;">
				{#each editingConnector.fields as field}
					<div class="form-group">
						<label class="form-label" for="field-{field.key}">
							{field.label}{#if field.required} <span style="color:var(--c-danger)">*</span>{/if}
						</label>

						{#if field.type === 'boolean'}
							<label style="display:flex; align-items:center; gap:.5rem; cursor:pointer;">
								<input
									type="checkbox"
									id="field-{field.key}"
									checked={!!formValues[field.key]}
									on:change={(e) => formValues[field.key] = e.target.checked}
								/>
								<span style="font-size:.85rem;">{field.label}</span>
							</label>

						{:else if field.type === 'textarea'}
							<textarea
								id="field-{field.key}"
								class="form-input"
								rows="4"
								placeholder={isMasked(formValues[field.key]) ? '(invariato)' : (field.hint ?? '')}
								value={isMasked(formValues[field.key]) ? '' : (formValues[field.key] ?? '')}
								on:input={(e) => formValues[field.key] = e.target.value}
							></textarea>

						{:else if field.type === 'select'}
							<select
								id="field-{field.key}"
								class="form-input"
								bind:value={formValues[field.key]}
							>
								{#each field.options ?? [] as opt}
									<option value={opt.value ?? opt}>{opt.label ?? opt}</option>
								{/each}
							</select>

						{:else if field.type === 'password'}
							<div style="position:relative; display:flex; align-items:center;">
								<input
									id="field-{field.key}"
									class="form-input"
									type={showPassword[field.key] ? 'text' : 'password'}
									placeholder={isMasked(formValues[field.key]) ? '(invariato — lascia vuoto per non cambiare)' : (field.hint ?? '')}
									value={isMasked(formValues[field.key]) ? '' : (formValues[field.key] ?? '')}
									on:input={(e) => formValues[field.key] = e.target.value}
									style="width:100%; padding-right:2.5rem;"
								/>
								<button
									type="button"
									on:click={() => toggleShowPassword(field.key)}
									style="position:absolute; right:.5rem; background:none; border:none; color:var(--c-muted); font-size:.85rem; cursor:pointer;"
									title={showPassword[field.key] ? 'Nascondi' : 'Mostra'}
								>
									{showPassword[field.key] ? '🙈' : '👁️'}
								</button>
							</div>

						{:else}
							{#if field.type === 'number'}
							<input id="field-{field.key}" class="form-input" type="number" placeholder={field.hint ?? ''} bind:value={formValues[field.key]} />
						{:else if field.type === 'email'}
							<input id="field-{field.key}" class="form-input" type="email" placeholder={field.hint ?? ''} bind:value={formValues[field.key]} />
						{:else}
							<input id="field-{field.key}" class="form-input" type="text" placeholder={field.hint ?? ''} bind:value={formValues[field.key]} />
						{/if}
						{/if}

						{#if field.hint && field.type !== 'password'}
							<span style="font-size:.74rem; color:var(--c-muted);">{field.hint}</span>
						{/if}
					</div>
				{/each}

				{#if saveMsg}
					<div class="alert" class:alert-success={saveMsgType === 'success'} class:alert-error={saveMsgType === 'error'}>
						{saveMsg}
					</div>
				{/if}

				{#if testResult}
					<div class="alert" class:alert-success={testResult.ok} class:alert-error={!testResult.ok}>
						{testResult.ok ? '✅' : '❌'} {testResult.message}
					</div>
				{/if}

				<div style="display:flex; gap:.5rem; margin-top:.5rem; flex-wrap:wrap;">
					<button type="submit" class="btn btn-primary" disabled={saving}>
						{#if saving}<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px;"></span>{/if}
						Salva
					</button>

					{#if editingConnector.status !== 'unconfigured'}
						<button
							type="button"
							class="btn btn-outline"
							disabled={testing}
							on:click={testConnector}
						>
							{#if testing}<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px;"></span>{/if}
							Testa connessione
						</button>
					{/if}

					<button type="button" class="btn btn-outline" on:click={closeDrawer}>
						Annulla
					</button>
				</div>
			</form>
		{/if}
	</aside>
{/if}

<!-- Roles Drawer -->
{#if rolesDrawerOpen}
	<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
	<div class="drawer-overlay" on:click={() => rolesDrawerOpen = false}></div>

	<aside class="drawer">
		<div class="drawer-header">
			<span>👥 Accesso — {rolesEditing?.name ?? ''}</span>
			<button class="drawer-close" on:click={() => rolesDrawerOpen = false} title="Chiudi">✕</button>
		</div>

		<p style="font-size:.83rem; color:var(--c-muted); margin-top:-.25rem;">
			Definisci quali ruoli possono usare questo connettore. Di default è accessibile a tutti.
		</p>

		<div style="display:flex; flex-direction:column; gap:.75rem; margin-top:.5rem;">
			<label style="display:flex; align-items:center; gap:.6rem; cursor:pointer; font-size:.9rem;">
				<input
					type="checkbox"
					checked={rolesAll}
					on:change={(e) => { rolesAll = e.target.checked; if (rolesAll) selectedRoles = []; }}
				/>
				<span><strong>Tutti i ruoli</strong> — nessuna restrizione</span>
			</label>

			{#if !rolesAll}
				<div style="border-top:1px solid var(--c-border); padding-top:.75rem; display:flex; flex-direction:column; gap:.5rem;">
					{#each ALL_ROLES as role}
						<label style="display:flex; align-items:center; gap:.6rem; cursor:pointer; font-size:.88rem;">
							<input
								type="checkbox"
								checked={selectedRoles.includes(role.value)}
								on:change={() => toggleRole(role.value)}
							/>
							{role.label}
						</label>
					{/each}
				</div>
			{/if}

			{#if rolesMsg}
				<div class="alert" class:alert-success={rolesMsg === 'Accesso aggiornato.'} class:alert-error={rolesMsg !== 'Accesso aggiornato.'}>
					{rolesMsg}
				</div>
			{/if}

			<div style="display:flex; gap:.5rem; margin-top:.25rem;">
				<button class="btn btn-primary" disabled={rolesSaving} on:click={saveRoles}>
					{#if rolesSaving}<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px;"></span>{/if}
					Salva
				</button>
				<button class="btn btn-outline" on:click={() => rolesDrawerOpen = false}>
					Annulla
				</button>
			</div>
		</div>
	</aside>
{/if}

<style>
.page-subtitle {
	font-size: .85rem;
	color: var(--c-muted);
	margin-top: .25rem;
}
</style>
