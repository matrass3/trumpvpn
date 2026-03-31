import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delayMs = 350): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedValue(value);
    }, Math.max(0, delayMs));
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debouncedValue;
}
