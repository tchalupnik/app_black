import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';

const CHECK_INTERVAL = 30000; // 30 seconds
const MIN_CHECK_DURATION = 5000; // 5 seconds

export function useApiAvailability() {
  const [isApiAvailable, setIsApiAvailable] = useState(true);
  const [isChecking, setIsChecking] = useState(true);
  const [nextCheckTime, setNextCheckTime] = useState<Date>(new Date(Date.now() + CHECK_INTERVAL));
  const intervalRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const checkStartTimeRef = useRef<number | undefined>(undefined);

  const setupInterval = useCallback(() => {
    // Clear existing interval if any
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    // Set up new interval
    intervalRef.current = setInterval(() => {
      checkApiAvailability();
    }, CHECK_INTERVAL);
  }, []);

  const ensureMinCheckDuration = async () => {
    const checkStartTime = checkStartTimeRef.current || Date.now();
    const elapsedTime = Date.now() - checkStartTime;
    if (elapsedTime < MIN_CHECK_DURATION) {
      await new Promise(resolve => setTimeout(resolve, MIN_CHECK_DURATION - elapsedTime));
    }
  };

  const checkApiAvailability = useCallback(async () => {
    setIsChecking(true);
    checkStartTimeRef.current = Date.now();

    try {
      await axios.get('/api/version');
      await ensureMinCheckDuration();
      setIsApiAvailable(true);
    } catch (error) {
      await ensureMinCheckDuration();
      setIsApiAvailable(false);
    } finally {
      setIsChecking(false);
      setNextCheckTime(new Date(Date.now() + CHECK_INTERVAL));
      checkStartTimeRef.current = undefined;
    }
  }, []);

  // Manual check function that also resets the interval
  const checkNow = useCallback(async () => {
    await checkApiAvailability();
    setupInterval();
  }, [checkApiAvailability, setupInterval]);

  useEffect(() => {
    // Initial check
    checkApiAvailability();
    // Set up initial interval
    setupInterval();

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [checkApiAvailability, setupInterval]);

  return { 
    isApiAvailable, 
    isChecking, 
    nextCheckTime,
    nextCheckInMs: Math.max(0, nextCheckTime.getTime() - Date.now()),
    checkNow
  };
}
