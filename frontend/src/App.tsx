import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { createContext, useEffect, useState } from 'react';
import ConfigEditor from './components/ConfigEditor';
import LogViewer from './components/LogViewer';
import OutputsView from './components/OutputsView';
import InputsView from './components/InputsView';
import SensorView from './components/SensorView';
import HelpView from './components/HelpView';
import LoginView from './components/LoginView';
import Layout from './components/Layout';
import LoadingSpinner from './components/LoadingSpinner';
import { useWebSocket, StateUpdate } from './hooks/useWebSocket';
import { AuthProvider, useAuth } from './hooks/useAuth';
import { useLocation } from 'react-router-dom';

export const WebSocketContext = createContext<{
  outputs: StateUpdate['data'][];
  inputs: StateUpdate['data'][];
  sensors: StateUpdate['data'][];
}>({
  outputs: [],
  inputs: [],
  sensors: [],
});

// Protected route component
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, isAuthRequired } = useAuth();
  if (isLoading) {
    return <LoadingSpinner />;
  }
  
  if (!isAuthenticated && isAuthRequired) {
    return <Navigate to="/login" />;
  }
  
  return <>{children}</>;
}

function AppContent() {
  const [outputs, setOutputs] = useState<StateUpdate['data'][]>([]);
  const [inputs, setInputs] = useState<StateUpdate['data'][]>([]);
  const [sensors, setSensors] = useState<StateUpdate['data'][]>([]);
  const { isAuthenticated, isAuthRequired } = useAuth();
  const { error, addMessageListener } = useWebSocket();
  const location = useLocation();
  const isLoginPage = location.pathname === '/login';

  useEffect(() => {
    console.log("WebSocket state:", { isAuthenticated, isAuthRequired });
    
    // Clear states when not authenticated and auth is required
    if (!isAuthenticated && isAuthRequired) {
      setOutputs([]);
      setInputs([]);
      setSensors([]);
      return;
    }

    // Only set up listeners if authenticated or auth not required
    if (isAuthenticated || !isAuthRequired) {
      const unsubscribe = addMessageListener((message: StateUpdate) => {
        if (message.type === 'output') {
          setOutputs(prev => {
            const index = prev.findIndex(o => o.name === message.data.name);
            if (index >= 0) {
              const prevOutput = prev[index];
              if (prevOutput.state === message.data.state) {
                return prev; // No change needed
              }
              const newOutputs = [...prev];
              newOutputs[index] = message.data;
              return newOutputs;
            }
            return [...prev, message.data];
          });
        } else if (message.type === 'input') {
          setInputs(prev => {
            const index = prev.findIndex(i => i.name === message.data.name);
            if (index >= 0) {
              const prevInput = prev[index];
              if (prevInput.state === message.data.state) {
                return prev; // No change needed
              }
              const newInputs = [...prev];
              newInputs[index] = message.data;
              return newInputs;
            }
            return [...prev, message.data];
          });
        } else if (message.type === 'modbus_sensor' || message.type === 'sensor') {
          setSensors(prev => {
            const index = prev.findIndex(s => s.name === message.data.name);
            if (index >= 0) {
              const prevSensor = prev[index];
              if (prevSensor.state === message.data.state) {
                return prev; // No change needed
              }
              const newSensors = [...prev];
              newSensors[index] = message.data;
              return newSensors;
            }
            return [...prev, message.data];
          });
        }
      });

      return () => {
        unsubscribe();
      };
    }
  }, [addMessageListener, isAuthenticated, isAuthRequired]);

  if (isLoginPage) {
    return <LoginView />;
  }

  if (error && (isAuthenticated || !isAuthRequired)) {
    return <div>Error: {error}</div>;
  }

  return (
    <WebSocketContext.Provider value={{ outputs, inputs, sensors }}>
      <Routes>
        <Route path="/outputs" element={
          <ProtectedRoute>
            <Layout>
              <OutputsView />
            </Layout>
          </ProtectedRoute>
        } />
        <Route path="/inputs" element={
          <ProtectedRoute>
            <Layout>
              <InputsView />
            </Layout>
          </ProtectedRoute>
        } />
        <Route path="/config" element={
          <ProtectedRoute>
            <Layout>
              <ConfigEditor />
            </Layout>
          </ProtectedRoute>
        } />
        <Route path="/logs" element={
          <ProtectedRoute>
            <Layout>
              <LogViewer />
            </Layout>
          </ProtectedRoute>
        } />
        <Route path="/sensors" element={
          <ProtectedRoute>
            <Layout>
              <SensorView />
            </Layout>
          </ProtectedRoute>
        } />
        <Route path="/help" element={
          <ProtectedRoute>
            <Layout>
              <HelpView />
            </Layout>
          </ProtectedRoute>
        } />
        <Route path="/" element={<Navigate to="/outputs" replace />} />
      </Routes>
    </WebSocketContext.Provider>
  );
}

export default function App() {
  return (
    <Router>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </Router>
  );
}
