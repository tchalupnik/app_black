import { useState, useEffect } from 'react';
import axios from 'axios';

export function useDeviceName() {
  const [deviceName, setDeviceName] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchDeviceName = async () => {
      try {
        const response = await axios.get('/api/name');
        setDeviceName(response.data.name);
      } catch (error) {
        console.error('Failed to fetch device name:', error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchDeviceName();
  }, []);

  return { deviceName, isLoading };
}
