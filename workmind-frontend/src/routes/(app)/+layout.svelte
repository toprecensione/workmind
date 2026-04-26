<script>
	import { isLoggedIn, auth } from '$lib/stores.js';
	import { goto } from '$app/navigation';
	import Sidebar from '$lib/Sidebar.svelte';

	$: if ($auth.ready && !$isLoggedIn) goto('/login');
</script>

{#if $isLoggedIn}
	<div class="app-shell">
		<Sidebar />
		<main class="main-content">
			<slot />
		</main>
	</div>
{/if}
