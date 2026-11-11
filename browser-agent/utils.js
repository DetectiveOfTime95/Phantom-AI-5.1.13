export const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const isLocalHttpHost = (hostname) => {
  const host = String(hostname || '').toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host.endsWith('.local')) return true;
  if (host === '::1') return true;
  const octets = host.split('.').map(Number);
  if (octets.length !== 4 || octets.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return false;
  return octets[0] === 10 || octets[0] === 127 ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
    (octets[0] === 192 && octets[1] === 168) ||
    (octets[0] === 169 && octets[1] === 254);
};

export const normalizeUrl = (value) => {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const candidate = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  const parsed = new URL(candidate);
  if (!['https:', 'http:'].includes(parsed.protocol)) throw new Error('Only HTTPS websites are allowed.');
  if (parsed.protocol === 'http:' && !isLocalHttpHost(parsed.hostname)) {
    throw new Error('Unencrypted Internet websites are blocked. Use the HTTPS address instead.');
  }
  if (parsed.username || parsed.password) throw new Error('Do not put credentials in a website URL.');
  return parsed.toString();
};

export const safeString = (value, fallback = '') => {
  if (value === null || value === undefined) return fallback;
  const text = String(value);
  return text.trim() ? text : fallback;
};

export const slugify = (value = '') =>
  String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)+/g, '');

export const withinAllowlist = (url, allowlist = []) => {
  if (!allowlist.length) return true;
  try {
    const { hostname } = new URL(url);
    return allowlist.some((entry) => hostname.endsWith(entry));
  } catch {
    return false;
  }
};
