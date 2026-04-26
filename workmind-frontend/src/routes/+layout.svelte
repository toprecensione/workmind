<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth, isLoggedIn } from '$lib/stores.js';

	onMount(() => {
		auth.restore();
	});

	$: if ($auth.ready && !$isLoggedIn && $page.url.pathname !== '/login') {
		goto('/login');
	}
</script>

<slot />
