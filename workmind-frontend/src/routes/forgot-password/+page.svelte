<script>
	import { resetApi } from '$lib/api.js';

	let email = '';
	let loading = false;
	let sent = false;
	let error = '';

	async function submit() {
		if (!email) return;
		loading = true; error = '';
		try {
			await resetApi.forgotPassword(email);
			sent = true;
		} catch (e) {
			error = e.message || 'Errore imprevisto';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head><title>Password dimenticata — MEDIC</title></svelte:head>

<div class="page">
	<div class="card">
		<div class="logo-row">
			<span class="logo-m">M</span>
			<div>
				<div class="logo-name">MEDIC</div>
				<div class="logo-sub">Aesthetic Medicine</div>
			</div>
		</div>

		<h2 class="title">Recupera password</h2>

		{#if sent}
			<div class="alert alert-ok">
				Se l'email è registrata, riceverai un link per reimpostare la password.
			</div>
			<a href="/login" class="back-link">← Torna al login</a>
		{:else}
			<p class="desc">Inserisci la tua email. Ti invieremo un link per reimpostare la password.</p>

			{#if error}<div class="alert alert-error">{error}</div>{/if}

			<form on:submit|preventDefault={submit}>
				<div class="form-group">
					<label class="form-label" for="email">Email</label>
					<input
						id="email" type="email" class="form-input"
						bind:value={email} placeholder="utente@esempio.it" required
					/>
				</div>
				<button type="submit" class="btn btn-primary submit-btn" disabled={loading}>
					{#if loading}<span class="spinner"></span>{/if}
					{loading ? 'Invio...' : 'Invia link'}
				</button>
			</form>
			<a href="/login" class="back-link">← Torna al login</a>
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
.title { font-size: 1rem; font-weight: 600; color: var(--c-text); margin-bottom: 1rem; }
.desc  { font-size: .875rem; color: var(--c-muted); margin-bottom: 1.25rem; line-height: 1.5; }
.submit-btn { width: 100%; justify-content: center; padding: .7rem; margin-top: .25rem; font-size: .95rem; }
.back-link { display: block; text-align: center; margin-top: 1.25rem; font-size: .82rem; color: var(--c-muted); text-decoration: none; }
.back-link:hover { text-decoration: underline; color: var(--c-accent); }
.alert-ok {
	background: rgba(34,197,94,.12); border: 1px solid rgba(34,197,94,.3);
	color: #16a34a; border-radius: 8px; padding: .75rem 1rem;
	font-size: .875rem; margin-bottom: 1.25rem;
}
</style>
