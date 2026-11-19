// The minimum for the readers, documented in README.md under Run from source.
export const MIN_PYTHON = '3.14';

export function pythonMeetsMinimum(version: string): boolean {
  const v = /^(\d+)\.(\d+)(?:\.|$)/.exec(version);
  const [major, minor] = MIN_PYTHON.split('.').map(Number);
  return !!v && (+v[1] > major || (+v[1] === major && +v[2] >= minor));
}

// The bundled iPhone wheels use the CPython 3.14 ABI (README.md, Run from source).
export function pythonSupported(version: string): boolean {
  const v = /^(\d+)\.(\d+)(?:\.|$)/.exec(version);
  const [major, minor] = MIN_PYTHON.split('.').map(Number);
  return !!v && +v[1] === major && +v[2] === minor;
}
