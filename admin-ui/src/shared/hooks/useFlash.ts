import { useState } from "react";

type FlashState = {
  message: string;
  error: string;
};

export function useFlash() {
  const [state, setState] = useState<FlashState>({ message: "", error: "" });

  function showMessage(message: string) {
    setState({ message: String(message || ""), error: "" });
  }

  function showError(error: string) {
    setState({ message: "", error: String(error || "") });
  }

  function clear() {
    setState({ message: "", error: "" });
  }

  return {
    ...state,
    showMessage,
    showError,
    clear,
  };
}
