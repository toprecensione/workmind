<script>
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { auth } from './stores.js';
	import { authApi } from './api.js';

	let adminSheetOpen = false;

	async function logout() {
		try { await authApi.logout($auth.refreshToken); } catch {}
		auth.logout();
		goto('/login');
	}

	function navTo(href) {
		adminSheetOpen = false;
		goto(href);
	}

	const navItems = [
		{ href: '/',                   label: 'Dashboard',    short: 'Home'     },
		{ href: '/products',           label: 'Prodotti',     short: 'Prodotti' },
		{ href: '/sales',              label: 'Vendite',      short: 'Vendite'  },
		{ href: '/stats',              label: 'Statistiche',  short: 'Stats'    },
		{ href: '/logs',               label: 'Registro',     short: 'Registro' },
		{ href: '/chat',               label: 'Assistente AI',short: 'AI'       },
		{ href: '/admin/users',        label: 'Utenti',       short: 'Utenti',  adminOnly: true },
		{ href: '/admin/connectors',   label: 'Integrazioni', short: 'Plugin',  adminOnly: true },
		{ href: '/admin/skills',       label: 'Funzionalità', short: 'Skill',   adminOnly: true },
	];
</script>

<!-- Desktop sidebar -->
<aside class="sidebar">
	<div class="sidebar-logo">
		<div class="logo-row">
			<span class="logo-m">M</span>
			<div>
				<div class="logo-name">MEDIC</div>
				<div class="logo-sub">Aesthetic Medicine</div>
			</div>
		</div>
	</div>

	<nav class="sidebar-nav">
		{#each navItems as item, i}
			{#if !item.adminOnly || $auth.user?.role === 'admin'}
				{#if item.adminOnly && !navItems[i-1]?.adminOnly}
					<div class="nav-separator"></div>
				{/if}
				<a href={item.href} class="nav-item" class:active={item.href === '/' ? $page.url.pathname === '/' : $page.url.pathname.startsWith(item.href)}>
					{#if item.href === '/'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path d="M3 4a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm0 8a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H4a1 1 0 01-1-1v-4zm8-8a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V4zm0 8a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"/></svg>
					{:else if item.href === '/products'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path d="M4 3a2 2 0 100 4h12a2 2 0 100-4H4z"/><path fill-rule="evenodd" d="M3 8h14v7a2 2 0 01-2 2H5a2 2 0 01-2-2V8zm5 3a1 1 0 011-1h2a1 1 0 110 2h-2a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>
					{:else if item.href === '/sales'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clip-rule="evenodd"/></svg>
					{:else if item.href === '/stats'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zm6-4a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zm6-3a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z"/></svg>
					{:else if item.href === '/logs'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 4a1 1 0 000 2h14a1 1 0 100-2H3zm0 4a1 1 0 000 2h14a1 1 0 100-2H3zm0 4a1 1 0 000 2h8a1 1 0 100-2H3zm0 4a1 1 0 000 2h8a1 1 0 100-2H3z" clip-rule="evenodd"/></svg>
					{:else if item.href === '/admin/users'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/></svg>
					{:else if item.href === '/admin/connectors'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"/></svg>
					{:else if item.href === '/admin/skills'}
						<svg viewBox="0 0 20 20" fill="currentColor"><path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z"/></svg>
					{:else}
						<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clip-rule="evenodd"/></svg>
					{/if}
					{item.label}
				</a>
			{/if}
		{/each}
	</nav>

	<div class="sidebar-footer">
		<div class="user-email">{$auth.user?.display_name || ($auth.user?.email_hash ? $auth.user.email_hash.slice(0,12) + '…' : 'utente')}</div>
		<button class="logout-btn" on:click={logout}>Esci →</button>
	</div>
</aside>

<!-- Mobile bottom nav — solo item NON admin + pulsante Admin (sheet) + Esci -->
<nav class="bottom-nav">
	<!-- Item principali (non admin) -->
	{#each navItems.filter(i => !i.adminOnly) as item}
		<a href={item.href} class="bottom-nav-item" class:active={item.href === '/' ? $page.url.pathname === '/' : $page.url.pathname.startsWith(item.href)}>
			{#if item.href === '/'}
				<svg viewBox="0 0 20 20" fill="currentColor"><path d="M3 4a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm0 8a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H4a1 1 0 01-1-1v-4zm8-8a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V4zm0 8a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"/></svg>
			{:else if item.href === '/products'}
				<svg viewBox="0 0 20 20" fill="currentColor"><path d="M4 3a2 2 0 100 4h12a2 2 0 100-4H4z"/><path fill-rule="evenodd" d="M3 8h14v7a2 2 0 01-2 2H5a2 2 0 01-2-2V8zm5 3a1 1 0 011-1h2a1 1 0 110 2h-2a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>
			{:else if item.href === '/sales'}
				<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clip-rule="evenodd"/></svg>
			{:else if item.href === '/stats'}
				<svg viewBox="0 0 20 20" fill="currentColor"><path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zm6-4a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zm6-3a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z"/></svg>
			{:else if item.href === '/logs'}
				<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 4a1 1 0 000 2h14a1 1 0 100-2H3zm0 4a1 1 0 000 2h14a1 1 0 100-2H3zm0 4a1 1 0 000 2h8a1 1 0 100-2H3zm0 4a1 1 0 000 2h8a1 1 0 100-2H3z" clip-rule="evenodd"/></svg>
			{:else}
				<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clip-rule="evenodd"/></svg>
			{/if}
			{item.short}
		</a>
	{/each}

	<!-- Admin: pulsante ⚙️ che apre sheet -->
	{#if $auth.user?.role === 'admin'}
		<button
			class="bottom-nav-item"
			class:active={adminSheetOpen || $page.url.pathname.startsWith('/admin')}
			on:click={() => adminSheetOpen = !adminSheetOpen}
		>
			<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"/></svg>
			Admin
		</button>
	{:else}
		<!-- Esci per utenti non-admin -->
		<button class="bottom-nav-item bottom-nav-logout" on:click={logout}>
			<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 3a1 1 0 00-1 1v12a1 1 0 001 1h7a1 1 0 100-2H4V5h6a1 1 0 100-2H3zm11.707 4.293a1 1 0 010 1.414L13.414 10l1.293 1.293a1 1 0 01-1.414 1.414l-2-2a1 1 0 010-1.414l2-2a1 1 0 011.414 0z" clip-rule="evenodd"/><path d="M13 10a1 1 0 00-1-1H7a1 1 0 100 2h5a1 1 0 001-1z"/></svg>
			Esci
		</button>
	{/if}
</nav>

<!-- Admin sheet (slide-up) -->
{#if adminSheetOpen}
	<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
	<div class="admin-sheet-overlay" on:click={() => adminSheetOpen = false}></div>
	<div class="admin-sheet">
		<div class="admin-sheet-handle"></div>
		<div class="admin-sheet-title">Amministrazione</div>

		<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
		<div class="admin-sheet-item" on:click={() => navTo('/admin/users')}>
			<svg viewBox="0 0 20 20" fill="currentColor" width="20" height="20"><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/></svg>
			Utenti
		</div>
		<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
		<div class="admin-sheet-item" on:click={() => navTo('/admin/connectors')}>
			<svg viewBox="0 0 20 20" fill="currentColor" width="20" height="20"><path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"/></svg>
			Integrazioni
		</div>
		<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
		<div class="admin-sheet-item" on:click={() => navTo('/admin/skills')}>
			<svg viewBox="0 0 20 20" fill="currentColor" width="20" height="20"><path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z"/></svg>
			Funzionalità
		</div>

		<div class="admin-sheet-divider"></div>

		<button class="admin-sheet-item admin-sheet-logout" on:click={logout}>
			<svg viewBox="0 0 20 20" fill="currentColor" width="20" height="20"><path fill-rule="evenodd" d="M3 3a1 1 0 00-1 1v12a1 1 0 001 1h7a1 1 0 100-2H4V5h6a1 1 0 100-2H3zm11.707 4.293a1 1 0 010 1.414L13.414 10l1.293 1.293a1 1 0 01-1.414 1.414l-2-2a1 1 0 010-1.414l2-2a1 1 0 011.414 0z" clip-rule="evenodd"/><path d="M13 10a1 1 0 00-1-1H7a1 1 0 100 2h5a1 1 0 001-1z"/></svg>
			Esci
		</button>
	</div>
{/if}

<style>
.logo-row { display: flex; align-items: center; gap: .75rem; }
.logo-m {
	width: 2.1rem; height: 2.1rem;
	background: var(--c-gold);
	border-radius: 6px;
	display: flex; align-items: center; justify-content: center;
	font-size: 1.15rem; font-weight: 900; color: #111;
	flex-shrink: 0;
}
.nav-separator {
	height: 1px;
	background: rgba(255,255,255,.1);
	margin: 0.5rem 1rem;
}

/* Mobile logout item — slight dimming */
.bottom-nav-logout { opacity: .8; }
.bottom-nav-logout:hover { opacity: 1; }

/* Admin slide-up sheet */
.admin-sheet-overlay {
	position: fixed; inset: 0; z-index: 200;
	background: rgba(0,0,0,.45);
}
.admin-sheet {
	position: fixed; bottom: 64px; left: 0; right: 0; z-index: 201;
	background: var(--c-surface, #1e2433);
	border-radius: 16px 16px 0 0;
	padding: .75rem 0 1.5rem;
	box-shadow: 0 -4px 24px rgba(0,0,0,.35);
	animation: sheet-up .22s ease;
}
@keyframes sheet-up {
	from { transform: translateY(100%); }
	to   { transform: translateY(0); }
}
.admin-sheet-handle {
	width: 40px; height: 4px;
	background: rgba(255,255,255,.2);
	border-radius: 2px;
	margin: 0 auto .75rem;
}
.admin-sheet-title {
	font-size: .7rem;
	font-weight: 700;
	letter-spacing: .08em;
	text-transform: uppercase;
	color: rgba(255,255,255,.4);
	padding: 0 1.25rem .5rem;
}
.admin-sheet-item {
	display: flex; align-items: center; gap: .85rem;
	padding: .85rem 1.25rem;
	font-size: .95rem;
	color: rgba(255,255,255,.85);
	cursor: pointer;
	transition: background .15s;
	width: 100%; text-align: left;
	background: none; border: none; font: inherit;
}
.admin-sheet-item:hover { background: rgba(255,255,255,.07); }
.admin-sheet-divider {
	height: 1px;
	background: rgba(255,255,255,.1);
	margin: .4rem 1.25rem;
}
.admin-sheet-logout { color: rgba(255,120,120,.9); }
</style>
