<script>
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores.js';
	import { authApi } from '$lib/api.js';

	let email = '';
	let password = '';
	let loading = false;
	let error = '';

	async function handleLogin() {
		if (!email || !password) return;
		loading = true;
		error = '';
		try {
			const res = await authApi.login(email, password);
			auth.setTokens(res.access_token, res.refresh_token);
			goto('/');
		} catch (e) {
			error = e.message || 'Credenziali non valide';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head><title>Login — MEDIC</title></svelte:head>

<div class="login-page">
	<div class="login-card">
		<div class="login-logo">
			<span class="logo-m">M</span>
			<div>
				<div class="logo-name">MEDIC</div>
				<div class="logo-sub">Aesthetic Medicine</div>
			</div>
		</div>

		<h2 class="login-title">Accedi al gestionale</h2>

		{#if error}
			<div class="alert alert-error">{error}</div>
		{/if}

		<form on:submit|preventDefault={handleLogin}>
			<div class="form-group">
				<label class="form-label" for="email">Email</label>
				<input
					id="email" type="email" class="form-input"
					bind:value={email} autocomplete="username"
					placeholder="utente@esempio.it" required
				/>
			</div>
			<div class="form-group">
				<label class="form-label" for="pw">Password</label>
				<input
					id="pw" type="password" class="form-input"
					bind:value={password} autocomplete="current-password"
					placeholder="••••••••" required
				/>
			</div>

			<button type="submit" class="btn btn-primary login-btn" disabled={loading}>
				{#if loading}<span class="spinner"></span>{/if}
				{loading ? 'Accesso...' : 'Accedi'}
			</button>
		</form>

		<div class="forgot-link">
			<a href="/forgot-password">Password dimenticata?</a>
		</div>
	</div>
</div>

<style>
.login-page {
	min-height: 100vh;
	display: flex;
	align-items: center;
	justify-content: center;
	background: var(--c-sidebar);
	padding: 1rem;
}
.login-card {
	width: 100%;
	max-width: 380px;
	background: var(--c-surface);
	border-radius: 12px;
	padding: 2.25rem 2rem;
	box-shadow: 0 20px 60px rgba(0,0,0,.3);
}
.login-logo {
	display: flex;
	align-items: center;
	gap: .85rem;
	margin-bottom: 2rem;
}
.logo-m {
	width: 2.6rem;
	height: 2.6rem;
	background: var(--c-gold);
	border-radius: 8px;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: 1.4rem;
	font-weight: 900;
	color: #111;
	flex-shrink: 0;
}
.logo-name { font-size: 1.1rem; font-weight: 800; color: var(--c-text); }
.logo-sub  { font-size: .7rem; color: var(--c-muted); margin-top: .05rem; }
.login-title {
	font-size: 1rem;
	font-weight: 600;
	color: var(--c-text);
	margin-bottom: 1.5rem;
}
.login-btn {
	width: 100%;
	justify-content: center;
	padding: .7rem;
	margin-top: .25rem;
	font-size: .95rem;
}
.forgot-link {
	text-align: center;
	margin-top: 1rem;
}
.forgot-link a {
	color: var(--c-muted);
	font-size: .82rem;
	text-decoration: none;
}
.forgot-link a:hover { text-decoration: underline; color: var(--c-accent); }
</style>
