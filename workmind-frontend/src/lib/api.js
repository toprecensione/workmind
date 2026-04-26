/**
 * MEDIC API client
 * All requests go to /api/* — proxied to FastAPI in dev, served directly in prod.
 */
import { get } from 'svelte/store';
import { auth } from './stores.js';

const BASE = '/api';

class ApiError extends Error {
	constructor(status, detail) {
		super(detail);
		this.status = status;
	}
}

async function _request(method, path, body, opts = {}) {
	const $auth = get(auth);
	const headers = { 'Content-Type': 'application/json' };

	if ($auth.accessToken) {
		headers['Authorization'] = `Bearer ${$auth.accessToken}`;
	}

	const res = await fetch(`${BASE}${path}`, {
		method,
		headers,
		body: body != null ? JSON.stringify(body) : undefined,
		...opts,
	});

	// Token expired — attempt refresh
	if (res.status === 401 && $auth.refreshToken) {
		const refreshed = await _tryRefresh($auth.refreshToken);
		if (refreshed) {
			// Retry original request with new token
			headers['Authorization'] = `Bearer ${get(auth).accessToken}`;
			const retry = await fetch(`${BASE}${path}`, {
				method,
				headers,
				body: body != null ? JSON.stringify(body) : undefined,
			});
			return _parse(retry);
		} else {
			auth.logout();
			window.location.href = '/login';
			throw new ApiError(401, 'Sessione scaduta');
		}
	}

	return _parse(res);
}

async function _tryRefresh(refreshToken) {
	try {
		const res = await fetch(`${BASE}/auth/refresh`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ refresh_token: refreshToken }),
		});
		if (!res.ok) return false;
		const { access_token } = await res.json();
		auth.updateAccessToken(access_token);
		return true;
	} catch {
		return false;
	}
}

async function _parse(res) {
	if (res.status === 204) return null;
	const text = await res.text();
	let data;
	try { data = JSON.parse(text); } catch { data = { detail: text }; }
	if (!res.ok) throw new ApiError(res.status, data?.detail ?? `HTTP ${res.status}`);
	return data;
}

const get_  = (path)        => _request('GET', path);
const post  = (path, body)  => _request('POST', path, body);
const put   = (path, body)  => _request('PUT', path, body);
const patch = (path, body)  => _request('PATCH', path, body);
const del   = (path)        => _request('DELETE', path);
const put_  = put;
const del_  = del;

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authApi = {
	login:   (email, password) => post('/auth/login', { email, password }),
	refresh: (refresh_token)   => post('/auth/refresh', { refresh_token }),
	logout:  (refresh_token)   => post('/auth/logout', { refresh_token }),
};

// ── MEDIC Products ────────────────────────────────────────────────────────────
export const productsApi = {
	list:             ()             => get_('/medic/products'),
	create:           (data)         => post('/medic/products', data),
	update:           (id, data)     => put(`/medic/products/${id}`, data),
	delete:           (id)           => del_(`/medic/products/${id}`),
	alerts:           ()             => get_('/medic/stock/alerts'),
	stockCorrection:  (id, data)     => post(`/medic/products/${id}/stock-correction`, data),
};

// ── MEDIC Lots ────────────────────────────────────────────────────────────────
export const lotsApi = {
	addLot:   (productId, data) => post(`/medic/products/${productId}/lots`, data),
	listLots: (productId)       => get_(`/medic/products/${productId}/lots`),
};

// ── MEDIC Sales ───────────────────────────────────────────────────────────────
export const salesApi = {
	list:   (params = {}) => {
		const qs = new URLSearchParams(
			Object.fromEntries(Object.entries(params).filter(([, v]) => v != null))
		).toString();
		return get_(`/medic/sales${qs ? '?' + qs : ''}`);
	},
	create: (data)       => post('/medic/sales', data),
	update: (id, data)   => put_('/medic/sales/' + id, data),
	delete: (id)         => del_('/medic/sales/' + id),
};

// ── MEDIC Stats ───────────────────────────────────────────────────────────────
export const statsApi = {
	overview:  () => get_('/medic/stats/summary'),
	byAgent:   () => get_('/medic/stats/by-agent'),
	byProduct: () => get_('/medic/stats/by-product'),
};

// ── Agent Warehouse ───────────────────────────────────────────────────────────
export const agentWarehouseApi = {
	myStock:    ()          => get_('/medic/agent-warehouse/my'),
	allocations: (agentId)  => {
		const qs = agentId ? `?agent_id=${agentId}` : '';
		return get_('/medic/agent-warehouse/allocations' + qs);
	},
	allocate:   (data)      => post('/medic/agent-warehouse/allocate', data),
	return_:    (data)      => post('/medic/agent-warehouse/return', data),
	movements:  (params={}) => {
		const qs = new URLSearchParams(Object.entries(params).filter(([,v])=>v!=null)).toString();
		return get_('/medic/agent-warehouse/movements' + (qs ? '?' + qs : ''));
	},
};

