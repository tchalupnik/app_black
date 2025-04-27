import React from "react";

// A horizontal bar with a dashed background, showing the tilt position as a colored foreground
const TiltBar: React.FC<{
  value: number; // 0-100
  disabled?: boolean;
}> = ({ value, disabled }) => {
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: 16,
        background: "repeating-linear-gradient(90deg, #eee, #eee 8px, #fff 8px, #fff 16px)",
        borderRadius: 8,
        margin: "4px 0",
        opacity: disabled ? 0.5 : 1,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          height: "100%",
          width: `${value}%`,
          background: "#a084ca",
          borderRadius: 8,
          transition: "width 0.2s",
        }}
      />
      {/* Thumb */}
      <div
        style={{
          position: "absolute",
          left: `calc(${value}% - 10px)`,
          top: 2,
          width: 12,
          height: 12,
          background: "#7b4ae2",
          borderRadius: "50%",
          border: "2px solid #fff",
          boxShadow: "0 1px 4px #0002",
          pointerEvents: "none",
          transition: "left 0.2s",
        }}
      />
    </div>
  );
};

export default TiltBar;
