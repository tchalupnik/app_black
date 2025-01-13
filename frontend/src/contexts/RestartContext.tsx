import React, { createContext, useContext, useState } from 'react';

interface RestartContextType {
  isRestarting: boolean;
  setIsRestarting: (isRestarting: boolean) => void;
}

const RestartContext = createContext<RestartContextType | undefined>(undefined);

export function RestartProvider({ children }: { children: React.ReactNode }) {
  const [isRestarting, setIsRestarting] = useState(false);

  return (
    <RestartContext.Provider value={{ isRestarting, setIsRestarting }}>
      {children}
    </RestartContext.Provider>
  );
}

export function useRestart() {
  const context = useContext(RestartContext);
  if (context === undefined) {
    throw new Error('useRestart must be used within a RestartProvider');
  }
  return context;
}
