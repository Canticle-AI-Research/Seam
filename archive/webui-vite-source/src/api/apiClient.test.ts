import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  fetchHealth,
  fetchStats,
  fetchCompile,
  fetchSearch,
  fetchContext,
  fetchPersist,
  fetchLosslessCompress,
} from './apiClient';

function installStorage(values: Record<string, string> = {}, sessionValues: Record<string, string> = {}) {
  const store = new Map(Object.entries(values));
  const sessionStore = new Map(Object.entries(sessionValues));
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: vi.fn((key: string) => store.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => store.set(key, value)),
      removeItem: vi.fn((key: string) => store.delete(key)),
    },
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: vi.fn((key: string) => sessionStore.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => sessionStore.set(key, value)),
      removeItem: vi.fn((key: string) => sessionStore.delete(key)),
    },
  });
}

function installFetch(response: Response) {
  const fetchMock = vi.fn(async () => response);
  Object.defineProperty(globalThis, 'fetch', {
    configurable: true,
    value: fetchMock,
  });
  return fetchMock;
}

describe('apiClient', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('exports fetchHealth and it is a function', () => {
    expect(fetchHealth).toBeDefined();
    expect(typeof fetchHealth).toBe('function');
  });

  it('exports fetchStats and it is a function', () => {
    expect(fetchStats).toBeDefined();
    expect(typeof fetchStats).toBe('function');
  });

  it('exports fetchCompile and it is a function', () => {
    expect(fetchCompile).toBeDefined();
    expect(typeof fetchCompile).toBe('function');
  });

  it('exports fetchSearch and it is a function', () => {
    expect(fetchSearch).toBeDefined();
    expect(typeof fetchSearch).toBe('function');
  });

  it('exports fetchContext and it is a function', () => {
    expect(fetchContext).toBeDefined();
    expect(typeof fetchContext).toBe('function');
  });

  it('exports fetchPersist and it is a function', () => {
    expect(fetchPersist).toBeDefined();
    expect(typeof fetchPersist).toBe('function');
  });

  it('exports fetchLosslessCompress and it is a function', () => {
    expect(fetchLosslessCompress).toBeDefined();
    expect(typeof fetchLosslessCompress).toBe('function');
  });

  it('uses the default local API base URL without a saved setting', async () => {
    installStorage();
    const fetchMock = installFetch(Response.json({ status: 'ok' }));

    await expect(fetchHealth()).resolves.toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/health',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    );
  });

  it('adds bearer authorization from session storage', async () => {
    installStorage({
      'seam-webui-api-url': 'http://127.0.0.1:9999/',
    }, {
      'seam-webui-api-token': 'test-token',
    });
    const fetchMock = installFetch(Response.json({ total_records: 3 }));

    await expect(fetchStats()).resolves.toEqual({ total_records: 3 });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:9999/stats',
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer test-token',
        },
      }),
    );
  });

  it('marks unauthorized protected endpoints with a stable error code', async () => {
    installStorage();
    installFetch(new Response('nope', { status: 401 }));

    await expect(fetchCompile({ text: 'x' })).rejects.toMatchObject({ code: 'UNAUTHORIZED' });
  });

  it('marks browser fetch failures as disconnected', async () => {
    installStorage();
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      value: vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    });

    await expect(fetchSearch('memory')).rejects.toMatchObject({ code: 'DISCONNECTED' });
  });
});
