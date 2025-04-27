import React from "react";

const VenetianSlats: React.FC<{ count?: number; active?: number }> = ({ count = 12, active = 100 }) => {
  // active: 0-100, how many slats are visually highlighted (for tilt preview)
  const slats = Array.from({ length: count });
  const activeCount = Math.round((active / 100) * count);
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      width: '60px',
      height: '80px',
      background: '#f8f8fa',
      borderRadius: '0 0 1.2rem 1.2rem',
      overflow: 'hidden',
      borderTop: '2px solid #eee',
      margin: '0.5rem auto',
      boxShadow: '0 1px 4px #0001',
      padding: '2px 0'
    }}>
      {slats.map((_, i) => (
        <div
          key={i}
          style={{
            height: '5px',
            margin: '1px 0',
            background: i < activeCount ? '#a084ca' : '#d1b8ea',
            borderRadius: '2.5px',
            width: '90%'
          }}
        />
      ))}
    </div>
  );
};

export default VenetianSlats;
