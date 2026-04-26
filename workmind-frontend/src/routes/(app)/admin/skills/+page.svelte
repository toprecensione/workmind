<script>
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/api.js';

	let skills = [];
	let loading = true;
	let loadError = '';
	let activeCategory = 'all';
	let drawerOpen = false;
	let editingSkill = null;
	let formValues = {};
	let saving = false;
	let saveMsg = '';
	let saveMsgType = '';

	const CATEGORIES = [
		{ id: 'all',           label: 'Tutti' },
		{ id: 'notifications', label: 'Notifiche' },
		{ id: 'ai',            label: 'AI' },
		{ id: 'messaging',     label: 'Messaggistica' },
		{ id: 'devops',        label: 'DevOps' },
		{ id: 'storage',       label: 'Storage' },
		{ id: 'medic',         label: '🏥 MEDIC' },
	];

	const SKILL_ICONS = {
		bell:             '🔔',
		terminal:         '💻',
		mic:              '🎤',
		mail:             '📧',
		inbox:            '📬',
		whatsapp:         '💬',
		github:           '🐙',
		archive:          '💾',
		'alert-triangle': '⚠️',
		'bar-chart':      '📊',
	};

	const CATEGORY_LABELS = {
		notifications: 'Notifiche',
		ai:            'AI',
		messaging:     'Messaggistica',
		devops:        'DevOps',
		storage:       'Storage',
		medic:         '🏥 MEDIC',
	};

	$: filteredSkills = activeCategory === 'all'
		? skills
		: skills.filter(s => s.category === activeCategory);

	onMount(async () => {
		try {
			skills = await adminApi.listSkills();
		} catch (e) {
			loadError = e.message || 'Errore caricamento skill';
		} finally {
			loading = false;
		}
	});

	async function toggleSkill(skill) {
		if (!skill.requirements_met && !skill.is_enabled) return;
		try {
			if (skill.is_enabled) {
				await adminApi.disableSkill(skill.id);
			} else {
				await adminApi.enableSkill(skill.id);
			}
			skills = await adminApi.listSkills();
		} catch (e) {
			// silent
		}
	}

	function openSkillConfig(skill) {
		editingSkill = skill;
		formValues = {};
		for (const field of skill.config_schema) {
			formValues[field.key] = skill.config?.[field.key] ?? field.default ?? '';
		}
		saveMsg = '';
		drawerOpen = true;
	}

	function closeDrawer() {
		drawerOpen = false;
		editingSkill = null;
		saveMsg = '';
	}

	async function saveSkillConfig() {
		saving = true;
		saveMsg = '';
		try {
			await adminApi.saveSkillConfig(editingSkill.id, formValues);
			skills = await adminApi.listSkills();
			editingSkill = skills.find(s => s.id === editingSkill.id);
			saveMsg = 'Configurazione salvata con successo.';
			saveMsgType = 'success';
		} catch (e) {
			saveMsg = e.message || 'Errore durante il salvataggio.';
			saveMsgType = 'error';
		} finally {
			saving = false;
		}
	}

	// ── Assegnazione ruoli ────────────────────────────────────────────────────────
	const ALL_ROLES = [
		{ value: 'admin',      label: 'Admin' },
		{ value: 'supervisor', label: 'Supervisor' },
		{ value: 'agent',      label: 'Agente' },
		{ value: 'user',       label: 'Utente' },
	];

	let rolesDrawerOpen = false;
	let rolesEditing = null;
	let selectedRoles = [];
	let rolesAll = true;
	let rolesSaving = false;
	let rolesMsg = '';

	function openRolesDrawer(skill) {
		rolesEditing = skill;
		rolesAll = !skill.allowed_roles || skill.allowed_roles.length === 0;
		selectedRoles = skill.allowed_roles ? [...skill.allowed_roles] : [];
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
			await adminApi.setSkillRoles(rolesEditing.id, roles);
			skills = await adminApi.listSkills();
			rolesEditing = skills.find(s => s.id === rolesEditing.id);
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
		<h1 class="page-title">Funzionalità</h1>
		<p class="page-subtitle">Abilita e configura le skill automatizzate di WorkMind.</p>
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
		<p>Caricamento funzionalità…</p>
	</div>
{:else if filteredSkills.length === 0}
	<div class="empty-state">
		<p>Nessuna funzionalità in questa categoria.</p>
	</div>
{:else}
	<div class="skill-grid">
		{#each filteredSkills as skill (skill.id)}
			<div class="skill-card" class:skill-disabled={!skill.requirements_met && !skill.is_enabled}>
				<div class="connector-card-header">
					<span class="connector-icon">{SKILL_ICONS[skill.icon] ?? '⚙️'}</span>
					<div style="flex:1; min-width:0;">
						<div class="connector-name">{skill.name}</div>
						{#if skill.category && CATEGORY_LABELS[skill.category]}
							<span class="badge badge-muted" style="font-size:.7rem;">{CATEGORY_LABELS[skill.category]}</span>
						{/if}
					</div>
					<!-- Toggle -->
					<label
						class="toggle-switch"
						title={!skill.requirements_met && !skill.is_enabled ? 'Requisiti mancanti' : (skill.is_enabled ? 'Disabilita' : 'Abilita')}
					>
						<input
							type="checkbox"
							checked={skill.is_enabled}
							disabled={!skill.requirements_met && !skill.is_enabled}
							on:change={() => toggleSkill(skill)}
						/>
						<span class="toggle-slider"></span>
					</label>
				</div>

				<p class="connector-desc">{skill.description}</p>

				<!-- Requisiti -->
				{#if skill.requires && skill.requires.length > 0}
					<div style="display:flex; flex-wrap:wrap; gap:.35rem;">
						{#each skill.requirements_detail ?? skill.requires.map(r => ({ name: r, met: skill.requirements_met })) as req}
							<span class="req-chip" class:req-chip-ok={req.met} class:req-chip-miss={!req.met}>
								{req.name} {req.met ? '✅' : '❌'}
							</span>
						{/each}
					</div>
				{/if}

				{#if !skill.requirements_met && !skill.is_enabled}
					<p style="font-size:.76rem; color:var(--c-danger);">Abilita prima i connettori richiesti.</p>
				{/if}

				<div class="connector-actions">
					<div style="flex:1;"></div>
					<button
						class="btn btn-outline btn-sm"
						title="Gestisci accesso per ruolo"
						on:click={() => openRolesDrawer(skill)}
					>
						👥
					</button>
					{#if skill.config_schema && skill.config_schema.length > 0}
						<button class="btn btn-outline btn-sm" on:click={() => openSkillConfig(skill)}>
							Configura
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
				{#if editingSkill}
					{SKILL_ICONS[editingSkill.icon] ?? '⚙️'} {editingSkill.name}
				{:else}
					Configura
				{/if}
			</span>
			<button class="drawer-close" on:click={closeDrawer} title="Chiudi">✕</button>
		</div>

		{#if editingSkill}
			{#if editingSkill.description}
				<p style="font-size:.83rem; color:var(--c-muted); margin-top:-.25rem;">{editingSkill.description}</p>
			{/if}

			<form on:submit|preventDefault={saveSkillConfig} style="display:flex; flex-direction:column; gap:.1rem;">
				{#each editingSkill.config_schema as field}
					<div class="form-group">
						<label class="form-label" for="skill-field-{field.key}">
							{field.label}{#if field.required} <span style="color:var(--c-danger)">*</span>{/if}
						</label>

						{#if field.type === 'boolean'}
							<label style="display:flex; align-items:center; gap:.5rem; cursor:pointer;">
								<input
									type="checkbox"
									id="skill-field-{field.key}"
									checked={!!formValues[field.key]}
									on:change={(e) => formValues[field.key] = e.target.checked}
								/>
								<span style="font-size:.85rem;">{field.label}</span>
							</label>

						{:else if field.type === 'textarea'}
							<textarea
								id="skill-field-{field.key}"
								class="form-input"
								rows="4"
								placeholder={field.hint ?? ''}
								bind:value={formValues[field.key]}
							></textarea>

						{:else if field.type === 'select'}
							<select
								id="skill-field-{field.key}"
								class="form-input"
								bind:value={formValues[field.key]}
							>
								{#each field.options ?? [] as opt}
									<option value={opt.value ?? opt}>{opt.label ?? opt}</option>
								{/each}
							</select>

						{:else}
							{#if field.type === 'number'}
							<input id="skill-field-{field.key}" class="form-input" type="number" placeholder={field.hint ?? ''} bind:value={formValues[field.key]} />
						{:else if field.type === 'email'}
							<input id="skill-field-{field.key}" class="form-input" type="email" placeholder={field.hint ?? ''} bind:value={formValues[field.key]} />
						{:else}
							<input id="skill-field-{field.key}" class="form-input" type="text" placeholder={field.hint ?? ''} bind:value={formValues[field.key]} />
						{/if}
						{/if}

						{#if field.hint}
							<span style="font-size:.74rem; color:var(--c-muted);">{field.hint}</span>
						{/if}
					</div>
				{/each}

				{#if saveMsg}
					<div class="alert" class:alert-success={saveMsgType === 'success'} class:alert-error={saveMsgType === 'error'}>
						{saveMsg}
					</div>
				{/if}

				<div style="display:flex; gap:.5rem; margin-top:.5rem;">
					<button type="submit" class="btn btn-primary" disabled={saving}>
						{#if saving}<span class="spinner" style="width:.9rem;height:.9rem;border-width:2px;"></span>{/if}
						Salva
					</button>
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
			Definisci quali ruoli possono usare questa funzionalità. Di default è accessibile a tutti.
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
.skill-disabled {
	opacity: .65;
}
</style>
