/** #384: shared mic-device preference for every getUserMedia call. */

const KEY = "fleeting.micDeviceId";

export function storedMicId(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function storeMicId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(KEY, id);
    else window.localStorage.removeItem(KEY);
  } catch {
    /* private mode — preference just won't persist */
  }
}

export function audioConstraints(): MediaTrackConstraints {
  const id = storedMicId();
  return {
    echoCancellation: true,
    noiseSuppression: true,
    ...(id ? { deviceId: { ideal: id } } : {}),
  };
}
