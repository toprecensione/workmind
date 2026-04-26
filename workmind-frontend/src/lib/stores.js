import { writable, derived } from 'svelte/store';

// ── Auth store ────────────────────────────────────────────────────────────────

function createAuthStore() {
	const { subscribe, set, update } = writable({
		accessToken: null,
		refreshToken: null,
		user: null,          // { sub, org_id, role, email_hash }
		ready: false,
	});

	return {
		subscribe,

		/** Called after successful login */
		setTokens(accessToken, refreshToken) {
			const user = _decodeJwt(accessToken);
			localStorage.setItem('wm_access',  accessToken);
			localStorage.setItem('wm_refresh', refreshToken);
			set({ accessToken, refreshToken, user, ready: true });
		},

		/** Restore from localStorage on app init */
		restore() {
			const accessToken  = localStorage.getItem('wm_access');
			const refreshToken = localStorage.getItem('wm_refresh');
			if (accessToken && refreshToken) {
				const user = _decodeJwt(accessToken);
				// Check expiry
				if (user && user.exp * 1000 > Date.now()) {
					set({ accessToken, refreshToken, user, ready: true });
					return true;
				}
			}
			set({ accessToken: null, refreshToken: null, user: null, ready: true });
			return false;
		},

		updateAccessToken(accessToken) {
			localStorage.setItem('wm_access', accessToken);
			update(s => ({ ...s, accessToken, user: _decodeJwt(accessToken) }));
		},

		/** Update display_name in memory (after PATCH /auth/me) */
		updateDisplayName(display_name) {
			update(s => ({
				...s,
				user: s.user ? { ...s.user, display_name } : s.user,
			}));
		},

		logout() {
			localStorage.removeItem('wm_access');
			localStorage.removeItem('wm_refresh');
			set({ accessToken: null, refreshToken: null, user: null, ready: true });
		},
	};
}

function _decodeJwt(token) {
	try {
		const payload = token.split('.')[1];
		return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
	} catch {
		return null;
	}
}

export const auth = createAuthStore();
export const isLoggedIn = derived(auth, $a => !!$a.accessToken && !!$a.user);

// ── Chat store — persists across navigation AND hard reload ──────────────────

const WELCOME_MSG = {
	role: 'assistant',
	content: 'Ciao! Sono il tuo assistente MEDIC. Puoi chiedermi informazioni su inventario, vendite e statistiche. Posso anche registrare vendite per te! 🎯',
};

const CHAT_STORAGE_KEY = 'wm_chat_messages';
const CHAT_CONV_KEY    = 'wm_chat_conv_id';

function createChatStore() {
	// Restore from localStorage on init (SSR-safe)
	let initial;
	try {
		const saved = typeof localStorage !== 'undefined' && localStorage.getItem(CHAT_STORAGE_KEY);
		initial = saved ? { messages: JSON.parse(saved) } : { messages: [WELCOME_MSG] };
	} catch {
		initial = { messages: [WELCOME_MSG] };
	}

	const { subscribe, set, update } = writable(initial);

	return {
		subscribe,
		addMessage(msg) {
			update(s => {
				const messages = [...s.messages, msg];
				try { localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages)); } catch {}
				return { ...s, messages };
			});
		},
		reset() {
			try {
				localStorage.removeItem(CHAT_STORAGE_KEY);
				localStorage.removeItem(CHAT_CONV_KEY);
			} catch {}
			set({ messages: [WELCOME_MSG] });
		},
		/** Append text to the last message (used during SSE streaming) */
		appendToLast(text) {
			update(s => {
				if (s.messages.length === 0) return s;
				const messages = [...s.messages];
				const last = messages[messages.length - 1];
				messages[messages.length - 1] = { ...last, content: last.content + text };
				try { localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages)); } catch {}
				return { ...s, messages };
			});
		},
		/** Restore messages from DB (overwrites localStorage cache) */
		restoreFromDb(dbMessages) {
			const messages = dbMessages.length > 0 ? dbMessages : [WELCOME_MSG];
			try { localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages)); } catch {}
			set({ messages });
		},
		getConversationId() {
			try { return localStorage.getItem(CHAT_CONV_KEY) || null; } catch { return null; }
		},
		setConversationId(id) {
			try { if (id) localStorage.setItem(CHAT_CONV_KEY, id); } catch {}
		},
	};
}

export const chatStore = createChatStore();
