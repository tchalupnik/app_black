import { useState, useEffect } from 'react';

export function useTheme() {
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    // Get initial theme
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);

    // Listen for theme changes
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === 'data-theme') {
          const newTheme = document.documentElement.getAttribute('data-theme') || 'dark';
          setTheme(newTheme);
        }
      });
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    });

    return () => observer.disconnect();
  }, []);

  return theme;
}
