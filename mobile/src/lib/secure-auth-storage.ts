import * as SecureStore from 'expo-secure-store';

import type { SupportedStorage } from '@supabase/supabase-js';

// Keychain implementations have historically rejected values around 2 KB.
// Supabase sessions can exceed that, so each value is committed as small,
// generation-scoped chunks and the manifest is swapped last.
const CHUNK_CHARACTERS = 440;
const PREFIX = 'reelmate.auth';

type Manifest = { generation: string; chunks: number };

const hashKey = (value: string) => {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
};

const rootKey = (key: string) => `${PREFIX}.${hashKey(key)}`;
const manifestKey = (key: string) => `${rootKey(key)}.manifest`;
const chunkKey = (key: string, generation: string, index: number) =>
  `${rootKey(key)}.${generation}.${index}`;

const parseManifest = (value: string | null): Manifest | null => {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Partial<Manifest>;
    if (
      typeof parsed.generation === 'string' &&
      /^[a-z0-9]+$/i.test(parsed.generation) &&
      Number.isInteger(parsed.chunks) &&
      Number(parsed.chunks) >= 0 &&
      Number(parsed.chunks) <= 128
    ) {
      return { generation: parsed.generation, chunks: Number(parsed.chunks) };
    }
  } catch {
    // A partial/corrupt manifest is treated as a signed-out session.
  }
  return null;
};

const deleteGeneration = async (key: string, manifest: Manifest | null) => {
  if (!manifest) return;
  await Promise.all(
    Array.from({ length: manifest.chunks }, (_, index) =>
      SecureStore.deleteItemAsync(chunkKey(key, manifest.generation, index)),
    ),
  );
};

export const secureAuthStorage: SupportedStorage = {
  async getItem(key) {
    const manifest = parseManifest(
      await SecureStore.getItemAsync(manifestKey(key)),
    );
    if (!manifest) return null;
    const chunks = await Promise.all(
      Array.from({ length: manifest.chunks }, (_, index) =>
        SecureStore.getItemAsync(chunkKey(key, manifest.generation, index)),
      ),
    );
    return chunks.every((chunk): chunk is string => chunk !== null)
      ? chunks.join('')
      : null;
  },

  async setItem(key, value) {
    const previous = parseManifest(
      await SecureStore.getItemAsync(manifestKey(key)),
    );
    const generation = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    const chunks = Array.from(
      { length: Math.ceil(value.length / CHUNK_CHARACTERS) },
      (_, index) =>
        value.slice(index * CHUNK_CHARACTERS, (index + 1) * CHUNK_CHARACTERS),
    );
    await Promise.all(
      chunks.map((chunk, index) =>
        SecureStore.setItemAsync(chunkKey(key, generation, index), chunk, {
          keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
        }),
      ),
    );
    await SecureStore.setItemAsync(
      manifestKey(key),
      JSON.stringify({ generation, chunks: chunks.length } satisfies Manifest),
      { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
    );
    await deleteGeneration(key, previous);
  },

  async removeItem(key) {
    const manifest = parseManifest(
      await SecureStore.getItemAsync(manifestKey(key)),
    );
    await SecureStore.deleteItemAsync(manifestKey(key));
    await deleteGeneration(key, manifest);
  },
};
