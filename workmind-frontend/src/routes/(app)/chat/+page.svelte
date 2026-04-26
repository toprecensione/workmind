<script>
	import { onMount, tick } from 'svelte';
	import { medicApi, conversationsApi } from '$lib/api.js';
	import { chatStore } from '$lib/stores.js';

	let input = '';
	let loading = false;
	let listening = false;
	let recognition = null;
	let chatEl;
	let inputEl;
	let speechSupported = false;
	let lastActionPerformed = null; // 'registra_vendita' | 'carica_stock' | null

	// Reactive alias — messages live in the store
	$: messages = $chatStore.messages;

	onMount(async () => {
		// Try to restore DB conversation if we have a saved conv_id
		const savedConvId = chatStore.getConversationId();
		if (savedConvId) {
			try {
				const conv = await conversationsApi.get(savedConvId);
				if (conv && conv.messages && conv.messages.length > 0) {
					// Restore from DB — more reliable than localStorage
					chatStore.restoreFromDb(conv.messages.map(m => ({ role: m.role, content: m.content })));
				}
			} catch {
				// Conversation may have been deleted or expired — start fresh
				chatStore.reset();
			}
		}

		await tick();
		scrollBottom();

		speechSupported = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;
		if (speechSupported) {
			const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
			recognition = new SR();
			recognition.lang = 'it-IT';
			recognition.continuous = false;
			recognition.interimResults = false;
			recognition.onresult = (e) => {
				input = e.results[0][0].transcript;
				listening = false;
				send();
			};
			recognition.onerror = () => { listening = false; };
			recognition.onend   = () => { listening = false; };
		}
	});

	async function send() {
		const text = input.trim();
		if (!text || loading) return;
		input = '';
		if (inputEl) { inputEl.style.height = 'auto'; }
		chatStore.addMessage({ role: 'user', content: text });
		loading = true;
		await tick();
		scrollBottom();

		try {
			await sendStream(text);
		} catch(e) {
			const msg = e?.status === 401
				? 'Sessione scaduta. Rieffettua il login.'
				: (e?.message || 'Errore di connessione. Riprova.');
			chatStore.addMessage({ role: 'assistant', content: msg });
		} finally {
			loading = false;
			await tick();
			scrollBottom();
		}
	}

	/**
	 * SSE streaming via fetch + ReadableStream.
	 * Falls back to non-streaming if SSE fails (e.g. older proxy without X-Accel-Buffering).
	 */
	async function sendStream(text) {
		const { get } = await import('svelte/store');
		const { auth: authStore } = await import('$lib/stores.js');
		const $auth = get(authStore);
		const token = $auth.accessToken;

		const convId = chatStore.getConversationId();
		const payload = { message: text };
		if (convId) payload.conversation_id = convId;

		const res = await fetch('/api/chat/stream', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				...(token ? { 'Authorization': `Bearer ${token}` } : {}),
			},
			body: JSON.stringify(payload),
		});

		if (!res.ok) {
			// Fallback: non-streaming (e.g. 404 if endpoint not deployed yet)
			const data = await res.json().catch(() => ({}));
			const detail = data?.detail || `HTTP ${res.status}`;
			throw new Error(detail);
		}

		// Add empty assistant message — will be filled incrementally
		chatStore.addMessage({ role: 'assistant', content: '' });
		await tick();
		scrollBottom();

		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buffer = '';

		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, { stream: true });
			const parts = buffer.split('\n\n');
			buffer = parts.pop() ?? '';  // keep incomplete last part

			for (const part of parts) {
				for (const line of part.split('\n')) {
					if (!line.startsWith('data: ')) continue;
					let event;
					try { event = JSON.parse(line.slice(6)); } catch { continue; }

					if (event.type === 'chunk' && event.text) {
						chatStore.appendToLast(event.text);
						await tick();
						scrollBottom();
					} else if (event.type === 'done') {
						if (event.conversation_id) chatStore.setConversationId(event.conversation_id);
						lastActionPerformed = event.action_performed ?? null;
					} else if (event.type === 'error') {
						// Replace placeholder with error message
						chatStore.appendToLast(
							(messages[messages.length - 1]?.content ? '\n' : '') +
							'⚠️ ' + (event.message || 'Errore nella risposta.')
						);
					}
				}
			}
		}
	}

	function scrollBottom() {
		if (chatEl) chatEl.scrollTop = chatEl.scrollHeight;
	}

	function toggleVoice() {
		if (!recognition) return;
		if (listening) {
			recognition.stop();
			listening = false;
		} else {
			recognition.start();
			listening = true;
		}
	}

	function onKeydown(e) {
		if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
	}

	function autoResize(e) {
		const el = e.target;
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 120) + 'px';
	}

	function newChat() {
		chatStore.reset();
		input = '';
	}

	// ── Lightweight markdown → HTML renderer ────────────────────────────────────
	function renderMarkdown(text) {
		if (!text) return '';
		let html = text
			// Escape HTML entities first
			.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
			// Fenced code blocks ```lang\n...\n```
			.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
				`<pre><code>${code.trimEnd()}</code></pre>`)
			// Inline code `...`
			.replace(/`([^`\n]+)`/g, '<code>$1</code>')
			// Bold **text** or __text__
			.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
			.replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
			// Italic *text* or _text_ (not inside words)
			.replace(/(?<!\w)\*([^*\n]+)\*(?!\w)/g, '<em>$1</em>')
			.replace(/(?<!\w)_([^_\n]+)_(?!\w)/g, '<em>$1</em>');

		// Process line-by-line for lists + paragraphs
		const lines = html.split('\n');
		const out = [];
		let inUl = false, inOl = false, inPre = false;

		for (const line of lines) {
			if (line.startsWith('<pre>')) { inPre = true; out.push(line); continue; }
			if (line.startsWith('</pre>')) { inPre = false; out.push(line); continue; }
			if (inPre) { out.push(line); continue; }

			const ulMatch = line.match(/^[\-\*] (.+)/);
			const olMatch = line.match(/^\d+\. (.+)/);

			if (ulMatch) {
				if (!inUl) { out.push('<ul>'); inUl = true; }
				if (inOl)  { out.push('</ol>'); inOl = false; }
				out.push(`<li>${ulMatch[1]}</li>`);
			} else if (olMatch) {
				if (!inOl) { out.push('<ol>'); inOl = true; }
				if (inUl)  { out.push('</ul>'); inUl = false; }
				out.push(`<li>${olMatch[1]}</li>`);
			} else {
				if (inUl) { out.push('</ul>'); inUl = false; }
				if (inOl) { out.push('</ol>'); inOl = false; }
				out.push(line === '' ? '<br>' : line);
			}
		}
		if (inUl) out.push('</ul>');
		if (inOl) out.push('</ol>');

		return out.join('\n');
	}

	const suggestions = [
		'Quante siringhe di Juvéderm abbiamo?',
		'Chi ha venduto di più questo mese?',
		'Ci sono prodotti in scadenza?',
		'Registra una vendita di Botox 1 siringa',
	];
</script>

<div class="chat-page">
	<div class="page-header" style="margin-bottom:.75rem">
		<div style="display:flex;align-items:center;gap:.6rem">
			<h1 class="page-title">Assistente AI</h1>
			<span class="badge badge-ok" style="font-size:.7rem">Storico salvato</span>
		</div>
		<button class="btn btn-outline btn-sm" on:click={newChat} title="Inizia una nuova conversazione">
			<svg viewBox="0 0 20 20" fill="currentColor" style="width:1rem;height:1rem"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>
			Nuova chat
		</button>
	</div>

	<!-- Messages -->
	<div class="chat-messages" bind:this={chatEl}>
		{#each messages as msg}
			<div class="msg msg-{msg.role}">
				{#if msg.role === 'assistant'}
					<div class="msg-avatar">
						<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clip-rule="evenodd"/></svg>
					</div>
				{/if}
				{#if msg.role === 'assistant'}
					<div class="msg-bubble md">{@html renderMarkdown(msg.content)}</div>
				{:else}
					<div class="msg-bubble">{msg.content}</div>
				{/if}
			</div>
		{/each}
		{#if loading}
			<div class="msg msg-assistant">
				<div class="msg-avatar"><svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7z" clip-rule="evenodd"/></svg></div>
				<div class="msg-bubble typing"><span></span><span></span><span></span></div>
			</div>
		{/if}
	</div>

	<!-- Action banner: shown after bot performs a write action -->
	{#if lastActionPerformed}
		<div class="action-banner">
			{#if lastActionPerformed === 'registra_vendita'}
				✅ Vendita registrata — lo stock è stato aggiornato.
			{:else if lastActionPerformed === 'carica_stock'}
				✅ Carico registrato — lo stock è stato aggiornato.
			{/if}
			<a href="/products" class="banner-link">Vai a Prodotti</a>
			<a href="/logs" class="banner-link">Vai al Registro</a>
			<button class="banner-close" on:click={() => lastActionPerformed = null}>✕</button>
		</div>
	{/if}

	<!-- Suggestions (shown when only welcome message) -->
	{#if messages.length === 1}
		<div class="suggestions">
			{#each suggestions as s}
				<button class="suggestion-chip" on:click={() => { input = s; send(); }}>{s}</button>
			{/each}
		</div>
	{/if}

	<!-- Input -->
	<div class="chat-input-row">
		<textarea
			bind:this={inputEl}
			bind:value={input}
			on:keydown={onKeydown}
			on:input={autoResize}
			placeholder="Scrivi o usa il microfono…"
			rows="1"
			disabled={loading}
		></textarea>
		{#if speechSupported}
			<button class="btn-icon" class:recording={listening} on:click={toggleVoice} title="Voce" disabled={loading}>
				{#if listening}
					<svg viewBox="0 0 20 20" fill="currentColor" style="color:var(--c-danger)"><path fill-rule="evenodd" d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" clip-rule="evenodd"/></svg>
				{:else}
					<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" clip-rule="evenodd"/></svg>
				{/if}
			</button>
		{/if}
		<button class="btn btn-primary btn-sm" on:click={send} disabled={loading || !input.trim()}>
			{#if loading}<span class="spinner" style="width:.9rem;height:.9rem"></span>{:else}Invia{/if}
		</button>
	</div>
</div>

<style>
.chat-page { display: flex; flex-direction: column; height: calc(100vh - 2rem - 60px); max-height: 800px; }
@media (max-width: 640px) {
	.chat-page { height: calc(100dvh - 60px - 76px); max-height: none; }
}

.chat-messages {
	flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: .75rem;
	padding: .5rem 0 1rem;
	scroll-behavior: smooth;
}

.msg { display: flex; align-items: flex-end; gap: .5rem; }
.msg-user { flex-direction: row-reverse; }

.msg-avatar {
	width: 1.8rem; height: 1.8rem; flex-shrink: 0;
	background: var(--c-gold); border-radius: 50%;
	display: flex; align-items: center; justify-content: center;
	color: #111;
}
.msg-avatar svg { width: 1rem; height: 1rem; }

.msg-bubble {
	max-width: 75%; padding: .65rem .9rem;
	border-radius: 1rem; font-size: .9rem; line-height: 1.5;
	white-space: pre-wrap;
}
/* Markdown bubble */
.msg-bubble.md { white-space: normal; }
.msg-bubble.md :global(strong) { font-weight: 700; }
.msg-bubble.md :global(em) { font-style: italic; }
.msg-bubble.md :global(code) {
	font-family: monospace; font-size: .82em;
	background: rgba(0,0,0,.07); border-radius: 4px; padding: .1em .35em;
}
.msg-bubble.md :global(pre) {
	background: rgba(0,0,0,.1); border-radius: 6px;
	padding: .6rem .8rem; margin: .4rem 0; overflow-x: auto;
}
.msg-bubble.md :global(pre code) { background: none; padding: 0; font-size: .83em; }
.msg-bubble.md :global(ul), .msg-bubble.md :global(ol) {
	margin: .3rem 0 .3rem 1.2rem; padding: 0;
}
.msg-bubble.md :global(li) { margin: .15rem 0; }
.msg-bubble.md :global(br) { display: block; margin: .25rem 0; content: ''; }
.msg-assistant .msg-bubble { background: var(--c-surface); box-shadow: var(--shadow); border-bottom-left-radius: .25rem; }
.msg-user .msg-bubble { background: var(--c-gold); color: #111; border-bottom-right-radius: .25rem; }

/* Typing indicator */
.typing { display: flex; align-items: center; gap: 4px; padding: .7rem 1rem; }
.typing span {
	width: 6px; height: 6px; background: var(--c-muted);
	border-radius: 50%; animation: bounce .9s infinite;
}
.typing span:nth-child(2) { animation-delay: .15s; }
.typing span:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 0%,80%,100%{transform:translateY(0)} 40%{transform:translateY(-6px)} }

/* Action banner */
.action-banner {
	display: flex; align-items: center; gap: .5rem; flex-wrap: wrap;
	background: #dcfce7; border: 1.5px solid #86efac; border-radius: var(--radius);
	padding: .5rem .75rem; font-size: .8rem; color: #166534;
	margin-bottom: .5rem;
}
.banner-link {
	padding: .2rem .5rem; background: #166534; color: #fff;
	border-radius: 99px; font-size: .75rem; font-weight: 600;
	text-decoration: none; white-space: nowrap;
}
.banner-link:hover { background: #14532d; }
.banner-close {
	margin-left: auto; background: none; border: none; cursor: pointer;
	color: #166534; font-size: .9rem; padding: 0 .2rem; opacity: .7;
}
.banner-close:hover { opacity: 1; }

.suggestions { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .75rem; }
.suggestion-chip {
	padding: .4rem .75rem; border-radius: 99px; font-size: .78rem;
	background: var(--c-surface); border: 1.5px solid var(--c-border);
	color: var(--c-muted); cursor: pointer; transition: all .15s;
	text-align: left;
}
.suggestion-chip:hover { border-color: var(--c-gold); color: var(--c-text); }

.chat-input-row {
	display: flex; gap: .5rem; align-items: flex-end;
	background: var(--c-surface); border: 1.5px solid var(--c-border);
	border-radius: var(--radius); padding: .4rem .5rem;
	box-shadow: var(--shadow);
}
.chat-input-row textarea {
	flex: 1; border: none; outline: none; resize: none; background: transparent;
	font-size: .9rem; line-height: 1.5; max-height: 120px; padding: .25rem .3rem;
	color: var(--c-text);
}
.btn-icon {
	width: 2.1rem; height: 2.1rem; border-radius: 50%; border: none;
	background: var(--c-bg); display: flex; align-items: center; justify-content: center;
	flex-shrink: 0; transition: background .15s;
}
.btn-icon svg { width: 1.1rem; height: 1.1rem; color: var(--c-muted); }
.btn-icon:hover { background: var(--c-border); }
.btn-icon.recording { background: var(--c-danger-bg); animation: pulse 1s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
</style>
