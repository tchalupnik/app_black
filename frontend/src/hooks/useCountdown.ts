import { useState, useEffect } from 'react';

export function useCountdown(targetDate: Date) {
  const [secondsLeft, setSecondsLeft] = useState(0);

  useEffect(() => {
    const calculateTimeLeft = () => {
      const difference = Math.max(0, targetDate.getTime() - Date.now());
      return Math.ceil(difference / 1000);
    };

    // Initial calculation
    setSecondsLeft(calculateTimeLeft());

    // Update every second
    const timer = setInterval(() => {
      const timeLeft = calculateTimeLeft();
      setSecondsLeft(timeLeft);
    }, 1000);

    // Cleanup
    return () => clearInterval(timer);
  }, [targetDate]);

  return secondsLeft;
}
