import React from "react";

export interface SectionHeaderProps {
  sectionTitle: string;
  unsaved: boolean;
  onSave: () => void;
  onReset: () => void;
  isSaving: boolean;
}

/**
 * Header for each configuration section: title, save/reset buttons, status.
 */
const SectionHeader: React.FC<SectionHeaderProps> = ({
  sectionTitle,
  unsaved,
  onSave,
  onReset,
  isSaving,
}) => {
  return (
    <div className="flex items-center justify-between py-2">
      <h2 className="text-xl font-bold">{sectionTitle}</h2>
      <div className="flex gap-2">
        <button
          className="btn btn-success btn-sm"
          onClick={onSave}
          disabled={!unsaved || isSaving}
        >
          {isSaving ? "Saving..." : "Save"}
        </button>
        <button
          className="btn btn-outline btn-sm"
          onClick={onReset}
          disabled={!unsaved || isSaving}
        >
          Reset
        </button>
      </div>
    </div>
  );
};

export default SectionHeader;
