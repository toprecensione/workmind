<script>
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { resetApi } from '$lib/api.js';

	let token = '';
	let newPassword = '';
	let confirmPassword = '';
	let loading = false;
	let success = false;
	let error = '';

	onMount(() => {
		token = $page.url.searchParams.get('token') || '';
		if (!token) error = 'Link non valido o scaduto.';
	});

	async function submit() {
		error = '';
		if (!newPassword || !confirmPassword) { error = 'Compila tutti i campi.'; return; }
		if (newPassword !== confirmPassword)  { error = 'Le password non coincidono.'; return; }
		if (newPassword.length < 8)           { error = 'La password deve avere almeno 8 caratteri.'; return; }

		loading = true;
		try {
			await resetApi.resetPassword(token, newPassword);
			success = true;
			setTimeout(() => goto('/login'), 3000);
		} catch (e) {
			error = e.message || 'Token non valido o scaduto.';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head><title>Reimposta password — MEDIC</title></svelte:head>

<div class="page">
	<div class="card">
		<div class="logo-row">
			<span class="logo-m">M</span>
			<div>
				<div class="logo-name">MEDIC</div>
				<div class="logo-sub">Aesthetic Medicine</div>
			</div>
		</div>

		<h2 class="title">Reimposta password</h2>

		{#if success}
			<div class="alert alert-ok">
				Password aggiornata. Verrai reindirizzato al login tra pochi secondi…
			</div>
			<a href="/login" class="back-link">← Vai al login</a>
		{:else}
			{#if error && !token}
				<div class="alert alert-error">{error}</div>
				<a href="/forgot-password" class="back-link">← Richiedi un nuovo link</a>
			{:else}
				{#if error}<div class="alert alert-error">{error}</div>{/if}

				<form on:submit|preventDefault={submit}>
					<div class="form-group">
						<label class="form-label" for="np">Nuova password</label>
						<input
							id="np" type="password" class="form-input"
							bind:value={newPassword} placeholder="Min. 8 caratteri" required
						/>
					</div>
					<div class="form-group">
						<label class="form-label" for="cp">Conferma password</label>
						<input
							id="cp" type="password" class="form-input"
							bind:value={confirmPassword} placeholder="Ripeti la password" required
						/>
					</div>
					<button type="submit" class="btn btn-primary submit-btn" disabled={loading || !token}>
						{#if loading}<span class="spinner"></span>{/if}
						{loading ? 'Salvataggio...' : 'Salva password'}
					</button>
				</form>
				<a href="/login" class="back-link">← Torna al login</a>
			{/if}
		{/if}
	</div>
</div>

<style>
.page {
	min-height: 100vh;
	display: flex; align-items: center; justify-content: center;
	background: var(--c-sidebar); padding: 1rem;
}
.card {
	width: 100%; max-width: 380px;
	background: var(--c-surface); border-radius: 12px;
	padding: 2.25rem 2rem;
	box-shadow: 0 20px 60px rgba(0,0,0,.3);
}
.logo-row { display: flex; align-items: center; gap: .85rem; margin-bottom: 2rem; }
.logo-m {
	width: 2.6rem; height: 2.6rem; background: var(--c-gold); border-radius: 8px;
	display: flex; align-items: center; justify-content: center;
	font-size: 1.4rem; font-weight: 900; color: #111; flex-shrink: 0;
}
.logo-name { font-size: 1.1rem; font-weight: 800; color: var(--c-text); }
.logo-sub  { font-size: .7rem; color: var(--c-muted); margin-top: .05rem; }
.title { font-size: 1rem; font-weight: 600; color: var(--c-text); margin-bottom: 1.5rem; }
.submit-btn { width: 100%; justify-content: center; padding: .7rem; margin-top: .25rem; font-size: .95rem; }
.back-link { display: block; text-align: center; margin-top: 1.25rem; font-size: .82rem; color: var(--c-muted); text-decoration: none; }
.back-link:hover { text-decoration: underline; color: var(--c-accent); }
.alert-ok {
	background: rgba(34,197,94,.12); border: 1px solid rgba(34,197,94,.3);
	color: #16a34a; border-radius: 8px; padding: .75rem 1rem;
	font-size: .875rem; margin-bottom: 1.25rem;
}
</style>
