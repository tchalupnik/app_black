import React from "react";
import { JSONSchema7 } from "json-schema";

export interface SectionFormProps {
  schema: JSONSchema7;
  uiSchema: any;
  formData: any;
  onChange: (data: any) => void;
  onSubmit: () => void;
  disabled?: boolean;
  children?: React.ReactNode;
}

/**
 * Renders a JSON schema-based form for a config section.
 * Wraps RJSF form with custom UI schema and logic.
 */
const SectionForm: React.FC<SectionFormProps> = ({
  children,
}) => {
  // TODO: podłącz @rjsf/shadcn i custom widgety
  // Placeholder - tu będzie RJSF
  return (
    <form>
      {/* TODO: <Form schema={schema} uiSchema={uiSchema} ... /> */}
      {children}
    </form>
  );
};

export default SectionForm;