// ── Password Reset (public, no auth) ─────────────────────────────────────────
export const resetApi = {
	forgotPassword: (email)                  => post('/auth/forgot-password', { email }),
	resetPassword:  (token, new_password)    => post('/auth/reset-password', { token, new_password }),
};

// ── Generic MEDIC API helper ──────────────────────────────────────────────────
export const medicApi = {
	get:  (path) => get_(path),
	post: (path, body) => post(path, body),
};

// ── Conversations API ─────────────────────────────────────────────────────────
export const conversationsApi = {
	list:   (params = {}) => get_('/conversations' + (Object.keys(params).length ? '?' + new URLSearchParams(params) : '')),
	get:    (id)          => get_(`/conversations/${id}`),
	create: (data = {})   => post('/conversations', data),
	patch:  (id, data)    => patch(`/conversations/${id}`, data),
	delete: (id)          => del_(`/conversations/${id}`),
};

// ── Admin API ─────────────────────────────────────────────────────────────────
export const adminApi = {
	// Connectors
	listConnectors:     ()            => get_('/admin/connectors'),
	saveConnector:      (type, cfg)   => put_('/admin/connectors/' + type, { config: cfg }),
	enableConnector:    (type)        => post('/admin/connectors/' + type + '/enable', {}),
	disableConnector:   (type)        => post('/admin/connectors/' + type + '/disable', {}),
	testConnector:      (type)        => post('/admin/connectors/' + type + '/test', {}),
	deleteConnector:    (type)        => del_('/admin/connectors/' + type),
	setConnectorRoles:  (type, roles) => patch('/admin/connectors/' + type + '/roles', { allowed_roles: roles }),
	// Skills
	listSkills:         ()            => get_('/admin/skills'),
	enableSkill:        (id)          => post('/admin/skills/' + id + '/enable', {}),
	disableSkill:       (id)          => post('/admin/skills/' + id + '/disable', {}),
	saveSkillConfig:    (id, cfg)     => put_('/admin/skills/' + id + '/config', { config: cfg }),
	setSkillRoles:      (id, roles)   => patch('/admin/skills/' + id + '/roles', { allowed_roles: roles }),
	// Users
	listUsers: (params = {}) => {
		const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)).toString();
		return get_('/admin/users' + (qs ? '?' + qs : ''));
	},
	createUser:      (data)       => post('/admin/users', data),
	getUser:         (id)         => get_('/admin/users/' + id),
	updateUser:      (id, data)   => put_('/admin/users/' + id, data),
	deleteUser:      (id)         => del_('/admin/users/' + id),
	resetPassword:   (id)         => post('/admin/users/' + id + '/reset-password', {}),
	activateUser:    (id)         => post('/admin/users/' + id + '/activate', {}),
	deactivateUser:  (id)         => post('/admin/users/' + id + '/deactivate', {}),
	getUserActivity: (id)         => get_('/admin/users/' + id + '/activity'),
	getOrg:          ()           => get_('/admin/org'),
	updateOrg:       (data)       => put_('/admin/org', data),
	// AI Action Permissions
	listAiActions:   ()           => get_('/admin/ai-actions'),
	listAiUsers:     ()           => get_('/admin/ai-actions/users'),
	updateAiAction:  (key, data)  => patch('/admin/ai-actions/' + key, data),
	// System
	getSystemStatus:   ()           => get_('/admin/system/status'),
	getSystemMetrics:  ()           => get_('/admin/system/metrics'),
	getSystemOverview: ()           => get_('/admin/system/overview'),
	// KB admin
	getKbWatchPaths:   ()           => get_('/admin/kb/watch-paths'),
	addKbWatchPath:    (data)       => post('/admin/kb/watch-paths', data),
	updateKbWatchPath: (id, data)   => put_('/admin/kb/watch-paths/' + id, data),
	deleteKbWatchPath: (id)         => del_('/admin/kb/watch-paths/' + id),
	scanKbWatchPath:   (id)         => post('/admin/kb/watch-paths/' + id + '/scan', {}),
	getKbStats:        ()           => get_('/admin/kb/stats'),
	// KB documents (già in /api/kb)
	listKbDocuments:   (params={})  => get_('/kb/documents' + (Object.keys(params).length ? '?' + new URLSearchParams(params) : '')),
	searchKb:          (q, top_k=5) => get_('/kb/search?q=' + encodeURIComponent(q) + '&top_k=' + top_k),
	deleteKbDocument:  (id)         => del_('/kb/documents/' + id),
	// Audit
	getAuditLogs: (params={}) => {
		const qs = new URLSearchParams(Object.entries(params).filter(([,v])=>v!=null&&v!=='')).toString();
		return get_('/admin/audit/logs' + (qs ? '?' + qs : ''));
	},
	// Backup
	listBackups:    ()  => get_('/admin/backup'),
	triggerBackup:  ()  => post('/admin/backup/trigger', {}),
	getBackupStatus: (id) => get_('/admin/backup/' + id + '/status'),
	// AI Usage
	getAiUsage: (days=30, group_by_day=false) => get_('/admin/usage?days=' + days + (group_by_day ? '&group_by_day=true' : '')),
};
