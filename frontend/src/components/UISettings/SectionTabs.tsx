import React from "react";

export interface SectionTabsProps {
  sections: { name: string; title: string }[];
  activeSection: string;
  onSelect: (section: string) => void;
}

/**
 * Component for rendering section tabs/sidebar in ConfigEditor2.
 */
const SectionTabs: React.FC<SectionTabsProps> = ({ sections, activeSection, onSelect }) => {
  return (
    <div className="flex flex-col gap-2">
      {sections.map((section) => (
        <button
          key={section.name}
          className={`btn btn-sm ${activeSection === section.name ? "btn-primary" : "btn-ghost"}`}
          onClick={() => onSelect(section.name)}
        >
          {section.title || section.name}
        </button>
      ))}
    </div>
  );
};

export default SectionTabs;
