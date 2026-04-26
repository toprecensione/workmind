<script>
	import { onMount } from 'svelte';
	import { auth } from '$lib/stores.js';
	import { authApi } from '$lib/api.js';
	import { medicApi } from '$lib/api.js';

	// Use the authApi for /auth/me
	const meApi = {
		get:   () => medicApi.get('/auth/me'),
		patch: (data) => medicApi.post('/auth/me', data),  // will use PATCH below
	};

	// Proper PATCH via raw fetch wrapper
	import { get as svGet } from 'svelte/store';

	async function patchMe(data) {
		const $auth = svGet(auth);
		const res = await fetch('/api/auth/me', {
			method: 'PATCH',
			headers: {
				'Content-Type': 'application/json',
				'Authorization': `Bearer ${$auth.accessToken}`,
			},
			body: JSON.stringify(data),
		});
		if (!res.ok) {
			const j = await res.json().catch(() => ({}));
			throw new Error(j.detail || `HTTP ${res.status}`);
		}
		return res.json();
	}

	let profile = null;
	let loadError = '';

	// Display name form
	let nameValue = '';
	let nameSaving = false;
	let nameMsg = '';

	// Password form
	let currentPw = '';
	let newPw = '';
	let confirmPw = '';
	let pwSaving = false;
	let pwMsg = '';
	let pwError = '';

	onMount(async () => {
		try {
			profile = await meApi.get();
			nameValue = profile.display_name || '';
		} catch (e) {
			loadError = e.message || 'Errore caricamento profilo';
		}
	});

	async function saveName() {
		if (!nameValue.trim()) return;
		nameSaving = true; nameMsg = '';
		try {
			const updated = await patchMe({ display_name: nameValue.trim() });
			profile = updated;
			auth.updateDisplayName(nameValue.trim());
			nameMsg = '✅ Nome aggiornato';
		} catch(e) {
			nameMsg = '❌ ' + (e.message || 'Errore');
		} finally {
			nameSaving = false;
		}
	}

	async function savePassword() {
		pwMsg = ''; pwError = '';
		if (!currentPw || !newPw) { pwError = 'Compila tutti i campi'; return; }
		if (newPw !== confirmPw)  { pwError = 'Le password non coincidono'; return; }
		if (newPw.length < 8)     { pwError = 'Minimo 8 caratteri'; return; }
		pwSaving = true;
		try {
			await patchMe({ current_password: currentPw, new_password: newPw });
			pwMsg = '✅ Password aggiornata';
			currentPw = newPw = confirmPw = '';
		} catch(e) {
			pwError = '❌ ' + (e.message || 'Errore');
		} finally {
			pwSaving = false;
		}
	}
</script>

<div class="page-header">
	<h1 class="page-title">Profilo</h1>
</div>

{#if loadError}
	<div class="alert alert-danger">{loadError}</div>
{:else if !profile}
	<div class="spinner" style="width:2rem;height:2rem;margin:2rem auto;display:block"></div>
{:else}
	<div class="profile-grid">

		<!-- Info card -->
		<div class="card">
			<div class="card-header"><h2 class="card-title">Dati account</h2></div>
			<div class="card-body">
				<dl class="info-list">
					<dt>Email</dt><dd>{profile.email || '—'}</dd>
					<dt>Ruolo</dt><dd class="badge badge-ok" style="display:inline">{profile.role}</dd>
					<dt>ID</dt><dd style="font-size:.75rem;font-family:monospace;opacity:.6">{profile.id}</dd>
				</dl>
			</div>
		</div>

		<!-- Display name card -->
		<div class="card">
			<div class="card-header"><h2 class="card-title">Nome visualizzato</h2></div>
			<div class="card-body">
				<p class="form-hint">Mostrato nella sidebar e nei report.</p>
				<div class="form-row">
					<input
						class="form-input"
						type="text"
						placeholder="Es. Mario Rossi"
						bind:value={nameValue}
						maxlength="80"
					/>
					<button class="btn btn-primary btn-sm" on:click={saveName} disabled={nameSaving || !nameValue.trim()}>
						{#if nameSaving}<span class="spinner" style="width:.9rem;height:.9rem"></span>{:else}Salva{/if}
					</button>
				</div>
				{#if nameMsg}<p class="form-feedback">{nameMsg}</p>{/if}
			</div>
		</div>

		<!-- Password card -->
		<div class="card">
			<div class="card-header"><h2 class="card-title">Cambia password</h2></div>
			<div class="card-body">
				<div class="form-group">
					<label class="form-label" for="cur-pw">Password attuale</label>
					<input id="cur-pw" class="form-input" type="password" bind:value={currentPw} autocomplete="current-password"/>
				</div>
				<div class="form-group">
					<label class="form-label" for="new-pw">Nuova password</label>
					<input id="new-pw" class="form-input" type="password" bind:value={newPw} autocomplete="new-password"/>
				</div>
				<div class="form-group">
					<label class="form-label" for="conf-pw">Conferma nuova password</label>
					<input id="conf-pw" class="form-input" type="password" bind:value={confirmPw} autocomplete="new-password"/>
				</div>
				{#if pwError}<p class="form-feedback error">{pwError}</p>{/if}
				{#if pwMsg}  <p class="form-feedback">{pwMsg}</p>{/if}
				<button class="btn btn-primary btn-sm" on:click={savePassword} disabled={pwSaving}>
					{#if pwSaving}<span class="spinner" style="width:.9rem;height:.9rem"></span>{:else}Aggiorna password{/if}
				</button>
			</div>
		</div>

	</div>
{/if}

<style>
.profile-grid {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 1rem;
	align-items: start;
}
@media (max-width: 640px) {
	.profile-grid { grid-template-columns: 1fr; }
}
.info-list { display: grid; grid-template-columns: auto 1fr; gap: .35rem .75rem; align-items: baseline; }
.info-list dt { font-size: .78rem; color: var(--c-muted); font-weight: 600; }
.info-list dd { margin: 0; }
.form-row { display: flex; gap: .5rem; align-items: center; }
.form-row .form-input { flex: 1; }
.form-hint { font-size: .82rem; color: var(--c-muted); margin-bottom: .75rem; }
.form-feedback { margin-top: .5rem; font-size: .83rem; color: var(--c-muted); }
.form-feedback.error { color: var(--c-danger); }
.form-group { margin-bottom: .75rem; }
.card { background: var(--c-surface); border: 1px solid var(--c-border); border-radius: var(--radius); }
.card-header { padding: .85rem 1rem .6rem; border-bottom: 1px solid var(--c-border); }
.card-title { font-size: .95rem; font-weight: 700; margin: 0; }
.card-body { padding: 1rem; }
</style>
